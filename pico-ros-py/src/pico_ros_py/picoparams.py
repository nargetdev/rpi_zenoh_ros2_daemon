# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 the pico-ros-py authors
#
# A Python re-imagining of Pico-ROS `picoparams` (BSD-3-Clause, Ubiquity
# Robotics). This module keeps Pico-ROS's *semantics* -- a small parameter
# backend interface (ref/get/type/set/describe/list/prefixes) fronting the six
# standard ROS 2 `rcl_interfaces` parameter services -- but is implemented in
# Python on top of `zenoh_ros2_sdk` for runtimes like the Raspberry Pi.
#
# The types and the backend are pure Python with no transport dependency, so
# they import and unit-test without zenoh / ROS installed. Only `ParameterServer`
# touches the SDK, and it does so lazily.
"""Pico-ROS-style ROS 2 parameter server for Python runtimes."""

from __future__ import annotations

import enum
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .picoros import Node

LOGGER = logging.getLogger("pico_ros_py.picoparams")


# ---------------------------------------------------------------------------
# Parameter types (mirrors rcl_interfaces/msg/ParameterType and Pico-ROS
# pp_ParameterType -- the integer values are wire-significant, do not reorder).
# ---------------------------------------------------------------------------
class ParameterType(enum.IntEnum):
    NOT_SET = 0
    BOOL = 1
    INTEGER = 2
    DOUBLE = 3
    STRING = 4
    BYTE_ARRAY = 5
    BOOL_ARRAY = 6
    INTEGER_ARRAY = 7
    DOUBLE_ARRAY = 8
    STRING_ARRAY = 9


_ARRAY_TYPES = frozenset(
    {
        ParameterType.BYTE_ARRAY,
        ParameterType.BOOL_ARRAY,
        ParameterType.INTEGER_ARRAY,
        ParameterType.DOUBLE_ARRAY,
        ParameterType.STRING_ARRAY,
    }
)


@dataclass(frozen=True)
class FloatingPointRange:
    """Mirrors rcl_interfaces/msg/FloatingPointRange."""

    from_value: float
    to_value: float
    step: float = 0.0


@dataclass(frozen=True)
class IntegerRange:
    """Mirrors rcl_interfaces/msg/IntegerRange."""

    from_value: int
    to_value: int
    step: int = 0


@dataclass
class ParameterDescriptor:
    """Mirrors rcl_interfaces/msg/ParameterDescriptor (and Pico-ROS
    pp_ParameterDescriptor)."""

    name: str = ""
    type: ParameterType = ParameterType.NOT_SET
    description: str = ""
    additional_constraints: str = ""
    read_only: bool = False
    dynamic_typing: bool = False
    floating_point_range: Optional[FloatingPointRange] = None
    integer_range: Optional[IntegerRange] = None


@dataclass
class ParameterValue:
    """Transport-neutral parameter value: a ROS parameter type tag plus a
    native Python value. Conversion to/from the rosbags rcl_interfaces message
    lives in `_rcl.py`."""

    type: ParameterType
    value: Any = None

    @property
    def is_array(self) -> bool:
        return self.type in _ARRAY_TYPES

    @classmethod
    def not_set(cls) -> "ParameterValue":
        return cls(ParameterType.NOT_SET, None)

    @classmethod
    def from_python(cls, value: Any) -> "ParameterValue":
        """Infer a ParameterType from a native Python value.

        Mirrors how rclpy infers a parameter's type from its initial value.
        """
        if value is None:
            return cls(ParameterType.NOT_SET, None)
        if isinstance(value, bool):
            return cls(ParameterType.BOOL, value)
        if isinstance(value, int):
            return cls(ParameterType.INTEGER, value)
        if isinstance(value, float):
            return cls(ParameterType.DOUBLE, value)
        if isinstance(value, str):
            return cls(ParameterType.STRING, value)
        if isinstance(value, (bytes, bytearray)):
            return cls(ParameterType.BYTE_ARRAY, bytes(value))
        if isinstance(value, (list, tuple)):
            seq = list(value)
            if not seq:
                # Ambiguous empty sequence; default to an integer array.
                return cls(ParameterType.INTEGER_ARRAY, [])
            head = seq[0]
            if isinstance(head, bool):
                return cls(ParameterType.BOOL_ARRAY, [bool(x) for x in seq])
            if isinstance(head, int):
                return cls(ParameterType.INTEGER_ARRAY, [int(x) for x in seq])
            if isinstance(head, float):
                return cls(ParameterType.DOUBLE_ARRAY, [float(x) for x in seq])
            if isinstance(head, str):
                return cls(ParameterType.STRING_ARRAY, [str(x) for x in seq])
        raise TypeError(f"cannot infer ParameterType for value of type {type(value)!r}")


@dataclass
class Parameter:
    """A named parameter value (mirrors rcl_interfaces/msg/Parameter)."""

    name: str
    value: ParameterValue


# ---------------------------------------------------------------------------
# Backend interface -- the Python analogue of Pico-ROS's picoparams_interface_t
# (f_ref / f_get / f_type / f_set / f_describe / f_list / f_prefixes).
#
# A "handle" is any opaque object your `ref()` returns for a parameter name;
# the other methods receive it back. Subclass this to wire parameters straight
# into your own application state, exactly like the C `api_param_*` callbacks.
# ---------------------------------------------------------------------------
class ParameterBackend:
    """Abstract parameter backend. Override the seven hooks."""

    def ref(self, name: str) -> Optional[Any]:
        raise NotImplementedError

    def get(self, handle: Any) -> ParameterValue:
        raise NotImplementedError

    def type(self, handle: Any) -> ParameterType:
        raise NotImplementedError

    def describe(self, handle: Any) -> ParameterDescriptor:
        raise NotImplementedError

    def set(self, handle: Any, value: ParameterValue) -> tuple[bool, str]:
        """Return (successful, reason). reason is "" on success."""
        raise NotImplementedError

    def list(self, prefix: Optional[str]) -> list[str]:
        """Return fully-qualified parameter names under `prefix` (None = all)."""
        raise NotImplementedError

    def prefixes(self, prefix: Optional[str]) -> list[str]:
        """Return parameter sub-namespaces under `prefix` (None = all)."""
        raise NotImplementedError


@dataclass
class _Entry:
    descriptor: ParameterDescriptor
    value: ParameterValue


class DictParameterBackend(ParameterBackend):
    """Convenience backend backed by an in-memory ordered dict.

    This is the easy on-ramp (the equivalent of the static `params[]` array in
    the Pico-ROS `params_server.c` example). It enforces type, range, and
    read-only constraints from each parameter's descriptor.
    """

    def __init__(self) -> None:
        self._params: "OrderedDict[str, _Entry]" = OrderedDict()
        self.on_set: Optional[Callable[[str, ParameterValue], None]] = None

    # -- declaration -------------------------------------------------------
    def declare(
        self,
        name: str,
        value: Any,
        *,
        descriptor: Optional[ParameterDescriptor] = None,
        description: str = "",
        read_only: bool = False,
        integer_range: Optional[IntegerRange] = None,
        floating_point_range: Optional[FloatingPointRange] = None,
    ) -> "DictParameterBackend":
        """Declare a parameter from a native Python value (chainable)."""
        pv = value if isinstance(value, ParameterValue) else ParameterValue.from_python(value)
        if descriptor is None:
            descriptor = ParameterDescriptor(
                name=name,
                type=pv.type,
                description=description,
                read_only=read_only,
                integer_range=integer_range,
                floating_point_range=floating_point_range,
            )
        else:
            descriptor.name = name
            if descriptor.type == ParameterType.NOT_SET:
                descriptor.type = pv.type
        self._params[name] = _Entry(descriptor=descriptor, value=pv)
        return self

    def value_of(self, name: str) -> Any:
        return self._params[name].value.value

    def __contains__(self, name: str) -> bool:
        return name in self._params

    # -- backend hooks -----------------------------------------------------
    def ref(self, name: str) -> Optional[str]:
        return name if name in self._params else None

    def get(self, handle: Any) -> ParameterValue:
        return self._params[handle].value

    def type(self, handle: Any) -> ParameterType:
        return self._params[handle].descriptor.type

    def describe(self, handle: Any) -> ParameterDescriptor:
        return self._params[handle].descriptor

    def set(self, handle: Any, value: ParameterValue) -> tuple[bool, str]:
        entry = self._params[handle]
        desc = entry.descriptor
        if desc.read_only:
            return False, "parameter is read-only"
        if not desc.dynamic_typing and value.type != desc.type:
            return (
                False,
                f"wrong type: expected {desc.type.name}, got {value.type.name}",
            )
        ok, reason = self._check_range(desc, value)
        if not ok:
            return False, reason
        entry.value = value
        if self.on_set is not None:
            try:
                self.on_set(handle, value)
            except Exception:  # pragma: no cover - user callback
                LOGGER.exception("on_set callback failed for %s", handle)
        return True, ""

    @staticmethod
    def _check_range(desc: ParameterDescriptor, value: ParameterValue) -> tuple[bool, str]:
        if value.type == ParameterType.INTEGER and desc.integer_range is not None:
            r = desc.integer_range
            if not (r.from_value <= value.value <= r.to_value):
                return False, f"value out of range [{r.from_value}, {r.to_value}]"
        if value.type == ParameterType.DOUBLE and desc.floating_point_range is not None:
            r = desc.floating_point_range
            if not (r.from_value <= value.value <= r.to_value):
                return False, f"value out of range [{r.from_value}, {r.to_value}]"
        return True, ""

    def _names_under(self, prefix: Optional[str]) -> list[str]:
        if not prefix:
            return list(self._params.keys())
        return [
            name
            for name in self._params
            if name == prefix or name.startswith(prefix + ".")
        ]

    def list(self, prefix: Optional[str]) -> list[str]:
        return self._names_under(prefix)

    def prefixes(self, prefix: Optional[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for name in self._names_under(prefix):
            parts = name.split(".")
            for i in range(1, len(parts)):
                pfx = ".".join(parts[:i])
                if pfx not in seen:
                    seen.add(pfx)
                    out.append(pfx)
        return out


# ---------------------------------------------------------------------------
# Parameter server -- declares the six rcl_interfaces parameter services on a
# Node, plus a /parameter_events publisher. Mirrors Pico-ROS picoparams_init.
# ---------------------------------------------------------------------------

# (ros service name, ROS 2 service type, handler attribute) -- the same six
# services Pico-ROS's picoparams.c declares.
_PARAM_SERVICES = [
    ("list_parameters", "rcl_interfaces/srv/ListParameters", "_handle_list"),
    ("get_parameters", "rcl_interfaces/srv/GetParameters", "_handle_get"),
    ("get_parameter_types", "rcl_interfaces/srv/GetParameterTypes", "_handle_get_types"),
    ("set_parameters", "rcl_interfaces/srv/SetParameters", "_handle_set"),
    ("set_parameters_atomically", "rcl_interfaces/srv/SetParametersAtomically", "_handle_set_atomic"),
    ("describe_parameters", "rcl_interfaces/srv/DescribeParameters", "_handle_describe"),
]


class ParameterServer:
    """Serves the standard ROS 2 parameter interface for a `Node`.

    Once started, the owning node responds to `ros2 param list/get/set/describe`
    and to rqt_reconfigure, with the actual parameter storage delegated to a
    `ParameterBackend`.
    """

    def __init__(
        self,
        node: "Node",
        backend: ParameterBackend,
        *,
        publish_events: bool = True,
    ) -> None:
        self.node = node
        self.backend = backend
        self.publish_events = publish_events
        self._services: list[Any] = []
        self._event_pub: Any = None
        self._started = False

    def start(self) -> "ParameterServer":
        if self._started:
            return self
        # Lazy import so the pure types/backend above stay importable without
        # zenoh_ros2_sdk installed.
        from . import _rcl

        self._rcl = _rcl
        for service_name, srv_type, handler_attr in _PARAM_SERVICES:
            handler = getattr(self, handler_attr)
            full_name = self.node.resolve_name(service_name)
            srv = self.node.create_service(full_name, srv_type, handler)
            self._services.append(srv)
        if self.publish_events:
            try:
                self._event_pub = self.node.create_publisher(
                    "/parameter_events", "rcl_interfaces/msg/ParameterEvent"
                )
            except Exception:  # pragma: no cover - non-fatal
                LOGGER.exception("could not create /parameter_events publisher")
        self._started = True
        LOGGER.info(
            "parameter server started for node %s (%d services)",
            self.node.fully_qualified_name,
            len(self._services),
        )
        return self

    def stop(self) -> None:
        for srv in self._services:
            try:
                srv.close()
            except Exception:  # pragma: no cover - best effort
                LOGGER.debug("error closing parameter service", exc_info=True)
        self._services.clear()
        if self._event_pub is not None:
            try:
                self._event_pub.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._event_pub = None
        self._started = False

    # -- service handlers --------------------------------------------------
    def _handle_list(self, request: Any) -> Any:
        prefixes = list(getattr(request, "prefixes", []) or [])
        targets: list[Optional[str]] = prefixes if prefixes else [None]
        names: list[str] = []
        sub_prefixes: list[str] = []
        for pfx in targets:
            names.extend(self.backend.list(pfx))
            sub_prefixes.extend(self.backend.prefixes(pfx))
        # de-dup while preserving order
        names = list(dict.fromkeys(names))
        sub_prefixes = list(dict.fromkeys(sub_prefixes))
        return self._rcl.build_list_parameters_response(
            self._response_class("list_parameters"), names, sub_prefixes
        )

    def _handle_get(self, request: Any) -> Any:
        names = list(getattr(request, "names", []) or [])
        values: list[ParameterValue] = []
        for name in names:
            handle = self.backend.ref(name)
            values.append(
                self.backend.get(handle) if handle is not None else ParameterValue.not_set()
            )
        return self._rcl.build_get_parameters_response(
            self._response_class("get_parameters"), values
        )

    def _handle_get_types(self, request: Any) -> Any:
        names = list(getattr(request, "names", []) or [])
        types: list[int] = []
        for name in names:
            handle = self.backend.ref(name)
            types.append(int(self.backend.type(handle)) if handle is not None else 0)
        return self._rcl.build_get_parameter_types_response(
            self._response_class("get_parameter_types"), types
        )

    def _handle_describe(self, request: Any) -> Any:
        names = list(getattr(request, "names", []) or [])
        descriptors: list[ParameterDescriptor] = []
        for name in names:
            handle = self.backend.ref(name)
            if handle is not None:
                desc = self.backend.describe(handle)
            else:
                desc = ParameterDescriptor(name=name)
            desc.name = name  # echo requested name (matches picoparams behaviour)
            descriptors.append(desc)
        return self._rcl.build_describe_parameters_response(
            self._response_class("describe_parameters"), descriptors
        )

    def _handle_set(self, request: Any) -> Any:
        results = self._apply_sets(getattr(request, "parameters", []) or [])
        return self._rcl.build_set_parameters_response(
            self._response_class("set_parameters"), results
        )

    def _handle_set_atomic(self, request: Any) -> Any:
        params = list(getattr(request, "parameters", []) or [])
        # Validate all first; only commit if every set succeeds.
        previews: list[tuple[str, ParameterValue]] = []
        for p in params:
            name = getattr(p, "name", "")
            pv = self._rcl.param_value_from_msg(getattr(p, "value", None))
            handle = self.backend.ref(name)
            if handle is None:
                return self._rcl.build_set_parameters_atomically_response(
                    self._response_class("set_parameters_atomically"),
                    False,
                    f"parameter not found: {name}",
                )
            previews.append((name, pv))
        for name, pv in previews:
            ok, reason = self.backend.set(self.backend.ref(name), pv)
            if not ok:
                return self._rcl.build_set_parameters_atomically_response(
                    self._response_class("set_parameters_atomically"), False, reason
                )
        self._emit_event(changed=previews)
        return self._rcl.build_set_parameters_atomically_response(
            self._response_class("set_parameters_atomically"), True, ""
        )

    def _apply_sets(self, params: list[Any]) -> list[tuple[bool, str]]:
        results: list[tuple[bool, str]] = []
        changed: list[tuple[str, ParameterValue]] = []
        for p in params:
            name = getattr(p, "name", "")
            handle = self.backend.ref(name)
            if handle is None:
                results.append((False, "parameter not found"))
                continue
            pv = self._rcl.param_value_from_msg(getattr(p, "value", None))
            ok, reason = self.backend.set(handle, pv)
            results.append((ok, reason))
            if ok:
                changed.append((name, pv))
        if changed:
            self._emit_event(changed=changed)
        return results

    def _emit_event(self, *, changed: list[tuple[str, ParameterValue]]) -> None:
        if self._event_pub is None:
            return
        try:
            self._rcl.publish_parameter_event(
                self._event_pub, self.node.fully_qualified_name, changed
            )
        except Exception:  # pragma: no cover - non-fatal
            LOGGER.debug("failed to publish parameter event", exc_info=True)

    def _response_class(self, service_name: str) -> Any:
        for srv, (name, _type, _h) in zip(self._services, _PARAM_SERVICES):
            if name == service_name:
                return srv.response_class
        raise KeyError(service_name)

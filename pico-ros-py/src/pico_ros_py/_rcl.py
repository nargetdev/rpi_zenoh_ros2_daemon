# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 the pico-ros-py authors
"""Glue between pico-ros-py's neutral parameter types and the rosbags-generated
``rcl_interfaces`` messages used on the wire.

All message construction is centralised here. The field names and ordering
follow the ROS 2 ``rcl_interfaces`` definitions exactly:

  ParameterValue, Parameter, ParameterType, ParameterDescriptor,
  FloatingPointRange, IntegerRange, SetParametersResult,
  ListParametersResult, ParameterEvent

Numeric arrays are passed to rosbags as numpy arrays; sequences of nested
messages and string arrays are passed as plain lists.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from .picoparams import (
    FloatingPointRange,
    IntegerRange,
    ParameterDescriptor,
    ParameterType,
    ParameterValue,
)
from .picoserdes import get_message_class

_PV = "rcl_interfaces/msg/ParameterValue"
_PARAM = "rcl_interfaces/msg/Parameter"
_DESC = "rcl_interfaces/msg/ParameterDescriptor"
_FPR = "rcl_interfaces/msg/FloatingPointRange"
_IR = "rcl_interfaces/msg/IntegerRange"
_SPR = "rcl_interfaces/msg/SetParametersResult"
_LPR = "rcl_interfaces/msg/ListParametersResult"
_EVENT = "rcl_interfaces/msg/ParameterEvent"
_TIME = "builtin_interfaces/msg/Time"


# ---------------------------------------------------------------------------
# ParameterValue  <->  rcl_interfaces/msg/ParameterValue
# ---------------------------------------------------------------------------
def param_value_to_msg(pv: ParameterValue) -> Any:
    cls = get_message_class(_PV)
    fields = dict(
        type=int(pv.type),
        bool_value=False,
        integer_value=0,
        double_value=0.0,
        string_value="",
        byte_array_value=np.array([], dtype=np.uint8),
        bool_array_value=np.array([], dtype=np.bool_),
        integer_array_value=np.array([], dtype=np.int64),
        double_array_value=np.array([], dtype=np.float64),
        string_array_value=[],
    )
    t = pv.type
    if t == ParameterType.BOOL:
        fields["bool_value"] = bool(pv.value)
    elif t == ParameterType.INTEGER:
        fields["integer_value"] = int(pv.value)
    elif t == ParameterType.DOUBLE:
        fields["double_value"] = float(pv.value)
    elif t == ParameterType.STRING:
        fields["string_value"] = str(pv.value)
    elif t == ParameterType.BYTE_ARRAY:
        fields["byte_array_value"] = np.frombuffer(bytes(pv.value or b""), dtype=np.uint8)
    elif t == ParameterType.BOOL_ARRAY:
        fields["bool_array_value"] = np.array(list(pv.value or []), dtype=np.bool_)
    elif t == ParameterType.INTEGER_ARRAY:
        fields["integer_array_value"] = np.array(list(pv.value or []), dtype=np.int64)
    elif t == ParameterType.DOUBLE_ARRAY:
        fields["double_array_value"] = np.array(list(pv.value or []), dtype=np.float64)
    elif t == ParameterType.STRING_ARRAY:
        fields["string_array_value"] = [str(x) for x in (pv.value or [])]
    return cls(**fields)


def param_value_from_msg(msg: Any) -> ParameterValue:
    if msg is None:
        return ParameterValue.not_set()
    t = ParameterType(int(getattr(msg, "type", 0)))
    if t == ParameterType.BOOL:
        return ParameterValue(t, bool(msg.bool_value))
    if t == ParameterType.INTEGER:
        return ParameterValue(t, int(msg.integer_value))
    if t == ParameterType.DOUBLE:
        return ParameterValue(t, float(msg.double_value))
    if t == ParameterType.STRING:
        return ParameterValue(t, str(msg.string_value))
    if t == ParameterType.BYTE_ARRAY:
        return ParameterValue(t, bytes(bytearray(msg.byte_array_value)))
    if t == ParameterType.BOOL_ARRAY:
        return ParameterValue(t, [bool(x) for x in msg.bool_array_value])
    if t == ParameterType.INTEGER_ARRAY:
        return ParameterValue(t, [int(x) for x in msg.integer_array_value])
    if t == ParameterType.DOUBLE_ARRAY:
        return ParameterValue(t, [float(x) for x in msg.double_array_value])
    if t == ParameterType.STRING_ARRAY:
        return ParameterValue(t, [str(x) for x in msg.string_array_value])
    return ParameterValue.not_set()


def _parameter_msg(name: str, pv: ParameterValue) -> Any:
    cls = get_message_class(_PARAM)
    return cls(name=name, value=param_value_to_msg(pv))


# ---------------------------------------------------------------------------
# ParameterDescriptor -> rcl_interfaces/msg/ParameterDescriptor
# ---------------------------------------------------------------------------
def descriptor_to_msg(desc: ParameterDescriptor) -> Any:
    cls = get_message_class(_DESC)
    fpr: list[Any] = []
    ir: list[Any] = []
    if desc.floating_point_range is not None:
        r = desc.floating_point_range
        fpr = [get_message_class(_FPR)(
            from_value=float(r.from_value),
            to_value=float(r.to_value),
            step=float(r.step),
        )]
    if desc.integer_range is not None:
        r = desc.integer_range
        ir = [get_message_class(_IR)(
            from_value=int(r.from_value),
            to_value=int(r.to_value),
            step=int(r.step),
        )]
    return cls(
        name=desc.name,
        type=int(desc.type),
        description=desc.description,
        additional_constraints=desc.additional_constraints,
        read_only=bool(desc.read_only),
        dynamic_typing=bool(desc.dynamic_typing),
        floating_point_range=fpr,
        integer_range=ir,
    )


# ---------------------------------------------------------------------------
# Response builders (response_class is the SDK's response_msg_class)
# ---------------------------------------------------------------------------
def build_get_parameters_response(response_class: Any, values: list[ParameterValue]) -> Any:
    return response_class(values=[param_value_to_msg(v) for v in values])


def build_get_parameter_types_response(response_class: Any, types: list[int]) -> Any:
    return response_class(types=np.array(list(types), dtype=np.uint8))


def build_describe_parameters_response(
    response_class: Any, descriptors: list[ParameterDescriptor]
) -> Any:
    return response_class(descriptors=[descriptor_to_msg(d) for d in descriptors])


def build_list_parameters_response(
    response_class: Any, names: list[str], prefixes: list[str]
) -> Any:
    result = get_message_class(_LPR)(names=list(names), prefixes=list(prefixes))
    return response_class(result=result)


def build_set_parameters_response(
    response_class: Any, results: list[tuple[bool, str]]
) -> Any:
    spr = get_message_class(_SPR)
    return response_class(
        results=[spr(successful=ok, reason=reason) for ok, reason in results]
    )


def build_set_parameters_atomically_response(
    response_class: Any, successful: bool, reason: str
) -> Any:
    result = get_message_class(_SPR)(successful=bool(successful), reason=reason)
    return response_class(result=result)


# ---------------------------------------------------------------------------
# /parameter_events
# ---------------------------------------------------------------------------
def publish_parameter_event(
    event_pub: Any, node_fqn: str, changed: list[tuple[str, ParameterValue]]
) -> None:
    stamp = get_message_class(_TIME)(sec=0, nanosec=0)
    event_pub.publish(
        stamp=stamp,
        node=node_fqn,
        new_parameters=[],
        changed_parameters=[_parameter_msg(name, pv) for name, pv in changed],
        deleted_parameters=[],
    )

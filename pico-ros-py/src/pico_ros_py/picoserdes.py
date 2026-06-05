# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 the pico-ros-py authors
#
# Python analogue of Pico-ROS `picoserdes`. Pico-ROS hand-rolls CDR
# (de)serialization with Micro-CDR; here we delegate to the `zenoh_ros2_sdk`
# shared typestore (rosbags), which already does ROS 2-compatible CDR and
# type-hashing. This module is the thin "type access" seam.
"""Type registration / message-class access for pico-ros-py."""

from __future__ import annotations

from typing import Any, Optional


def get_session(router_ip: str = "127.0.0.1", router_port: int = 7447) -> Any:
    """Return the shared ZenohSession singleton (creates it on first call)."""
    from zenoh_ros2_sdk import ZenohSession

    return ZenohSession.get_instance(router_ip, router_port)


def get_message_class(type_name: str, definition: Optional[str] = None) -> Any:
    """Return (registering if needed) the message class for a ROS 2 type.

    Example: ``get_message_class("rcl_interfaces/msg/ParameterValue")``.
    """
    return get_session().register_message_type(definition, type_name)


def _ref_names(ftype: Any) -> list[str]:
    """Extract referenced complex type names from a rosbags field descriptor.

    Field descriptors look like ``(Nodetype.BASE, ('string', 0))`` or
    ``(Nodetype.NAME, 'pkg/msg/Type')`` or a SEQUENCE/ARRAY wrapping one of
    those. We only care about NAME references (nested messages).
    """
    kind = int(ftype[0])
    if kind == 2:  # NAME
        return [ftype[1]]
    if kind in (3, 4):  # ARRAY, SEQUENCE -> recurse into element descriptor
        return _ref_names(ftype[1][0])
    return []


def ensure_nested_types(session: Any, store_type: str) -> None:
    """Register any nested message types a service Request/Response references
    but that the SDK/rosbags left undefined.

    rosbags registers service types (`pkg/srv/msg/Name_Response`) whose nested
    fields reference a *shadow* ``pkg/srv/msg/Nested`` name, while only the
    canonical ``pkg/msg/Nested`` definition is actually registered. Serializing
    such a response then fails with a KeyError. We repair this by aliasing each
    missing shadow name to its canonical definition (the canonical fielddef's
    own nested refs are canonical, so a single-level alias suffices). General
    for any nested-message service, not just parameters.
    """
    store = session.store
    fd = store.fielddefs.get(store_type)
    if not fd:
        return
    for _field_name, ftype in fd[1]:
        for ref in _ref_names(ftype):
            if ref in store.fielddefs:
                continue
            _register_alias(session, ref)
            ensure_nested_types(session, ref)  # repair transitively


def _register_alias(session: Any, ref: str) -> None:
    store = session.store
    if ref in store.fielddefs:
        return
    canonical = ref.replace("/srv/msg/", "/msg/")
    if canonical not in store.fielddefs:
        try:
            session.register_message_type(None, canonical)
        except Exception:
            return
    if canonical in store.fielddefs:
        store.fielddefs[ref] = store.fielddefs[canonical]
        if canonical in store.types:
            store.types[ref] = store.types[canonical]
        session._registered_types[ref] = ref


def serialize(msg: Any, type_name: str) -> bytes:
    """CDR-serialize a message instance."""
    session = get_session()
    store_type = session._registered_types.get(type_name, type_name)
    return bytes(session.store.serialize_cdr(msg, store_type))


def deserialize(data: bytes, type_name: str) -> Any:
    """CDR-deserialize bytes into a message instance."""
    session = get_session()
    store_type = session._registered_types.get(type_name, type_name)
    return session.store.deserialize_cdr(data, store_type)

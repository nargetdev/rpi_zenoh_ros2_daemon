# SPDX-License-Identifier: Apache-2.0
"""Pure-Python tests for DictParameterBackend (no zenoh/ROS needed)."""
import pytest

from pico_ros_py.picoparams import (
    DictParameterBackend,
    IntegerRange,
    ParameterDescriptor,
    ParameterType,
    ParameterValue,
)


@pytest.fixture
def backend():
    b = DictParameterBackend()
    b.declare("example.param1", 10, integer_range=IntegerRange(-50, 50))
    b.declare("example.param2", 1.25)
    b.declare("example.param3", bytes([1, 2, 3]))
    b.declare("other.flag", True, read_only=True)
    return b


def test_ref_and_get(backend):
    assert backend.ref("example.param1") == "example.param1"
    assert backend.ref("nope") is None
    assert backend.get("example.param1").value == 10
    assert backend.type("example.param2") == ParameterType.DOUBLE


def test_list_all_and_prefixed(backend):
    names = backend.list(None)
    assert set(names) == {
        "example.param1",
        "example.param2",
        "example.param3",
        "other.flag",
    }
    assert set(backend.list("example")) == {
        "example.param1",
        "example.param2",
        "example.param3",
    }


def test_prefixes(backend):
    assert "example" in backend.prefixes(None)
    assert "other" in backend.prefixes(None)


def test_set_ok(backend):
    ok, reason = backend.set("example.param1", ParameterValue(ParameterType.INTEGER, 7))
    assert ok and reason == ""
    assert backend.value_of("example.param1") == 7


def test_set_wrong_type(backend):
    ok, reason = backend.set(
        "example.param1", ParameterValue(ParameterType.STRING, "x")
    )
    assert not ok
    assert "wrong type" in reason


def test_set_out_of_range(backend):
    ok, reason = backend.set(
        "example.param1", ParameterValue(ParameterType.INTEGER, 9999)
    )
    assert not ok
    assert "out of range" in reason


def test_set_read_only(backend):
    ok, reason = backend.set("other.flag", ParameterValue(ParameterType.BOOL, False))
    assert not ok
    assert "read-only" in reason


def test_on_set_callback():
    b = DictParameterBackend()
    b.declare("p", 1)
    seen = []
    b.on_set = lambda name, value: seen.append((name, value.value))
    b.set("p", ParameterValue(ParameterType.INTEGER, 42))
    assert seen == [("p", 42)]


def test_dynamic_typing_allows_type_change():
    b = DictParameterBackend()
    b.declare(
        "p",
        1,
        descriptor=ParameterDescriptor(type=ParameterType.INTEGER, dynamic_typing=True),
    )
    ok, _ = b.set("p", ParameterValue(ParameterType.STRING, "now a string"))
    assert ok
    assert b.value_of("p") == "now a string"

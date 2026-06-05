# SPDX-License-Identifier: Apache-2.0
"""Pure-Python tests for the parameter type model (no zenoh/ROS needed)."""
import pytest

from pico_ros_py.picoparams import ParameterType, ParameterValue


def test_parameter_type_wire_values():
    # These integer values are wire-significant (rcl_interfaces/msg/ParameterType
    # and Pico-ROS pp_ParameterType). They must not drift.
    assert ParameterType.NOT_SET == 0
    assert ParameterType.BOOL == 1
    assert ParameterType.INTEGER == 2
    assert ParameterType.DOUBLE == 3
    assert ParameterType.STRING == 4
    assert ParameterType.BYTE_ARRAY == 5
    assert ParameterType.BOOL_ARRAY == 6
    assert ParameterType.INTEGER_ARRAY == 7
    assert ParameterType.DOUBLE_ARRAY == 8
    assert ParameterType.STRING_ARRAY == 9


@pytest.mark.parametrize(
    "value, expected_type",
    [
        (True, ParameterType.BOOL),
        (3, ParameterType.INTEGER),
        (2.5, ParameterType.DOUBLE),
        ("hi", ParameterType.STRING),
        (b"\x01\x02", ParameterType.BYTE_ARRAY),
        ([True, False], ParameterType.BOOL_ARRAY),
        ([1, 2, 3], ParameterType.INTEGER_ARRAY),
        ([1.0, 2.0], ParameterType.DOUBLE_ARRAY),
        (["a", "b"], ParameterType.STRING_ARRAY),
        (None, ParameterType.NOT_SET),
    ],
)
def test_from_python_inference(value, expected_type):
    assert ParameterValue.from_python(value).type == expected_type


def test_bool_is_not_int():
    # bool must be detected before int (bool is a subclass of int in Python).
    assert ParameterValue.from_python(True).type == ParameterType.BOOL
    assert ParameterValue.from_python(1).type == ParameterType.INTEGER


def test_is_array():
    assert ParameterValue.from_python([1, 2]).is_array
    assert not ParameterValue.from_python(1).is_array


def test_unsupported_value_raises():
    with pytest.raises(TypeError):
        ParameterValue.from_python({"a": 1})

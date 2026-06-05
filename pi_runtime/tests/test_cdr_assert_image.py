"""Host-level unit tests for the hand-rolled FastCDR Image parser.

``ci/verifier/cdr_assert.py`` walks a ``sensor_msgs/msg/Image`` CDR buffer by hand
(``_align`` / ``_read_cdr_string`` / ``assert_image``). That offset arithmetic is the
correctness mechanism of the G5/G6 Image gates, yet it only ever ran inside the Docker
integration gate -- which is RED and times out *before* the parser is reached, so a latent
alignment/endianness bug would be invisible. These tests exercise the parser directly on
host: a self-consistent golden buffer must be accepted, and a table of mutated/truncated
buffers must each be rejected (a parser that only ever accepts is worthless as a gate).

``cdr_assert.py`` imports rclpy / sensor_msgs / std_msgs at module top (none installed on
the host), so those modules are stubbed in ``sys.modules`` before it is loaded by path.
"""
from __future__ import annotations

import importlib.util
import struct
import sys
import types
from pathlib import Path

import pytest


def _install_ros_stubs() -> None:
    """Register minimal stand-ins for the ROS modules cdr_assert imports."""
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda *a, **k: None
    rclpy.create_node = lambda *a, **k: None
    rclpy.try_shutdown = lambda *a, **k: None
    rclpy.spin_once = lambda *a, **k: None
    rclpy_node = types.ModuleType("rclpy.node")
    rclpy_node.Node = object
    rclpy_qos = types.ModuleType("rclpy.qos")
    rclpy_qos.QoSProfile = object
    rclpy_qos.ReliabilityPolicy = types.SimpleNamespace(RELIABLE=object())
    rclpy_qos.HistoryPolicy = types.SimpleNamespace(KEEP_LAST=object())
    sensor_msgs = types.ModuleType("sensor_msgs")
    sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")
    sensor_msgs_msg.Image = object
    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.Float32 = object
    std_msgs_msg.String = object
    sys.modules.update(
        {
            "rclpy": rclpy,
            "rclpy.node": rclpy_node,
            "rclpy.qos": rclpy_qos,
            "sensor_msgs": sensor_msgs,
            "sensor_msgs.msg": sensor_msgs_msg,
            "std_msgs": std_msgs,
            "std_msgs.msg": std_msgs_msg,
        }
    )


def _load_cdr_assert():
    _install_ros_stubs()
    path = Path(__file__).resolve().parents[2] / "ci" / "verifier" / "cdr_assert.py"
    spec = importlib.util.spec_from_file_location("cdr_assert", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cdr_assert = _load_cdr_assert()


# Small dims keep the golden buffer tiny; assert_image reads expected dims from
# module globals, so the parametrized fixtures patch them to match.
W, H = 4, 2
STEP = W * 3  # 12
DATA_LEN = STEP * H  # 24


def _build_image_cdr(
    *, frame_id: bytes = b"cam\x00", height: int = H, width: int = W,
    encoding: bytes = b"rgb8\x00", is_bigendian: int = 0, step: int = STEP,
    data_len: int = DATA_LEN, data: bytes | None = None,
) -> bytes:
    """Hand-build a CDR_LE sensor_msgs/Image buffer as an independent oracle.

    Padding is computed from the CDR alignment rule directly (modulo), not via the
    module's ``_align``, so the buffer does not encode the parser's own assumptions.
    """
    body = b""
    body += struct.pack("<i", 0)  # Header.stamp.sec  (int32)
    body += struct.pack("<I", 0)  # Header.stamp.nanosec (uint32)
    body += struct.pack("<I", len(frame_id)) + frame_id  # frame_id string
    body += struct.pack("<I", height)
    body += struct.pack("<I", width)
    body += struct.pack("<I", len(encoding)) + encoding  # encoding string
    body += struct.pack("<B", is_bigendian)
    body += b"\x00" * ((-len(body)) % 4)  # pad to 4-align `step`
    body += struct.pack("<I", step)
    body += b"\x00" * ((-len(body)) % 4)  # pad to 4-align the data length prefix
    body += struct.pack("<I", data_len)
    body += bytes(data_len) if data is None else data
    return cdr_assert.CDR_LE_HEADER + body


@pytest.fixture(autouse=True)
def _patch_expected_dims(monkeypatch):
    monkeypatch.setattr(cdr_assert, "IMAGE_W", W)
    monkeypatch.setattr(cdr_assert, "IMAGE_H", H)
    monkeypatch.setattr(cdr_assert, "IMAGE_STEP", STEP)
    monkeypatch.setattr(cdr_assert, "IMAGE_ENCODING", "rgb8")


# ---- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    "pos,size,expected",
    [(0, 4, 0), (1, 4, 4), (4, 4, 4), (5, 4, 8), (33, 4, 36), (1, 1, 1)],
)
def test_align(pos, size, expected):
    assert cdr_assert._align(pos, size) == expected


def test_read_cdr_string_strips_null_and_advances():
    body = struct.pack("<I", 4) + b"cam\x00"
    text, pos = cdr_assert._read_cdr_string(body, 0)
    assert text == "cam"
    assert pos == 8


# ---- assert_image: accept the good buffer ---------------------------------


def test_assert_image_accepts_a_well_formed_buffer():
    # Should walk the whole buffer without calling fail() (which sys.exit(1)s).
    cdr_assert.assert_image(_build_image_cdr())


# ---- assert_image: reject every malformation ------------------------------


def test_assert_image_rejects_bad_cdr_header():
    buf = bytearray(_build_image_cdr())
    buf[0:4] = b"\xde\xad\xbe\xef"
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(bytes(buf))


def test_assert_image_rejects_wrong_width():
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(_build_image_cdr(width=999))


def test_assert_image_rejects_wrong_encoding():
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(_build_image_cdr(encoding=b"bgr8\x00"))


def test_assert_image_rejects_step_height_mismatch():
    # data_len that disagrees with step*height must fail even if bytes are present.
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(_build_image_cdr(data_len=DATA_LEN + 4, data=bytes(DATA_LEN + 4)))


def test_assert_image_rejects_truncated_data_array():
    # Declares DATA_LEN bytes but the buffer is short -> the buffer-holds-data check fires.
    buf = _build_image_cdr()[:-4]
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(buf)


def test_assert_image_rejects_buffer_truncated_mid_header():
    with pytest.raises(SystemExit):
        cdr_assert.assert_image(_build_image_cdr()[:10])

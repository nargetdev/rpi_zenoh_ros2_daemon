#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Byte-level CDR wire-format assertions over rmw_zenoh (the verifier-only gate).

`ros2 topic echo` proves a message *decodes*; it does NOT prove the exact bytes
on the wire are what a native ROS 2 subscriber expects. This script does, using
an rclpy **raw** subscription (`raw=True`), which delivers the exact serialized
CDR buffer the real discovery/transport path produced -- no hand-computed Zenoh
keys, no SDK on the validator side. It is strictly stronger than `topic echo`.

Assertions, all gating CI by exit code (non-zero on any mismatch):

  1. std_msgs/msg/Float32 on the core-temp topic (real pi_runtime daemon):
       * buf[0:4] == 00 01 00 00   (PLAIN CDR, little-endian encapsulation header)
       * len(buf) == 8 and <f decode of buf[4:8] ~= TEMP_EXPECT (default 48.3)
  2. std_msgs/msg/String on /chatter (pico-ros-py talker):
       * buf[0:4] == 00 01 00 00
       * <I length prefix, null-terminated body, decodes to the talker greeting
  3. sensor_msgs/msg/Image on the native Image topic (run via `--image`):
       * buf[0:4] == 00 01 00 00, then a hand-walked FastCDR field decode
       * width/height/encoding/step match the expected mock dims and the data
         array holds step*height bytes

Env knobs (with defaults): CORE_TEMP_TOPIC, CHATTER_TOPIC, TEMP_EXPECT, TEMP_TOL,
CDR_TIMEOUT (per-topic seconds).
"""
from __future__ import annotations

import os
import struct
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Float32, String

CORE_TEMP_TOPIC = os.environ.get("CORE_TEMP_TOPIC", "/pgwaam/ci_dslr/online/core_temp")
CHATTER_TOPIC = os.environ.get("CHATTER_TOPIC", "/chatter")
TEMP_EXPECT = float(os.environ.get("TEMP_EXPECT", "48.3"))
TEMP_TOL = float(os.environ.get("TEMP_TOL", "0.2"))
CDR_TIMEOUT = float(os.environ.get("CDR_TIMEOUT", "60"))
CHATTER_EXPECT = os.environ.get("CHATTER_EXPECT", "hello from pico-ros-py")

# Native sensor_msgs/msg/Image gate (the 640x480 rgb8 synthesized mock frame).
IMAGE_TOPIC = os.environ.get("IMAGE_TOPIC", "/dslr/ci_cam/image_raw")
IMAGE_W = int(os.environ.get("IMAGE_W", "640"))
IMAGE_H = int(os.environ.get("IMAGE_H", "480"))
IMAGE_STEP = int(os.environ.get("IMAGE_STEP", "1920"))
IMAGE_ENCODING = os.environ.get("IMAGE_ENCODING", "rgb8")
# The Image is one-shot VOLATILE per capture, so allow a longer wait; the shell
# drives a background capture loop while this subscriber is alive.
IMAGE_TIMEOUT = float(os.environ.get("IMAGE_TIMEOUT", "90"))

# PLAIN CDR, little-endian: representation id 0x0001 (CDR_LE) + options 0x0000.
CDR_LE_HEADER = b"\x00\x01\x00\x00"


def log(msg: str) -> None:
    print(f"[cdr] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[cdr] FAIL: {msg}", file=sys.stderr, flush=True)
    print("::::: CDR ASSERT FAILED :::::", flush=True)
    rclpy.try_shutdown()
    sys.exit(1)


def _as_bytes(msg) -> bytes:
    """A raw callback may deliver raw `bytes`/`bytearray` OR a SerializedMessage
    with a `.buffer` attribute, depending on the rclpy version. Handle both."""
    if isinstance(msg, (bytes, bytearray)):
        return bytes(msg)
    buffer = getattr(msg, "buffer", None)
    if buffer is not None:
        return bytes(buffer)
    return bytes(msg)


def _reliable_qos() -> QoSProfile:
    # Match the publishers (reliable, depth>=5) so the periodic Float32 isn't
    # dropped by a default-volatile sub.
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )


def capture_raw(node: Node, topic: str, msg_type, timeout: float) -> bytes:
    """Spin until one raw CDR buffer arrives on `topic`, or fail on timeout."""
    box: dict[str, bytes] = {}

    def _cb(msg) -> None:
        if "buf" not in box:
            box["buf"] = _as_bytes(msg)

    sub = node.create_subscription(msg_type, topic, _cb, _reliable_qos(), raw=True)
    deadline = time.monotonic() + timeout
    try:
        while "buf" not in box and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.5)
    finally:
        node.destroy_subscription(sub)
    if "buf" not in box:
        fail(f"no message received on {topic} within {timeout:.0f}s")
    return box["buf"]


def assert_float32(buf: bytes) -> None:
    log(f"{CORE_TEMP_TOPIC} raw CDR ({len(buf)} bytes): {buf.hex(' ')}")
    if buf[0:4] != CDR_LE_HEADER:
        fail(f"{CORE_TEMP_TOPIC}: bad CDR header {buf[0:4].hex(' ')}, want 00 01 00 00")
    if len(buf) != 8:
        fail(f"{CORE_TEMP_TOPIC}: expected 8-byte Float32 CDR, got {len(buf)}")
    value = struct.unpack("<f", buf[4:8])[0]
    log(f"{CORE_TEMP_TOPIC}: decoded Float32 = {value:.4f} (expect ~{TEMP_EXPECT} +/- {TEMP_TOL})")
    if abs(value - TEMP_EXPECT) > TEMP_TOL:
        fail(f"{CORE_TEMP_TOPIC}: Float32 {value} not within {TEMP_TOL} of {TEMP_EXPECT}")
    log("Float32 byte-level CDR assertion PASSED")


def assert_string(buf: bytes) -> None:
    log(f"{CHATTER_TOPIC} raw CDR ({len(buf)} bytes): {buf.hex(' ')}")
    if buf[0:4] != CDR_LE_HEADER:
        fail(f"{CHATTER_TOPIC}: bad CDR header {buf[0:4].hex(' ')}, want 00 01 00 00")
    if len(buf) < 8:
        fail(f"{CHATTER_TOPIC}: buffer too short for a CDR string: {len(buf)} bytes")
    length = struct.unpack("<I", buf[4:8])[0]
    body = buf[8 : 8 + length]
    if len(body) != length:
        fail(f"{CHATTER_TOPIC}: declared length {length} but only {len(body)} bytes present")
    if length == 0 or body[-1] != 0:
        fail(f"{CHATTER_TOPIC}: CDR string not null-terminated (last byte {body[-1:].hex()})")
    text = body[:-1].decode("utf-8")
    log(f"{CHATTER_TOPIC}: decoded String (len prefix {length}) = {text!r}")
    if not text.startswith(CHATTER_EXPECT):
        fail(f"{CHATTER_TOPIC}: String {text!r} does not start with {CHATTER_EXPECT!r}")
    log("String byte-level CDR assertion PASSED")


def _align(pos: int, size: int) -> int:
    """CDR aligns each primitive to its own size, measured from the start of the
    body (the bytes after the 4-byte encapsulation header)."""
    rem = pos % size
    return pos + ((size - rem) % size)


def _read_cdr_string(body: bytes, pos: int) -> tuple[str, int]:
    """Read a 4-byte-length-prefixed, null-terminated CDR string (length-aligned
    to 4). Returns the decoded text (null stripped) and the new offset."""
    pos = _align(pos, 4)
    length = struct.unpack_from("<I", body, pos)[0]
    pos += 4
    raw = body[pos : pos + length]
    if len(raw) != length:
        fail(f"{IMAGE_TOPIC}: CDR string declared {length} bytes but only {len(raw)} present")
    pos += length
    # Strip the trailing null terminator if present.
    text = raw[:-1].decode("utf-8") if length and raw[-1:] == b"\x00" else raw.decode("utf-8")
    return text, pos


def assert_image(buf: bytes) -> None:
    """Byte-level CDR assertion for sensor_msgs/msg/Image.

    Field order (after the 4-byte CDR_LE encapsulation header):
      Header header  -> builtin_interfaces/Time stamp (int32 sec, uint32 nanosec)
                        + string frame_id
      uint32 height
      uint32 width
      string encoding
      uint8  is_bigendian
      uint32 step
      uint8[] data    (uint32 length prefix + raw bytes)

    Asserts width/height/encoding/step match the expected mock dims and that the
    data array length equals step*height -- proving a real rclpy/rmw_zenoh client
    decodes exactly what the producing publisher serialized.
    """
    log(f"{IMAGE_TOPIC} raw CDR ({len(buf)} bytes): first 64 = {buf[:64].hex(' ')}")
    if buf[0:4] != CDR_LE_HEADER:
        fail(f"{IMAGE_TOPIC}: bad CDR header {buf[0:4].hex(' ')}, want 00 01 00 00")
    body = buf[4:]
    try:
        pos = 0
        # Header.stamp: int32 sec, uint32 nanosec (both 4-byte aligned already).
        pos = _align(pos, 4) + 4  # sec
        pos = _align(pos, 4) + 4  # nanosec
        # Header.frame_id string.
        frame_id, pos = _read_cdr_string(body, pos)
        # height, width (uint32 each, 4-byte aligned).
        pos = _align(pos, 4)
        height = struct.unpack_from("<I", body, pos)[0]
        pos += 4
        pos = _align(pos, 4)
        width = struct.unpack_from("<I", body, pos)[0]
        pos += 4
        # encoding string.
        encoding, pos = _read_cdr_string(body, pos)
        # is_bigendian uint8 (1-byte aligned). Read via unpack_from so a buffer
        # truncated at this offset surfaces as struct.error, not a bare IndexError.
        is_bigendian = struct.unpack_from("<B", body, pos)[0]
        pos += 1
        # step uint32 (4-byte aligned -- skips padding after is_bigendian).
        pos = _align(pos, 4)
        step = struct.unpack_from("<I", body, pos)[0]
        pos += 4
        # data uint8[]: uint32 length prefix (4-byte aligned) + raw bytes.
        pos = _align(pos, 4)
        data_len = struct.unpack_from("<I", body, pos)[0]
        pos += 4
    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        # Any malformation (truncation, misalignment, non-UTF-8 string field)
        # routes through fail() for a clean, greppable diagnosis rather than a
        # raw traceback -- the gate must fail loudly and legibly.
        fail(f"{IMAGE_TOPIC}: malformed Image CDR buffer: {exc}")
    # The declared data array length is only meaningful if the buffer physically
    # holds that many payload bytes; a truncated/fragmented frame that merely
    # *claims* step*height bytes must not pass a "byte-level" gate.
    if len(body) - pos < data_len:
        fail(
            f"{IMAGE_TOPIC}: data array declares {data_len} bytes but only "
            f"{len(body) - pos} remain in the buffer (truncated frame)"
        )
    log(
        f"{IMAGE_TOPIC}: decoded Image frame_id={frame_id!r} {width}x{height} "
        f"encoding={encoding!r} is_bigendian={is_bigendian} step={step} data_len={data_len}"
    )
    if width != IMAGE_W:
        fail(f"{IMAGE_TOPIC}: width {width} != expected {IMAGE_W}")
    if height != IMAGE_H:
        fail(f"{IMAGE_TOPIC}: height {height} != expected {IMAGE_H}")
    if encoding != IMAGE_ENCODING:
        fail(f"{IMAGE_TOPIC}: encoding {encoding!r} != expected {IMAGE_ENCODING!r}")
    if step != IMAGE_STEP:
        fail(f"{IMAGE_TOPIC}: step {step} != expected {IMAGE_STEP}")
    if data_len != step * height:
        fail(f"{IMAGE_TOPIC}: data length {data_len} != step*height ({step * height})")
    log("Image byte-level CDR assertion PASSED")


def main() -> None:
    # `--image` runs ONLY the Image gate (G5): the shell drives a background
    # capture loop while we subscribe, since the Image is one-shot VOLATILE. The
    # default (no flag) runs the String + Float32 gates (G2).
    image_only = "--image" in sys.argv[1:]
    rclpy.init()
    node = rclpy.create_node("cdr_assert")
    try:
        if image_only:
            log(f"RMW={os.environ.get('RMW_IMPLEMENTATION', '?')}  image timeout={IMAGE_TIMEOUT:.0f}s")
            assert_image(capture_raw(node, IMAGE_TOPIC, Image, IMAGE_TIMEOUT))
        else:
            log(f"RMW={os.environ.get('RMW_IMPLEMENTATION', '?')}  timeout={CDR_TIMEOUT:.0f}s/topic")
            assert_float32(capture_raw(node, CORE_TEMP_TOPIC, Float32, CDR_TIMEOUT))
            assert_string(capture_raw(node, CHATTER_TOPIC, String, CDR_TIMEOUT))
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    print("::::: ALL CDR ASSERTIONS PASSED :::::", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Byte-level CDR wire-format assertions over rmw_zenoh (the verifier-only gate).

`ros2 topic echo` proves a message *decodes*; it does NOT prove the exact bytes
on the wire are what a native ROS 2 subscriber expects. This script does, using
an rclpy **raw** subscription (`raw=True`), which delivers the exact serialized
CDR buffer the real discovery/transport path produced -- no hand-computed Zenoh
keys, no SDK on the validator side. It is strictly stronger than `topic echo`.

Two assertions, both gating CI by exit code (non-zero on any mismatch):

  1. std_msgs/msg/Float32 on the core-temp topic (real pi_runtime daemon):
       * buf[0:4] == 00 01 00 00   (PLAIN CDR, little-endian encapsulation header)
       * len(buf) == 8 and <f decode of buf[4:8] ~= TEMP_EXPECT (default 48.3)
  2. std_msgs/msg/String on /chatter (pico-ros-py talker):
       * buf[0:4] == 00 01 00 00
       * <I length prefix, null-terminated body, decodes to the talker greeting

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
from std_msgs.msg import Float32, String

CORE_TEMP_TOPIC = os.environ.get("CORE_TEMP_TOPIC", "/pgwaam/ci_dslr/online/core_temp")
CHATTER_TOPIC = os.environ.get("CHATTER_TOPIC", "/chatter")
TEMP_EXPECT = float(os.environ.get("TEMP_EXPECT", "48.3"))
TEMP_TOL = float(os.environ.get("TEMP_TOL", "0.2"))
CDR_TIMEOUT = float(os.environ.get("CDR_TIMEOUT", "60"))
CHATTER_EXPECT = os.environ.get("CHATTER_EXPECT", "hello from pico-ros-py")

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


def main() -> None:
    rclpy.init()
    node = rclpy.create_node("cdr_assert")
    try:
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

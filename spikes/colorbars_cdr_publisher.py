#!/usr/bin/env python3
"""
SPIKE: colorbars_cdr_publisher.py

Goal: validate that zenoh_ros2_sdk's ROS2Publisher can emit a correctly
CDR-encoded sensor_msgs/msg/Image that a REAL rmw_zenoh ROS 2 subscriber
discovers and reads back.

A tiny synthetic colorbars frame (200x100, rgb8) is the probe. If the
type-hash / CDR / keyexpr are all correct, a `ros2 topic echo /spike/colorbars`
on a machine sharing the same Zenoh router will print an Image with
height=100, width=200, encoding=rgb8 and non-empty data.

Run with the daemon venv python:
    pi_runtime/.venv/bin/python spikes/colorbars_cdr_publisher.py \
        --router-ip 172.31.1.252 --router-port 7447 --domain-id 0 \
        --rate 2 --duration 30

No external image files; colorbars generated in pure Python.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from zenoh_ros2_sdk import ROS2Publisher, get_message_class


# Classic 8 vertical color bars, RGB triplets (white..black).
COLORBARS = [
    (255, 255, 255),  # white
    (255, 255, 0),    # yellow
    (0, 255, 255),    # cyan
    (0, 255, 0),      # green
    (255, 0, 255),    # magenta
    (255, 0, 0),      # red
    (0, 0, 255),      # blue
    (0, 0, 0),        # black
]


def make_colorbars(width: int, height: int) -> "np.ndarray":
    """Generate raw rgb8 bytes for vertical color bars (row-major, width*3 step).

    Returns a flat numpy uint8 array (length width*height*3). rosbags requires
    a numpy array for ``uint8[]`` dynamic-array fields (it calls ``.view()`` on
    the value during CDR serialization), so a plain ``bytes`` won't work.
    """
    nbars = len(COLORBARS)
    row = np.empty((width, 3), dtype=np.uint8)
    for x in range(width):
        row[x] = COLORBARS[(x * nbars) // width]
    frame = np.broadcast_to(row, (height, width, 3))
    return np.ascontiguousarray(frame).reshape(-1)


def build_publisher(router_ip: str, router_port: int, domain_id: int) -> ROS2Publisher:
    return ROS2Publisher(
        topic="/spike/colorbars",
        msg_type="sensor_msgs/msg/Image",
        domain_id=domain_id,
        router_ip=router_ip,
        router_port=router_port,
    )


def build_image_fields(width: int, height: int, data: bytes):
    """Construct sensor_msgs/msg/Image fields including nested Header/Time.

    We obtain the rosbags-generated dataclasses for Header and Time from the
    SDK's registry so the nested structures CDR-serialize correctly.
    """
    header_cls = get_message_class("std_msgs/msg/Header")
    time_cls = get_message_class("builtin_interfaces/msg/Time")

    now = time.time()
    stamp = time_cls(sec=int(now), nanosec=int((now % 1) * 1e9))
    header = header_cls(stamp=stamp, frame_id="spike")

    return dict(
        header=header,
        height=height,
        width=width,
        encoding="rgb8",
        is_bigendian=0,
        step=width * 3,
        data=data,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish synthetic colorbars Image via zenoh_ros2_sdk")
    ap.add_argument("--router-ip", default="172.31.1.252")
    ap.add_argument("--router-port", type=int, default=7447)
    ap.add_argument("--domain-id", type=int, default=0)
    ap.add_argument("--width", type=int, default=200)
    ap.add_argument("--height", type=int, default=100)
    ap.add_argument("--rate", type=float, default=2.0, help="publish rate Hz")
    ap.add_argument("--duration", type=float, default=30.0, help="seconds to run (<=0 = forever)")
    args = ap.parse_args(argv)

    data = make_colorbars(args.width, args.height)
    assert len(data) == args.width * args.height * 3

    print(f"[spike] colorbars: {args.width}x{args.height} rgb8, {len(data)} bytes")
    print(f"[spike] connecting publisher to tcp/{args.router_ip}:{args.router_port} domain={args.domain_id}")

    pub = build_publisher(args.router_ip, args.router_port, args.domain_id)
    print(f"[spike] keyexpr      = {pub.keyexpr}")
    print(f"[spike] dds_type     = {pub.dds_type_name}")
    print(f"[spike] type_hash    = {pub.type_hash}")

    # sanity: show first few pixels so we can compare against echo'd data
    print(f"[spike] first 24 data bytes = {list(int(b) for b in data[:24])}")

    period = 1.0 / args.rate if args.rate > 0 else 0.5
    deadline = None if args.duration <= 0 else time.time() + args.duration
    n = 0
    try:
        while deadline is None or time.time() < deadline:
            fields = build_image_fields(args.width, args.height, data)
            pub.publish(**fields)
            n += 1
            if n % 5 == 1:
                print(f"[spike] published frame #{n} (seq~{pub.sequence_number})")
            time.sleep(period)
    except KeyboardInterrupt:
        print("[spike] interrupted")
    finally:
        print(f"[spike] total frames published: {n}")
        pub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

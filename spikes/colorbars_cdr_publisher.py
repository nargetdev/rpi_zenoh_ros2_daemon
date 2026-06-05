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
from PIL import Image as PilImage, ImageDraw, ImageFont

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


_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
)


def _load_font(size: int):
    """Best-effort TrueType font load with bitmap fallback.

    ``ImageFont.load_default(size=...)`` is Pillow 10.1+; the project's floor
    is Pillow >= 9.0, so for any non-tiny text we must go through
    ``ImageFont.truetype``. Falls back to the sizeless bitmap default if every
    TrueType candidate fails — the overlay will be unreadable but the spike
    keeps running.
    """
    for path in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            print(f"[spike] font: {path} @ {size}px")
            return font
        except (OSError, IOError):
            continue
    print("[spike] font: TrueType unavailable, using ImageFont.load_default() bitmap fallback")
    return ImageFont.load_default()


def _epoch_lines(t_ns: int) -> list[str]:
    """Decompose an integer nanoseconds-since-epoch into 7 human-readable lines.

    Pure integer math — never feeds ``t_ns`` through float, which would lose
    ~microsecond precision in the mantissa. Returns days/hours/min/sec/ms/us/ns
    rows, each label-padded and value right-aligned for column alignment.
    """
    ns = int(t_ns)
    days = ns // 86_400_000_000_000
    hours = ns // 3_600_000_000_000
    minutes = ns // 60_000_000_000
    seconds = ns // 1_000_000_000
    millis = ns // 1_000_000
    micros = ns // 1_000
    return [
        f"DAYS  : {days:>20}",
        f"HOURS : {hours:>20}",
        f"MIN   : {minutes:>20}",
        f"SEC   : {seconds:>20}",
        f"ms    : {millis:>20}",
        f"us    : {micros:>20}",
        f"ns    : {ns:>20}",
    ]


def _render_frame(width: int, height: int, t_ns: int, font, overlay: bool) -> "np.ndarray":
    """Render one colorbars frame and (optionally) overlay the epoch-time block.

    Returns a flat contiguous ``np.uint8`` array of length ``width*height*3``,
    matching the rosbags CDR ``uint8[]`` requirement (it calls ``.view()`` on
    the data field during serialization). Allocates a fresh PIL image each
    call — at 2 Hz the cost is irrelevant and avoids mutate-shared-buffer
    surprises.
    """
    flat = make_colorbars(width, height)
    frame = flat.reshape(height, width, 3)
    img = PilImage.fromarray(frame, mode="RGB")

    if overlay:
        lines = _epoch_lines(t_ns)
        text = "\n".join(lines)
        draw = ImageDraw.Draw(img)
        try:
            left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, stroke_width=2)
            tw = right - left
            th = bottom - top
        except AttributeError:
            tw = max(len(line) for line in lines) * 6
            th = len(lines) * 12

        pad = 8
        x0, y0 = 8, 8
        x1 = min(width, x0 + tw + 2 * pad)
        y1 = min(height, y0 + th + 2 * pad)
        draw.rectangle([(x0, y0), (x1, y1)], fill=(0, 0, 0))
        draw.multiline_text(
            (x0 + pad, y0 + pad),
            text,
            font=font,
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(arr).reshape(-1)


def build_publisher(router_ip: str, router_port: int, domain_id: int) -> ROS2Publisher:
    return ROS2Publisher(
        topic="/spike/colorbars",
        msg_type="sensor_msgs/msg/Image",
        domain_id=domain_id,
        router_ip=router_ip,
        router_port=router_port,
    )


def build_image_fields(width: int, height: int, data: "np.ndarray", t_ns: int):
    """Construct sensor_msgs/msg/Image fields including nested Header/Time.

    We obtain the rosbags-generated dataclasses for Header and Time from the
    SDK's registry so the nested structures CDR-serialize correctly. The
    caller passes ``t_ns`` (integer nanoseconds-since-epoch) so the on-screen
    overlay and the ``Header.stamp`` are derived from the *same* instant.
    """
    header_cls = get_message_class("std_msgs/msg/Header")
    time_cls = get_message_class("builtin_interfaces/msg/Time")

    sec, nsec = divmod(int(t_ns), 1_000_000_000)
    stamp = time_cls(sec=int(sec), nanosec=int(nsec))
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
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--rate", type=float, default=2.0, help="publish rate Hz")
    ap.add_argument("--duration", type=float, default=30.0, help="seconds to run (<=0 = forever)")
    ap.add_argument("--no-overlay", action="store_true", help="disable epoch-time overlay (byte-perfect bars)")
    ap.add_argument("--font-size", type=int, default=28, help="overlay font size in px (auto-shrinks if frame is small)")
    args = ap.parse_args(argv)

    overlay = not args.no_overlay
    # Clamp font size so a small custom override (e.g. --width 200 --height 100)
    # still produces something that fits within the frame.
    font_size = min(args.font_size, max(10, args.height // 12))
    font = _load_font(font_size) if overlay else None

    print(f"[spike] colorbars: {args.width}x{args.height} rgb8, {args.width * args.height * 3} bytes")
    print(f"[spike] overlay={'on' if overlay else 'off'} font_size={font_size}")
    print(f"[spike] connecting publisher to tcp/{args.router_ip}:{args.router_port} domain={args.domain_id}")

    pub = build_publisher(args.router_ip, args.router_port, args.domain_id)
    print(f"[spike] keyexpr      = {pub.keyexpr}")
    print(f"[spike] dds_type     = {pub.dds_type_name}")
    print(f"[spike] type_hash    = {pub.type_hash}")

    period = 1.0 / args.rate if args.rate > 0 else 0.5
    deadline = None if args.duration <= 0 else time.time() + args.duration
    n = 0
    try:
        while deadline is None or time.time() < deadline:
            t_ns = time.time_ns()
            data = _render_frame(args.width, args.height, t_ns, font, overlay)
            assert data.size == args.width * args.height * 3
            if n == 0:
                # Sanity: sample a clean middle row so the overlay panel
                # doesn't mask the printed pixel.
                mid = args.height // 2
                row_start = mid * args.width * 3
                sample = list(int(b) for b in data[row_start:row_start + 24])
                print(f"[spike] mid-row first 24 bytes = {sample}")
            fields = build_image_fields(args.width, args.height, data, t_ns)
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

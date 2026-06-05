#!/usr/bin/env python3
"""End-to-end example/validation for the native Ros2ImagePublisher.

Feeds a SYNTHETIC JPEG colorbars frame (PIL-encoded RGB -> JPEG) THROUGH the
production ``Ros2ImagePublisher`` (the same class wired into ``pi_runtime``),
pointed at a live rmw_zenoh router. This exercises the exact production path:
JPEG bytes -> PIL decode -> downsample -> native ``sensor_msgs/msg/Image`` (rgb8)
-> ``zenoh_ros2_sdk.ROS2Publisher`` -> router.

Verify the round-trip in another pane with::

    spikes/colorbars_verify_sub.py 172.31.1.252:7447 0   # subscribes 0/dslr/<cam>/image_raw/**

(the verifier's KEY is /spike/colorbars by default — point it at the topic below,
or set --topic to match). The verifier CDR-decodes the Image and prints dims.

Run with the daemon venv python::

    pi_runtime/.venv/bin/python spikes/dslr_image_publish_example.py \\
        --router-ip 172.31.1.252 --router-port 7447 --domain-id 0 \\
        --camera-id Canon_EOS_6D --rate 2 --duration 20

Be honest: if the router is unreachable the publisher swallows the failure
(by design) and you simply won't see frames on the subscriber.
"""
from __future__ import annotations

import argparse
import io
import sys

# Allow running straight from the repo without installing the package.
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi_runtime"))

import time

import numpy as np
from PIL import Image as PilImage

from zenoh_dslr_pi_runtime.models import Ros2PublishConfig
from zenoh_dslr_pi_runtime.ros2_image_publisher import Ros2ImagePublisher


# Classic 8 vertical color bars (white..black), RGB triplets.
COLORBARS = [
    (255, 255, 255),
    (255, 255, 0),
    (0, 255, 255),
    (0, 255, 0),
    (255, 0, 255),
    (255, 0, 0),
    (0, 0, 255),
    (0, 0, 0),
]


def make_colorbars_jpeg(width: int, height: int, quality: int = 95) -> bytes:
    """Build an RGB colorbars image and JPEG-encode it (a synthetic DSLR frame)."""
    nbars = len(COLORBARS)
    row = np.empty((width, 3), dtype=np.uint8)
    for x in range(width):
        row[x] = COLORBARS[(x * nbars) // width]
    frame = np.ascontiguousarray(np.broadcast_to(row, (height, width, 3)))
    buf = io.BytesIO()
    PilImage.fromarray(frame, mode="RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--router-ip", default="172.31.1.252")
    ap.add_argument("--router-port", type=int, default=7447)
    ap.add_argument("--domain-id", type=int, default=0)
    ap.add_argument("--camera-id", default="Canon_EOS_6D")
    ap.add_argument("--topic", default=None, help="default /dslr/<camera_id>/image_raw")
    ap.add_argument("--src-width", type=int, default=1600)
    ap.add_argument("--src-height", type=int, default=1200)
    ap.add_argument("--max-width", type=int, default=640)
    ap.add_argument("--max-height", type=int, default=480)
    ap.add_argument("--rate", type=float, default=2.0)
    ap.add_argument("--duration", type=float, default=20.0, help="<=0 = forever")
    args = ap.parse_args(argv)

    topic = args.topic or f"/dslr/{args.camera_id}/image_raw"
    jpeg = make_colorbars_jpeg(args.src_width, args.src_height)

    config = Ros2PublishConfig(
        enabled=True,
        topic=topic,
        encoding="rgb8",
        max_width=args.max_width,
        max_height=args.max_height,
        domain_id=args.domain_id,
        router_ip=args.router_ip,
        router_port=args.router_port,
    )

    # Show the expected downsampled dims so the operator can compare with the verifier.
    with PilImage.open(io.BytesIO(jpeg)) as decoded:
        scale = min(args.max_width / decoded.width, args.max_height / decoded.height, 1.0)
        exp_w, exp_h = max(1, int(decoded.width * scale)), max(1, int(decoded.height * scale))

    print(f"[example] synthetic JPEG src={args.src_width}x{args.src_height} ({len(jpeg)} bytes)")
    print(f"[example] topic={topic} domain={args.domain_id} router=tcp/{args.router_ip}:{args.router_port}")
    print(f"[example] expect downsampled rgb8 Image ~ {exp_w}x{exp_h} (step={exp_w * 3})")

    publisher = Ros2ImagePublisher(config, frame_id=args.camera_id)

    period = 1.0 / args.rate if args.rate > 0 else 0.5
    deadline = None if args.duration <= 0 else time.time() + args.duration
    n = 0
    ok = 0
    try:
        while deadline is None or time.time() < deadline:
            if publisher.publish(jpeg, "image/jpeg", frame_id=args.camera_id):
                ok += 1
            n += 1
            if n % 5 == 1:
                print(f"[example] attempted {n} published_ok={ok}", flush=True)
            time.sleep(period)
    except KeyboardInterrupt:
        print("[example] interrupted")
    finally:
        print(f"[example] total attempted={n} published_ok={ok}")
        publisher.close()

    if ok == 0:
        print("[example] WARNING: 0 frames published (router unreachable or decode failed)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

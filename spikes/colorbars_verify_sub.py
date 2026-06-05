#!/usr/bin/env python3
"""Validate the colorbars round-trip through the REAL Zenoh router.

Connects to the live router as a plain Zenoh client (NOT via the SDK),
subscribes to the rmw_zenoh keyexpr for /spike/colorbars, CDR-decodes each
sample into a sensor_msgs/Image, and confirms dims + first pixel. If frames
print here, the pi's ROS2-over-Zenoh publication is live and correctly
encoded on the shared router 172.31.1.252:7447.

usage: colorbars_verify_sub.py [router_ip:port] [domain_id]
"""
import sys
import time
import zenoh
from rosbags.typesys import Stores, get_typestore

ROUTER = sys.argv[1] if len(sys.argv) > 1 else "172.31.1.252:7447"
DOMAIN = sys.argv[2] if len(sys.argv) > 2 else "0"
ip, port = ROUTER.split(":")
KEY = f"{DOMAIN}/spike/colorbars/**"
ts = get_typestore(Stores.ROS2_JAZZY)


def payload_bytes(sample):
    p = sample.payload
    try:
        return p.to_bytes()
    except Exception:
        return bytes(p)


count = 0


def on_sample(sample):
    global count
    data = payload_bytes(sample)
    try:
        msg = ts.deserialize_cdr(data, "sensor_msgs/msg/Image")
    except Exception as e:
        print(f"[verify] decode error: {e} (payload {len(data)}B)", flush=True)
        return
    count += 1
    first_px = list(bytes(msg.data[:3]))
    ok = (
        msg.encoding == "rgb8"
        and msg.width
        and msg.height
        and len(msg.data) == msg.height * msg.step
    )
    tag = "GREEN" if ok else "??"
    print(
        f"[verify] #{count} {msg.width}x{msg.height} {msg.encoding} "
        f"step={msg.step} bytes={len(msg.data)} first_px={first_px} "
        f"frame_id={msg.header.frame_id} [{tag}]",
        flush=True,
    )


conf = zenoh.Config()
conf.insert_json5("mode", '"client"')
conf.insert_json5("connect/endpoints", f'["tcp/{ip}:{port}"]')
conf.insert_json5("scouting/multicast/enabled", "false")

print(f"[verify] connect tcp/{ip}:{port}  subscribe {KEY}", flush=True)
session = zenoh.open(conf)
sub = session.declare_subscriber(KEY, on_sample)
print("[verify] waiting for colorbars frames (Ctrl-C to stop)...", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass

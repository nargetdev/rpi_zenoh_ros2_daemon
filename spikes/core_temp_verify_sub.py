#!/usr/bin/env python3
"""Validate the core-temperature round-trip through the REAL Zenoh router.

Connects to the live router as a plain Zenoh client (NOT via the SDK),
subscribes to the rmw_zenoh keyexpr for the core-temp topic, CDR-decodes each
sample into a std_msgs/Float32, and prints the temperature. If samples print
here, the Pi's ROS2-over-Zenoh core-temp publication is live and correctly
CDR-encoded on the shared router -- i.e. `ros2 topic echo` would see it too.

usage: core_temp_verify_sub.py [router_ip:port] [topic] [domain_id] [max_samples]
  topic defaults to /pgwaam/id2_rpi4/online/core_temp
  exits 0 after the first decoded sample (or after max_samples), 1 on timeout.
"""
import sys
import time
import zenoh
from rosbags.typesys import Stores, get_typestore

ROUTER = sys.argv[1] if len(sys.argv) > 1 else "172.31.1.252:7447"
TOPIC = sys.argv[2] if len(sys.argv) > 2 else "/pgwaam/id2_rpi4/online/core_temp"
DOMAIN = sys.argv[3] if len(sys.argv) > 3 else "0"
MAX_SAMPLES = int(sys.argv[4]) if len(sys.argv) > 4 else 1
TIMEOUT_S = 20.0

ip, port = ROUTER.split(":")
# rmw_zenoh data-plane keyexpr: <domain>/<topic-no-leading-slash>/<type>/<hash>
KEY = f"{DOMAIN}/{TOPIC.lstrip('/')}/**"
ts = get_typestore(Stores.ROS2_JAZZY)

count = 0


def payload_bytes(sample):
    p = sample.payload
    try:
        return p.to_bytes()
    except Exception:
        return bytes(p)


def on_sample(sample):
    global count
    data = payload_bytes(sample)
    try:
        msg = ts.deserialize_cdr(data, "std_msgs/msg/Float32")
    except Exception as e:
        print(f"[verify] decode error: {e} (payload {len(data)}B)", flush=True)
        return
    count += 1
    print(f"[verify] #{count} {TOPIC} -> core_temp = {msg.data} C  [GREEN]", flush=True)


conf = zenoh.Config()
conf.insert_json5("mode", '"client"')
conf.insert_json5("connect/endpoints", f'["tcp/{ip}:{port}"]')
conf.insert_json5("scouting/multicast/enabled", "false")

print(f"[verify] connect tcp/{ip}:{port}  subscribe {KEY}", flush=True)
session = zenoh.open(conf)
sub = session.declare_subscriber(KEY, on_sample)
print(f"[verify] waiting up to {TIMEOUT_S:.0f}s for {MAX_SAMPLES} core-temp sample(s)...", flush=True)

deadline = time.monotonic() + TIMEOUT_S
try:
    while count < MAX_SAMPLES and time.monotonic() < deadline:
        time.sleep(0.1)
finally:
    session.close()

if count >= MAX_SAMPLES:
    print(f"[verify] OK: received {count} CDR Float32 sample(s)", flush=True)
    sys.exit(0)
print(f"[verify] TIMEOUT: no samples decoded on {KEY}", flush=True)
sys.exit(1)

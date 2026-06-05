#!/usr/bin/env python3
"""Fleet liveness pane: subscribe to the shop MQTT broker and print every
pi's heartbeat as it arrives — 'all dem tits talking' at a glance.

usage: fleet_heartbeat_mon.py [broker_host]
"""
import json
import sys

import paho.mqtt.client as mqtt

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.31.1.252"

try:  # paho 2.x
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except Exception:  # paho 1.x
    client = mqtt.Client()


def on_connect(c, *_):
    c.subscribe("pgwaam/heartbeat/#")
    print(f"[fleet] connected {HOST}:1883, subscribed pgwaam/heartbeat/#", flush=True)


def on_message(c, u, m):
    try:
        d = json.loads(m.payload)
        name = m.topic.split("/")[-1]
        print(
            f"[fleet] {name:10} seq={d.get('seq'):<5} host={d.get('host'):10} "
            f"cam={d.get('camera_model')} {d.get('status')}",
            flush=True,
        )
    except Exception:
        print(f"[fleet] {m.topic} {m.payload[:80]!r}", flush=True)


client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, 1883, 60)
client.loop_forever()

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Env-driven pico-ros-py talker (a "pi daemon" pub role in CI).

Brings up a single ROS 2 node (visible in `ros2 node list` via its Zenoh
liveliness token -- the node "heartbeat") and publishes a std_msgs/String on a
topic (visible to `ros2 topic echo`). No ROS 2 install: pure zenoh_ros2_sdk.

Env:
  ROUTER_IP   zenoh router host      (default 127.0.0.1)
  ROUTER_PORT zenoh router port      (default 7447)
  NODE_NAME   ROS 2 node name        (default pico_talker)
  TOPIC       topic to publish on    (default /chatter)
  RATE_HZ     publish rate in Hz      (default 2)
"""
import os
import time

from pico_ros_py import Node


def main() -> None:
    router_ip = os.environ.get("ROUTER_IP", "127.0.0.1")
    router_port = int(os.environ.get("ROUTER_PORT", "7447"))
    node_name = os.environ.get("NODE_NAME", "pico_talker")
    topic = os.environ.get("TOPIC", "/chatter")
    rate_hz = float(os.environ.get("RATE_HZ", "2"))
    period = 1.0 / rate_hz if rate_hz > 0 else 0.5

    node = Node(node_name, router_ip=router_ip, router_port=router_port)
    pub = node.create_publisher(topic, "std_msgs/msg/String")
    print(
        f"[talker] node={node.fully_qualified_name} topic={topic} "
        f"router={router_ip}:{router_port} rate={rate_hz}Hz",
        flush=True,
    )
    i = 0
    try:
        while True:
            pub.publish(data=f"hello from pico-ros-py: {i}")
            if i % 10 == 0:
                print(f"[talker] published #{i}", flush=True)
            i += 1
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Subscriber example (mirrors Pico-ROS examples/listener.c).

    python examples/listener.py -m client -a tcp/127.0.0.1:7447
    # then, from a ROS 2 + rmw_zenoh shell:
    ros2 topic pub /chatter std_msgs/msg/String '{data: hi}'
"""
from pico_ros_py import Interface, Node, spin


def main() -> None:
    iface = Interface.from_args()
    print(f"Starting pico-ros-py listener: {iface.mode} {iface.locator}")
    node = Node("pico_listener", iface)

    def on_msg(msg) -> None:
        print(f"Heard: {msg.data}")

    node.create_subscription("/chatter", "std_msgs/msg/String", on_msg)
    spin(node)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Publisher example (mirrors Pico-ROS examples/talker.c).

    python examples/talker.py -m client -a tcp/127.0.0.1:7447
    # then, from a ROS 2 + rmw_zenoh shell:
    ros2 topic echo /chatter
"""
import time

from pico_ros_py import Interface, Node


def main() -> None:
    iface = Interface.from_args()
    print(f"Starting pico-ros-py talker: {iface.mode} {iface.locator}")
    node = Node("pico_talker", iface)
    pub = node.create_publisher("/chatter", "std_msgs/msg/String")
    try:
        i = 0
        while True:
            msg = f"Hello from pico-ros-py: {i}"
            pub.publish(data=msg)
            print(f"Publishing: {msg}")
            i += 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()


if __name__ == "__main__":
    main()

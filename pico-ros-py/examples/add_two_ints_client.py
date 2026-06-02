#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Service client example (mirrors Pico-ROS examples/srv_client_add2ints.c).

    python examples/add_two_ints_client.py -m client -a tcp/127.0.0.1:7447
"""
from pico_ros_py import Interface, Node


def main() -> None:
    iface = Interface.from_args()
    node = Node("pico_add_two_ints_client", iface)
    client = node.create_client("/add_two_ints", "example_interfaces/srv/AddTwoInts")
    try:
        response = client.call(a=2, b=3)
        if response is None:
            print("Service call timed out / failed")
        else:
            print(f"2 + 3 = {response.sum}")
    finally:
        node.close()


if __name__ == "__main__":
    main()

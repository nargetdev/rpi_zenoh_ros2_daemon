#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Service server example (mirrors Pico-ROS examples/srv_server_add2ints.c).

    python examples/add_two_ints_server.py -m client -a tcp/127.0.0.1:7447
    # then, from a ROS 2 + rmw_zenoh shell:
    ros2 service call /add_two_ints example_interfaces/srv/AddTwoInts '{a: 2, b: 3}'
"""
from pico_ros_py import Interface, Node, spin


def main() -> None:
    iface = Interface.from_args()
    print(f"Starting pico-ros-py add_two_ints server: {iface.mode} {iface.locator}")
    node = Node("pico_add_two_ints", iface)

    # `srv` is referenced lazily inside the handler, so it is bound by the time
    # a request actually arrives.
    def handle(request):
        total = request.a + request.b
        print(f"add_two_ints: {request.a} + {request.b} = {total}")
        return srv.response_class(sum=total)

    srv = node.create_service(
        "/add_two_ints", "example_interfaces/srv/AddTwoInts", handle
    )
    spin(node)


if __name__ == "__main__":
    main()

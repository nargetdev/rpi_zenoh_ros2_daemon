#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Parameter server example (a Python port of Pico-ROS examples/params_server.c).

Declares the same three parameters as the C example and serves the standard ROS 2
parameter interface, so the node is configurable from `ros2 param` and
rqt_reconfigure.

    python examples/params_server.py -m client -a tcp/127.0.0.1:7447
    # then, from a ROS 2 + rmw_zenoh shell:
    ros2 param list /picoros
    ros2 param get  /picoros example.param1
    ros2 param set  /picoros example.param1 7
    ros2 run rqt_reconfigure rqt_reconfigure
"""
from pico_ros_py import (
    DictParameterBackend,
    IntegerRange,
    Interface,
    Node,
    ParameterServer,
    ParameterType,
    ParameterDescriptor,
    spin,
)


def build_backend() -> DictParameterBackend:
    backend = DictParameterBackend()
    backend.declare(
        "example.param1",
        10,
        description="Super important parameter",
        integer_range=IntegerRange(from_value=-50, to_value=50),
    )
    backend.declare(
        "example.param2",
        1.2525,
        descriptor=ParameterDescriptor(
            type=ParameterType.DOUBLE, description="Don't touch!"
        ),
    )
    backend.declare("example.param3", bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))

    def report(name, value):
        print(f"parameter set: {name} -> {value.value!r}")

    backend.on_set = report
    return backend


def main() -> None:
    iface = Interface.from_args()
    print(f"Starting pico-ros-py parameter server: {iface.mode} {iface.locator}")
    node = Node("picoros", iface)
    server = ParameterServer(node, build_backend()).start()
    print(f"Parameter server started for {node.fully_qualified_name}")
    try:
        spin(node)
    finally:
        server.stop()


if __name__ == "__main__":
    main()

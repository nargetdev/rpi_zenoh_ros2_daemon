#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Env-driven pico-ros-py parameter server (the "pi daemon" role in CI).

Reads ROUTER_IP / ROUTER_PORT / NODE_NAME from the environment, declares a few
demo parameters, and serves the ROS 2 parameter interface until killed.
"""
import os

from pico_ros_py import (
    DictParameterBackend,
    IntegerRange,
    Node,
    ParameterDescriptor,
    ParameterServer,
    ParameterType,
    spin,
)


def build_backend() -> DictParameterBackend:
    backend = DictParameterBackend()
    backend.declare(
        "example.param1",
        10,
        description="demo integer with range",
        integer_range=IntegerRange(from_value=-50, to_value=50),
    )
    backend.declare(
        "example.param2",
        1.2525,
        descriptor=ParameterDescriptor(type=ParameterType.DOUBLE, description="demo double"),
    )
    backend.declare("example.greeting", "hello")

    def report(name, value):
        print(f"[params] set {name} -> {value.value!r}", flush=True)

    backend.on_set = report
    return backend


def main() -> None:
    router_ip = os.environ.get("ROUTER_IP", "127.0.0.1")
    router_port = int(os.environ.get("ROUTER_PORT", "7447"))
    node_name = os.environ.get("NODE_NAME", "picoros")

    node = Node(node_name, router_ip=router_ip, router_port=router_port)
    server = ParameterServer(node, build_backend()).start()
    print(
        f"[params] server up: node={node.fully_qualified_name} "
        f"router={router_ip}:{router_port}",
        flush=True,
    )
    try:
        spin(node)
    finally:
        server.stop()


if __name__ == "__main__":
    main()

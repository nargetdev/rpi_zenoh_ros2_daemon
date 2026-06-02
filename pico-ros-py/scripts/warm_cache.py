#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Warm the zenoh_ros2_sdk type cache at image-build time.

The SDK clones ROS 2 message repos (rcl_interfaces, common_interfaces, ...) on
first use. Doing it during `docker build` bakes the clones into the image so the
running container needs no network to register types. Type registration only
touches the rosbags typestore + a git clone; it does not require a live router.
"""
import os

os.environ.setdefault("ZENOH_ROS2_SDK_CACHE", "/opt/zenoh_ros2_sdk_cache")

from pico_ros_py.picoserdes import get_message_class, get_session  # noqa: E402

MESSAGES = [
    "std_msgs/msg/String",
    "builtin_interfaces/msg/Time",
    "rcl_interfaces/msg/ParameterValue",
    "rcl_interfaces/msg/Parameter",
    "rcl_interfaces/msg/ParameterDescriptor",
    "rcl_interfaces/msg/FloatingPointRange",
    "rcl_interfaces/msg/IntegerRange",
    "rcl_interfaces/msg/SetParametersResult",
    "rcl_interfaces/msg/ListParametersResult",
    "rcl_interfaces/msg/ParameterEvent",
]

SERVICES = [
    "rcl_interfaces/srv/ListParameters",
    "rcl_interfaces/srv/GetParameters",
    "rcl_interfaces/srv/GetParameterTypes",
    "rcl_interfaces/srv/SetParameters",
    "rcl_interfaces/srv/SetParametersAtomically",
    "rcl_interfaces/srv/DescribeParameters",
]


def main() -> None:
    session = get_session()
    for msg_type in MESSAGES:
        get_message_class(msg_type)
        print(f"warmed {msg_type}", flush=True)
    for srv_type in SERVICES:
        # Registering the request type pulls in the whole service definition.
        session.register_message_type(None, f"{srv_type}_Request")
        session.register_message_type(None, f"{srv_type}_Response")
        print(f"warmed {srv_type}", flush=True)
    print("cache warm complete", flush=True)


if __name__ == "__main__":
    main()

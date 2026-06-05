#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Warm the zenoh_ros2_sdk type cache at image-build time for the pi_runtime daemon.

The SDK clones ROS 2 message repos (common_interfaces, std_srvs, ...) on first
use to build its rosbags typestore. Doing it during `docker build` (with `git`
installed and the network available) bakes the clones into the image so the
running container needs NO network and never stalls a live capture/publish on a
git clone.

Mirror of `pico-ros-py/scripts/warm_cache.py` -- same `get_message_class`
registration API, just the type list the real DSLR runtime publishes:

  * std_msgs/msg/Float32          -- the core-temp topic (Ros2CoreTempBroadcaster)
  * sensor_msgs/msg/Image         -- the native ROS 2 frame topic (Ros2ImagePublisher)
  * std_msgs/msg/Header           -- nested in Image
  * builtin_interfaces/msg/Time   -- nested in Header

NOTE: the capture service `std_srvs/srv/SetBool` is deliberately NOT warmed here.
Unlike the `rcl_interfaces` services in pico-ros-py's warm_cache, the SDK cannot
fetch a std_srvs definition from the registry, and it does not need to: the
daemon constructs its `ROS2ServiceServer` with the SetBool request/response
definitions supplied INLINE (see `runtime.py`: `request_definition="bool data"`,
`response_definition="bool success\\nstring message"`), so no clone ever happens
for the service at runtime.
"""
import os

os.environ.setdefault("ZENOH_ROS2_SDK_CACHE", "/opt/zenoh_ros2_sdk_cache")

from pico_ros_py.picoserdes import get_message_class  # noqa: E402

MESSAGES = [
    "builtin_interfaces/msg/Time",
    "std_msgs/msg/Header",
    "std_msgs/msg/Float32",
    "sensor_msgs/msg/Image",
]


def main() -> None:
    for msg_type in MESSAGES:
        get_message_class(msg_type)
        print(f"warmed {msg_type}", flush=True)
    print("cache warm complete", flush=True)


if __name__ == "__main__":
    main()

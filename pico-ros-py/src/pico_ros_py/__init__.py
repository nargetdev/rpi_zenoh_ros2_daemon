# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 the pico-ros-py authors
"""pico-ros-py: a Python re-imagining of the Pico-ROS pattern.

Pico-ROS (https://github.com/Pico-ROS/Pico-ROS-software, BSD-3-Clause) is a
lightweight C ROS 2 client for microcontrollers built on zenoh-pico. pico-ros-py
keeps the same *semantics* -- Node, Publisher, Subscriber, Service server/client,
and a parameter server with a small pluggable backend -- but implements them in
Python on top of `zenoh_ros2_sdk`, for runtimes like the Raspberry Pi that can
run CPython but where a full ROS 2 install is unwanted.

Importing this package does not import zenoh_ros2_sdk; the transport is imported
lazily when you actually create a Node or start a ParameterServer.
"""

from __future__ import annotations

from .picoros import (
    Interface,
    Node,
    Publisher,
    ServiceClient,
    ServiceServer,
    Subscription,
    parse_locator,
    spin,
)
from .picoparams import (
    DictParameterBackend,
    FloatingPointRange,
    IntegerRange,
    Parameter,
    ParameterBackend,
    ParameterDescriptor,
    ParameterServer,
    ParameterType,
    ParameterValue,
)

__version__ = "0.1.0"

__all__ = [
    "Interface",
    "Node",
    "Publisher",
    "Subscription",
    "ServiceServer",
    "ServiceClient",
    "parse_locator",
    "spin",
    "ParameterType",
    "ParameterValue",
    "Parameter",
    "ParameterDescriptor",
    "FloatingPointRange",
    "IntegerRange",
    "ParameterBackend",
    "DictParameterBackend",
    "ParameterServer",
    "__version__",
]

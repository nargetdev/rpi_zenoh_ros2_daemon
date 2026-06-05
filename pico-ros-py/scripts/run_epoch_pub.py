#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Env-driven pico-ros-py "node under test": publish the wall-clock epoch in
nanoseconds on a topic, with ROS 2-compatible CDR serialization, over a live
Zenoh router. No ROS 2 install -- pure zenoh_ros2_sdk.

It brings up a single ROS 2 node (visible to `ros2 node list` via its Zenoh
liveliness token) and publishes a std_msgs/msg/Int64 carrying `time.time_ns()`,
so a stock ROS 2 validator can:

    ros2 topic echo node_under_test/node_under_test/epoch_ns

Env:
  ROUTER_IP    zenoh router host        (default 127.0.0.1)
  ROUTER_PORT  zenoh router port        (default 7447)
  NODE_NAME    ROS 2 node name          (default node_under_test)
  NAMESPACE    ROS 2 namespace          (default /node_under_test)
  TOPIC        topic (absolute)         (default /node_under_test/node_under_test/epoch_ns)
  MSG_TYPE     ROS 2 message type       (default std_msgs/msg/Int64)
  RATE_HZ      publish rate in Hz        (default 5)
"""
import os
import time

from pico_ros_py import Node


def main() -> None:
    router_ip = os.environ.get("ROUTER_IP", "127.0.0.1")
    router_port = int(os.environ.get("ROUTER_PORT", "7447"))
    node_name = os.environ.get("NODE_NAME", "node_under_test")
    namespace = os.environ.get("NAMESPACE", "/node_under_test")
    topic = os.environ.get("TOPIC", "/node_under_test/node_under_test/epoch_ns")
    msg_type = os.environ.get("MSG_TYPE", "std_msgs/msg/Int64")
    rate_hz = float(os.environ.get("RATE_HZ", "5"))
    period = 1.0 / rate_hz if rate_hz > 0 else 0.2

    node = Node(
        node_name,
        namespace=namespace,
        router_ip=router_ip,
        router_port=router_port,
    )
    pub = node.create_publisher(topic, msg_type)
    print(
        f"[node_under_test] node={node.fully_qualified_name} topic={topic} "
        f"type={msg_type} router={router_ip}:{router_port} rate={rate_hz}Hz",
        flush=True,
    )

    i = 0
    try:
        while True:
            epoch_ns = time.time_ns()
            # std_msgs/msg/Int64 has a single int64 field named `data`.
            pub.publish(data=epoch_ns)
            if i % 10 == 0:
                print(f"[node_under_test] published #{i} epoch_ns={epoch_ns}", flush=True)
            i += 1
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()


if __name__ == "__main__":
    main()

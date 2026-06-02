from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from std_srvs.srv import SetBool


class CaptureClient(Node):
    def __init__(self) -> None:
        super().__init__("dslr_capture_client")
        self.declare_parameter("service_name", "/dslr/capture")
        self.declare_parameter("service_wait_timeout_sec", 30.0)
        self.declare_parameter("call_timeout_sec", 60.0)
        service_name = self.get_parameter("service_name").value
        self.service_wait_timeout_sec = float(self.get_parameter("service_wait_timeout_sec").value)
        self.call_timeout_sec = float(self.get_parameter("call_timeout_sec").value)
        self.client = self.create_client(SetBool, service_name)

    def call(self) -> None:
        if not self.client.wait_for_service(timeout_sec=self.service_wait_timeout_sec):
            self.get_logger().error("service did not become available before timeout")
            return
        request = SetBool.Request()
        request.data = True
        future = self.client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=self.call_timeout_sec)
        if future.result() is None:
            self.get_logger().error("service call failed or timed out")
            return

        response = future.result()
        if not response.success:
            self.get_logger().error(f"capture failed: {response.message}")
            return

        metadata = json.loads(response.message)
        self.get_logger().info(
            "capture_id=%s image_key=%s encoding=%s %sx%s message=%s"
            % (
                metadata.get("capture_id"),
                metadata.get("image_key"),
                metadata.get("encoding"),
                metadata.get("width"),
                metadata.get("height"),
                metadata.get("message"),
            )
        )


def main() -> None:
    rclpy.init()
    node = CaptureClient()
    try:
        node.call()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

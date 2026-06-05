"""DEPRECATED for images.

This relay node subscribes to plain Zenoh frame blobs and republishes them as ROS
image topics. Its image republication is **superseded** by the native one-hop path:
``pi_runtime`` now publishes captured frames directly as native
``sensor_msgs/msg/Image`` via ``zenoh_ros2_sdk.ROS2Publisher`` onto the shared
rmw_zenoh router, where ``foxglove_bridge`` / any ROS 2 node displays them with no
relay in between (confirmed live on ``soma:8765``). Enable it via the
``ros2_publish`` block in the Pi config. This node is retained only as reference;
do not deploy it for image republication.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json

from PIL import Image as PilImage
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import Header
import zenoh


@dataclass(slots=True)
class FrameEnvelope:
    capture_id: str
    image_key: str
    payload: bytes
    encoding: str
    width: int
    height: int


class ZenohDslrGateway(Node):
    def __init__(self) -> None:
        super().__init__("zenoh_dslr_gateway")
        self.declare_parameter("camera_id", "cam0")
        self.declare_parameter("frame_key_prefix", "dslr/cam0/frames")
        self.declare_parameter("image_topic", "/dslr/image_raw")
        self.declare_parameter("compressed_topic", "/dslr/image_compressed")
        self.declare_parameter("zenoh_config_path", "")

        self.camera_id = self.get_parameter("camera_id").value
        self.frame_key_prefix = self.get_parameter("frame_key_prefix").value

        self.raw_publisher = self.create_publisher(
            Image,
            self.get_parameter("image_topic").value,
            10,
        )
        self.compressed_publisher = self.create_publisher(
            CompressedImage,
            self.get_parameter("compressed_topic").value,
            10,
        )

        zenoh_config_path = self.get_parameter("zenoh_config_path").value
        config = zenoh.Config.from_file(zenoh_config_path) if zenoh_config_path else zenoh.Config()
        self._session = zenoh.open(config)
        self._frame_subscriber = self._session.declare_subscriber(
            f"{self.frame_key_prefix}/**",
            self._on_frame,
        )
        self.get_logger().info(f"relay ready: frame_prefix={self.frame_key_prefix}")

    def destroy_node(self) -> bool:
        self._frame_subscriber.undeclare()
        self._session.close()
        return super().destroy_node()

    def _on_frame(self, sample: zenoh.Sample) -> None:
        metadata = {}
        if sample.attachment is not None:
            metadata = json.loads(sample.attachment.to_string())

        capture_id = metadata.get("capture_id")
        if not capture_id:
            self.get_logger().warning("received frame without capture_id metadata")
            return

        image_key = metadata.get("image_key", str(sample.key_expr))
        frame = FrameEnvelope(
            capture_id=capture_id,
            image_key=image_key,
            payload=sample.payload.to_bytes(),
            encoding=str(sample.encoding) if sample.encoding else metadata.get("encoding", "image/jpeg"),
            width=int(metadata.get("width", 0)),
            height=int(metadata.get("height", 0)),
        )
        self._publish_frame(frame)

    def _publish_frame(self, frame: FrameEnvelope) -> None:
        now = self.get_clock().now().to_msg()
        header = Header(stamp=now, frame_id=self.camera_id)

        compressed = CompressedImage()
        compressed.header = header
        compressed.format = frame.encoding
        compressed.data = frame.payload
        self.compressed_publisher.publish(compressed)

        raw_message = self._decode_to_image_message(frame, header)
        if raw_message is not None:
            self.raw_publisher.publish(raw_message)
        self.get_logger().info(
            f"republished capture_id={frame.capture_id} image_key={frame.image_key} encoding={frame.encoding}"
        )

    def _decode_to_image_message(self, frame: FrameEnvelope, header: Header) -> Image | None:
        try:
            with PilImage.open(io.BytesIO(frame.payload)) as decoded:
                rgb = decoded.convert("RGB")
                width, height = rgb.size
                data = rgb.tobytes()
        except Exception as exc:
            self.get_logger().warning(f"failed to decode compressed frame {frame.capture_id}: {exc}")
            return None

        image = Image()
        image.header = header
        image.height = height
        image.width = width
        image.encoding = "rgb8"
        image.is_bigendian = 0
        image.step = width * 3
        image.data = data
        return image


def main() -> None:
    rclpy.init()
    node = ZenohDslrGateway()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

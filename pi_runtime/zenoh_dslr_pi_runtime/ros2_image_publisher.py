from __future__ import annotations

import io
import logging
import time
from typing import Any

from PIL import Image as PilImage

from .models import Ros2PublishConfig

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.ros2_image_publisher")


class Ros2ImagePublisher:
    """Lazy, failure-tolerant native ROS 2 ``sensor_msgs/msg/Image`` publisher.

    Wraps ``zenoh_ros2_sdk.ROS2Publisher`` so a captured frame can be emitted as a
    native CDR-encoded ``sensor_msgs/msg/Image`` directly onto the shared rmw_zenoh
    router. ``soma``'s router + ``foxglove_bridge`` (or any ROS 2 node) then displays
    it one-hop, with no ``ros2_gateway`` relay in between.

    Mirrors the resilience contract of :class:`heartbeat._MqttPublisher`: the
    publisher (and its ROS message-definition load + Zenoh session) is constructed
    lazily on first use, every failure is swallowed and warned-about at most once,
    and a dead router NEVER breaks capture.
    """

    def __init__(self, config: Ros2PublishConfig, frame_id: str | None = None) -> None:
        self._config = config
        self._frame_id = frame_id or "camera"
        self._publisher: Any | None = None
        self._time_cls: Any | None = None
        self._header_cls: Any | None = None
        self._warned = False

    def _ensure_publisher(self) -> Any | None:
        if self._publisher is not None:
            return self._publisher
        try:
            import numpy  # noqa: F401  (imported for the early, clear failure if missing)
            from zenoh_ros2_sdk import ROS2Publisher, get_message_class
        except Exception as exc:  # pragma: no cover - depends on optional deps
            if not self._warned:
                LOGGER.warning("ROS 2 image publish disabled: imports unavailable (%s)", exc)
                self._warned = True
            return None
        try:
            publisher = ROS2Publisher(
                topic=self._config.topic,
                msg_type="sensor_msgs/msg/Image",
                domain_id=self._config.domain_id,
                router_ip=self._config.router_ip,
                router_port=self._config.router_port,
                qos=self._build_qos(),
            )
            self._time_cls = get_message_class("builtin_interfaces/msg/Time")
            self._header_cls = get_message_class("std_msgs/msg/Header")
            self._publisher = publisher
            LOGGER.info(
                "ROS 2 image publisher ready: topic=%s router=%s:%s domain=%s keyexpr=%s",
                self._config.topic,
                self._config.router_ip,
                self._config.router_port,
                self._config.domain_id,
                getattr(publisher, "keyexpr", "?"),
            )
            return publisher
        except Exception as exc:
            if not self._warned:
                LOGGER.warning(
                    "ROS 2 image publisher init failed (%s:%s): %s",
                    self._config.router_ip,
                    self._config.router_port,
                    exc,
                )
                self._warned = True
            return None

    def _build_qos(self) -> Any | None:
        """Map the shared contract's QoS fields onto a ``zenoh_ros2_sdk`` QoS profile.

        Best-effort: if the SDK QoS module is unavailable or the values are
        unexpected we fall back to the SDK default (``None``) rather than fail.
        """
        try:
            from zenoh_ros2_sdk.qos import QosProfile, QosReliability
        except Exception:  # pragma: no cover - SDK layout dependent
            return None
        reliability = (
            QosReliability.RELIABLE
            if str(self._config.qos_reliability).lower() == "reliable"
            else QosReliability.BEST_EFFORT
        )
        return QosProfile(
            reliability=reliability,
            history_depth=int(self._config.qos_history_depth),
        )

    def _downsample(self, image: PilImage.Image) -> PilImage.Image:
        """Shrink to fit within ``max_width`` x ``max_height`` preserving aspect.

        A ``0`` on either axis disables that constraint. Never upscales.
        """
        max_w = self._config.max_width
        max_h = self._config.max_height
        if max_w <= 0 and max_h <= 0:
            return image
        width, height = image.size
        if width == 0 or height == 0:
            return image
        scale = 1.0
        if max_w > 0:
            scale = min(scale, max_w / width)
        if max_h > 0:
            scale = min(scale, max_h / height)
        if scale >= 1.0:
            return image
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return image.resize(new_size, PilImage.BILINEAR)

    def publish(self, image_bytes: bytes, src_encoding: str, frame_id: str | None = None) -> bool:
        """Decode ``image_bytes``, downsample, and publish as ``sensor_msgs/msg/Image``.

        Returns ``True`` if a frame was published, ``False`` on any failure. Never
        raises: a dead router or undecodable frame is logged and swallowed so the
        capture path is untouched.
        """
        publisher = self._ensure_publisher()
        if publisher is None:
            return False
        try:
            import numpy as np

            with PilImage.open(io.BytesIO(image_bytes)) as decoded:
                rgb = self._downsample(decoded.convert("RGB"))
                width, height = rgb.size
                data = np.frombuffer(rgb.tobytes(), dtype=np.uint8)

            now = time.time()
            stamp = self._time_cls(sec=int(now), nanosec=int((now % 1) * 1e9))
            header = self._header_cls(stamp=stamp, frame_id=frame_id or self._frame_id)
            publisher.publish(
                header=header,
                height=height,
                width=width,
                encoding="rgb8",
                is_bigendian=0,
                step=width * 3,
                data=data,
            )
            return True
        except Exception as exc:  # pragma: no cover - network/decode dependent
            LOGGER.debug("ROS 2 image publish failed: %s", exc)
            return False

    def close(self) -> None:
        if self._publisher is not None:
            try:
                self._publisher.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._publisher = None

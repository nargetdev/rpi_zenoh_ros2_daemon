from __future__ import annotations

import logging
import threading
from typing import Any

from .heartbeat import read_core_temp_c
from .models import CoreTempPublishConfig
from .qos_profile import build_qos_profile

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.ros2_core_temp_publisher")


class Ros2CoreTempBroadcaster:
    """Periodically publishes the SoC core temperature as a native ROS 2 message.

    Emits ``std_msgs/msg/Float32`` (``data`` = degrees Celsius) over rmw_zenoh via
    ``zenoh_ros2_sdk.ROS2Publisher`` on its own timer thread, so ``ros2 topic echo``
    / foxglove / any ROS 2 node sees a real ``Float32`` topic one hop off the shared
    router. This is the CDR-encoded counterpart to the JSON ``core_temp_c`` field
    already carried in the heartbeat blob.

    Mirrors the resilience contract of :class:`ros2_image_publisher.Ros2ImagePublisher`
    and the timer shape of :class:`heartbeat.PgwaamOnlineBroadcaster`: the publisher
    (and its ROS message-definition load + Zenoh session) is constructed lazily on
    first use, every failure is swallowed and warned-about at most once, and a dead
    router NEVER breaks the runtime.
    """

    def __init__(self, config: CoreTempPublishConfig) -> None:
        self._config = config
        self._publisher: Any | None = None
        self._warned = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _ensure_publisher(self) -> Any | None:
        if self._publisher is not None:
            return self._publisher
        try:
            from zenoh_ros2_sdk import ROS2Publisher
        except Exception as exc:  # pragma: no cover - depends on optional deps
            if not self._warned:
                LOGGER.warning("ROS 2 core-temp publish disabled: imports unavailable (%s)", exc)
                self._warned = True
            return None
        try:
            publisher = ROS2Publisher(
                topic=self._config.topic,
                msg_type="std_msgs/msg/Float32",
                domain_id=self._config.domain_id,
                router_ip=self._config.router_ip,
                router_port=self._config.router_port,
                qos=build_qos_profile(
                    self._config.qos_reliability, self._config.qos_history_depth
                ),
            )
            self._publisher = publisher
            LOGGER.info(
                "ROS 2 core-temp publisher ready: topic=%s router=%s:%s domain=%s keyexpr=%s",
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
                    "ROS 2 core-temp publisher init failed (%s:%s): %s",
                    self._config.router_ip,
                    self._config.router_port,
                    exc,
                )
                self._warned = True
            return None

    def publish_value(self, temp_c: float) -> bool:
        """Publish a single ``Float32`` temperature reading.

        Returns ``True`` if a sample was emitted, ``False`` on any failure. Never
        raises: a dead router is logged and swallowed.
        """
        publisher = self._ensure_publisher()
        if publisher is None:
            return False
        try:
            publisher.publish(data=float(temp_c))
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.debug("ROS 2 core-temp publish failed: %s", exc)
            return False

    def publish_once(self) -> bool:
        """Read the core temperature and publish it. No-op if the probe is unreadable."""
        temp_c = read_core_temp_c(self._config.thermal_zone_path)
        if temp_c is None:
            return False
        return self.publish_value(temp_c)

    def start(self) -> None:
        if not self._config.enabled:
            LOGGER.info("ROS 2 core-temp publish disabled by config")
            return
        # Emit one sample immediately so a subscriber sees a value without
        # waiting a full interval, then continue on the timer.
        self.publish_once()
        self._thread = threading.Thread(target=self._loop, name="dslr-core-temp", daemon=True)
        self._thread.start()
        LOGGER.info(
            "ROS 2 core-temp publish started: topic=%s interval=%ss",
            self._config.topic,
            self._config.interval_s,
        )

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._config.interval_s)
            if self._stop_event.is_set():
                break
            self.publish_once()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.close()

    def close(self) -> None:
        if self._publisher is not None:
            try:
                self._publisher.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._publisher = None

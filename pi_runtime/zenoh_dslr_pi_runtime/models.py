from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import re
import socket


def slugify_camera_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    return cleaned.strip("_") or "dslr"


def ros2_safe_name(value: str) -> str:
    """Sanitize a token into a ROS 2-legal topic-name segment.

    A ROS 2 topic-name token may contain only ``[A-Za-z0-9_]`` -- hyphens are
    illegal -- so a hostname like ``id2-rpi4`` must collapse to ``id2_rpi4`` for
    the resulting topic to be visible to ``ros2 topic echo`` / rmw_zenoh. Any
    run of non-conforming characters becomes a single ``_``.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return cleaned.strip("_") or "device"


def default_device_id(camera_id: str | None = None) -> str:
    """Derive a device id from the hostname, falling back to ``camera_id``.

    The host's short name (``socket.gethostname()`` without any domain suffix)
    is the natural fleet identity for the pgwaam online pulse. If the hostname
    cannot be determined we fall back to ``camera_id`` so the device is still
    addressable.
    """
    try:
        host = socket.gethostname()
    except Exception:  # pragma: no cover - platform dependent
        host = ""
    host = (host or "").strip().split(".")[0]
    return host or (camera_id or "device")


@dataclass(slots=True)
class CaptureBackendConfig:
    type: str
    command: str | None = None
    encoding: str = "image/jpeg"
    port: str | None = None
    filename_pattern: str = "{capture_id}"
    keep_on_camera: bool = False
    extra_args: list[str] | None = None


@dataclass(slots=True)
class PersistenceConfig:
    enabled: bool = True
    directory: str = "./captures"
    max_bytes: int = 720 * 1024 * 1024


@dataclass(slots=True)
class MqttHeartbeatConfig:
    """Redundant MQTT heartbeat channel. Defaults to the shop broker used by the ESP32 fleet."""

    enabled: bool = False
    host: str = "172.31.1.252"
    port: int = 1883
    topic: str | None = None
    qos: int = 0
    keepalive: int = 60
    username: str | None = None
    password: str | None = None
    client_id: str | None = None


@dataclass(slots=True)
class PgwaamOnlineConfig:
    """pgwaam liveness pulse published on ``pgwaam/{device_id}/online``.

    A small, dedicated MQTT channel (mirrors the ``MqttHeartbeatConfig`` shape so
    it can reuse ``_MqttPublisher``). The pulse is a minimal JSON document
    ``{device_id, status: "online", ts, host}`` published ``retain``ed by
    default so a late-joining mothership subscriber immediately learns the
    device's last-known online state.
    """

    enabled: bool = False
    host: str = "172.31.1.252"
    port: int = 1883
    topic: str | None = None
    qos: int = 0
    retain: bool = True
    keepalive: int = 60
    interval_s: float = 5.0
    username: str | None = None
    password: str | None = None
    client_id: str | None = None


@dataclass(slots=True)
class Ros2PublishConfig:
    """Native ROS 2 ``sensor_msgs/msg/Image`` publication over rmw_zenoh.

    When ``enabled``, captured frames are published a second time (alongside the
    existing raw Zenoh blob ``put``) as a native CDR-encoded ``sensor_msgs/msg/Image``
    via ``zenoh_ros2_sdk.ROS2Publisher``. This is the one-hop path that ``soma``'s
    rmw_zenoh router + ``foxglove_bridge`` (or any ROS 2 node) can display directly,
    retiring the separate ``ros2_gateway`` relay for images.

    SHARED CONTRACT: this block must match the ansible side EXACTLY.
    """

    enabled: bool = False
    topic: str | None = None
    encoding: str = "rgb8"
    max_width: int = 640
    max_height: int = 480
    domain_id: int = 0
    router_ip: str = "172.31.1.252"
    router_port: int = 7447
    qos_reliability: str = "reliable"
    qos_history_depth: int = 5


@dataclass(slots=True)
class CoreTempPublishConfig:
    """Native ROS 2 ``std_msgs/msg/Float32`` core-temperature publication over rmw_zenoh.

    When ``enabled``, the SoC core temperature (degrees Celsius) is published
    periodically as a CDR-encoded ``std_msgs/msg/Float32`` via
    ``zenoh_ros2_sdk.ROS2Publisher``, so ``ros2 topic echo`` / foxglove / any ROS 2
    node sees a real ``Float32`` topic one hop off the shared router -- distinct
    from the JSON ``core_temp_c`` field already embedded in the heartbeat blob.

    The default topic mirrors the pgwaam online-channel convention,
    ``/{application}/{hostname}/online/core_temp``, with every segment sanitized
    to a ROS 2-legal name (e.g. ``id2-rpi4`` -> ``id2_rpi4``).

    SHARED CONTRACT: this block must match the ansible side EXACTLY.
    """

    enabled: bool = False
    application: str = "pgwaam"
    topic: str | None = None
    interval_s: float = 5.0
    domain_id: int = 0
    router_ip: str = "172.31.1.252"
    router_port: int = 7447
    qos_reliability: str = "reliable"
    qos_history_depth: int = 5
    thermal_zone_path: str = "/sys/class/thermal/thermal_zone0/temp"


@dataclass(slots=True)
class HeartbeatConfig:
    enabled: bool = True
    interval_s: float = 5.0
    zenoh_key: str | None = None
    liveliness_key: str | None = None
    report_core_temp: bool = True
    report_throttled: bool = True
    thermal_zone_path: str = "/sys/class/thermal/thermal_zone0/temp"
    mqtt: MqttHeartbeatConfig = field(default_factory=MqttHeartbeatConfig)


@dataclass(slots=True)
class PiRuntimeSettings:
    camera_id: str
    camera_model: str
    capture_service_name: str
    frame_key_prefix: str
    capture_backend: CaptureBackendConfig
    persistence: PersistenceConfig
    zenoh_config_path: str | None = None
    router_ip: str | None = None
    router_port: int | None = None
    publish_delay_ms: int = 0
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    device_id: str = field(default_factory=default_device_id)
    pgwaam: PgwaamOnlineConfig = field(default_factory=PgwaamOnlineConfig)
    ros2_publish: Ros2PublishConfig = field(default_factory=Ros2PublishConfig)
    core_temp_publish: CoreTempPublishConfig = field(default_factory=CoreTempPublishConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> "PiRuntimeSettings":
        config_path = Path(path).resolve()
        payload = json.loads(config_path.read_text())

        camera_model = payload.get("camera_model", payload.get("camera_id", "dslr"))
        camera_id = payload.get("camera_id", slugify_camera_name(camera_model))
        capture_service_name = payload.get("capture_service_name", f"/dslr/{camera_id}/capture")
        frame_key_prefix = payload.get("frame_key_prefix", f"dslr/{camera_id}/frames")

        backend = CaptureBackendConfig(**payload["capture_backend"])
        persistence_payload = payload.get("persistence", {})
        persistence_directory = persistence_payload.get("directory", "./captures")
        persistence_directory = str((config_path.parent / persistence_directory).resolve())
        persistence = PersistenceConfig(
            enabled=bool(persistence_payload.get("enabled", True)),
            directory=persistence_directory,
            max_bytes=int(persistence_payload.get("max_bytes", 720 * 1024 * 1024)),
        )

        zenoh_config_path = payload.get("zenoh_config_path")
        if zenoh_config_path:
            zenoh_config_path = str((config_path.parent / zenoh_config_path).resolve())

        heartbeat = _heartbeat_from_payload(payload.get("heartbeat", {}), camera_id)

        device_id = payload.get("device_id") or default_device_id(camera_id)
        pgwaam = _pgwaam_from_payload(payload.get("pgwaam", {}), device_id)

        ros2_publish = _ros2_publish_from_payload(payload.get("ros2_publish", {}), camera_id)

        core_temp_publish = _core_temp_publish_from_payload(payload.get("core_temp_publish", {}), device_id)

        return cls(
            camera_id=camera_id,
            camera_model=camera_model,
            capture_service_name=capture_service_name,
            frame_key_prefix=frame_key_prefix,
            capture_backend=backend,
            persistence=persistence,
            zenoh_config_path=zenoh_config_path,
            router_ip=payload.get("router_ip"),
            router_port=payload.get("router_port"),
            publish_delay_ms=int(payload.get("publish_delay_ms", 0)),
            heartbeat=heartbeat,
            device_id=device_id,
            pgwaam=pgwaam,
            ros2_publish=ros2_publish,
            core_temp_publish=core_temp_publish,
        )


def _heartbeat_from_payload(payload: dict[str, Any], camera_id: str) -> HeartbeatConfig:
    mqtt_payload = payload.get("mqtt", {})
    mqtt = MqttHeartbeatConfig(
        enabled=bool(mqtt_payload.get("enabled", False)),
        host=mqtt_payload.get("host", "172.31.1.252"),
        port=int(mqtt_payload.get("port", 1883)),
        topic=mqtt_payload.get("topic") or f"dslr/{camera_id}/heartbeat",
        qos=int(mqtt_payload.get("qos", 0)),
        keepalive=int(mqtt_payload.get("keepalive", 60)),
        username=mqtt_payload.get("username"),
        password=mqtt_payload.get("password"),
        client_id=mqtt_payload.get("client_id") or f"dslr-{camera_id}-heartbeat",
    )
    return HeartbeatConfig(
        enabled=bool(payload.get("enabled", True)),
        interval_s=float(payload.get("interval_s", 5.0)),
        zenoh_key=payload.get("zenoh_key") or f"dslr/{camera_id}/heartbeat",
        liveliness_key=payload.get("liveliness_key") or f"dslr/{camera_id}/alive",
        report_core_temp=bool(payload.get("report_core_temp", True)),
        report_throttled=bool(payload.get("report_throttled", True)),
        thermal_zone_path=payload.get("thermal_zone_path", "/sys/class/thermal/thermal_zone0/temp"),
        mqtt=mqtt,
    )


def _pgwaam_from_payload(payload: dict[str, Any], device_id: str) -> PgwaamOnlineConfig:
    return PgwaamOnlineConfig(
        enabled=bool(payload.get("enabled", False)),
        host=payload.get("host", "172.31.1.252"),
        port=int(payload.get("port", 1883)),
        topic=payload.get("topic") or f"pgwaam/{device_id}/online",
        qos=int(payload.get("qos", 0)),
        retain=bool(payload.get("retain", True)),
        keepalive=int(payload.get("keepalive", 60)),
        interval_s=float(payload.get("interval_s", 5.0)),
        username=payload.get("username"),
        password=payload.get("password"),
        client_id=payload.get("client_id") or f"pgwaam-{device_id}-online",
    )


def _ros2_publish_from_payload(payload: dict[str, Any], camera_id: str) -> Ros2PublishConfig:
    return Ros2PublishConfig(
        enabled=bool(payload.get("enabled", False)),
        topic=payload.get("topic") or f"/dslr/{camera_id}/image_raw",
        encoding=payload.get("encoding", "rgb8"),
        max_width=int(payload.get("max_width", 640)),
        max_height=int(payload.get("max_height", 480)),
        domain_id=int(payload.get("domain_id", 0)),
        router_ip=payload.get("router_ip", "172.31.1.252"),
        router_port=int(payload.get("router_port", 7447)),
        qos_reliability=payload.get("qos_reliability", "reliable"),
        qos_history_depth=int(payload.get("qos_history_depth", 5)),
    )


def _core_temp_publish_from_payload(payload: dict[str, Any], device_id: str) -> CoreTempPublishConfig:
    application = payload.get("application", "pgwaam")
    default_topic = f"/{ros2_safe_name(application)}/{ros2_safe_name(device_id)}/online/core_temp"
    return CoreTempPublishConfig(
        enabled=bool(payload.get("enabled", False)),
        application=application,
        topic=payload.get("topic") or default_topic,
        interval_s=float(payload.get("interval_s", 5.0)),
        domain_id=int(payload.get("domain_id", 0)),
        router_ip=payload.get("router_ip", "172.31.1.252"),
        router_port=int(payload.get("router_port", 7447)),
        qos_reliability=payload.get("qos_reliability", "reliable"),
        qos_history_depth=int(payload.get("qos_history_depth", 5)),
        thermal_zone_path=payload.get("thermal_zone_path", "/sys/class/thermal/thermal_zone0/temp"),
    )


@dataclass(slots=True)
class CaptureResult:
    capture_id: str
    payload: bytes
    encoding: str
    width: int
    height: int
    metadata: dict[str, Any]

    @property
    def image_key(self) -> str:
        return self.metadata["image_key"]

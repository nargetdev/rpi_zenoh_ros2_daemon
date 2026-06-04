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
class HeartbeatConfig:
    enabled: bool = True
    interval_s: float = 5.0
    zenoh_key: str | None = None
    liveliness_key: str | None = None
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

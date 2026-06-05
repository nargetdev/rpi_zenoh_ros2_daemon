from __future__ import annotations

import json
import logging
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import PiRuntimeSettings

if TYPE_CHECKING:  # pragma: no cover - typing only
    import zenoh

LOGGER = logging.getLogger("zenoh_dslr_pi_runtime.heartbeat")


def read_core_temp_c(path: str = "/sys/class/thermal/thermal_zone0/temp") -> float | None:
    """Read the SoC core temperature in Celsius from sysfs.

    Returns ``None`` when the thermal zone is unreadable (e.g. non-Pi host or
    missing sysfs entry) so a temperature probe never breaks the heartbeat.
    """
    try:
        raw = Path(path).read_text().strip()
        return round(int(raw) / 1000.0, 1)
    except Exception:  # pragma: no cover - hardware/filesystem dependent
        return None


def read_throttled() -> str | None:
    """Return the Raspberry Pi throttling/undervoltage bitmask via ``vcgencmd``.

    The value is the raw ``0x...`` word from ``vcgencmd get_throttled``; a
    non-zero value indicates current or past undervoltage/thermal throttling.
    Returns ``None`` when ``vcgencmd`` is unavailable.
    """
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:  # pragma: no cover - depends on vcgencmd availability
        return None
    if out.returncode != 0:
        return None
    # Output looks like "throttled=0x0"
    _, _, value = out.stdout.strip().partition("=")
    return value or None


def build_heartbeat_payload(
    settings: PiRuntimeSettings,
    seq: int,
    capture_count: int = 0,
    *,
    now: float | None = None,
    hostname: str | None = None,
    core_temp_c: float | None = None,
    throttled: str | None = None,
) -> dict[str, Any]:
    """Build a single heartbeat message describing this DSLR runtime instance."""
    return {
        "status": "alive",
        "camera_id": settings.camera_id,
        "camera_model": settings.camera_model,
        "host": hostname if hostname is not None else socket.gethostname(),
        "capture_service": settings.capture_service_name,
        "frame_key_prefix": settings.frame_key_prefix,
        "seq": seq,
        "capture_count": capture_count,
        "ts": now if now is not None else time.time(),
        "interval_s": settings.heartbeat.interval_s,
        "core_temp_c": core_temp_c,
        "throttled": throttled,
    }


def build_pgwaam_online_payload(
    settings: PiRuntimeSettings,
    *,
    now: float | None = None,
    hostname: str | None = None,
) -> dict[str, Any]:
    """Build the minimal pgwaam online pulse for this device.

    A small JSON document is used (rather than a bare ``"online"`` string) so the
    mothership can attribute the pulse to a device and reason about staleness via
    ``ts`` without a side channel.
    """
    return {
        "device_id": settings.device_id,
        "status": "online",
        "host": hostname if hostname is not None else socket.gethostname(),
        "ts": now if now is not None else time.time(),
    }


class _MqttPublisher:
    """Lazy, failure-tolerant MQTT publisher. A down broker never breaks the runtime."""

    def __init__(self, config) -> None:
        self._config = config
        self._client: Any | None = None
        self._warned = False

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            import paho.mqtt.client as mqtt
        except Exception as exc:  # pragma: no cover - depends on optional dep
            if not self._warned:
                LOGGER.warning("MQTT heartbeat disabled: paho-mqtt not importable (%s)", exc)
                self._warned = True
            return None
        try:
            client = mqtt.Client(client_id=self._config.client_id or "", clean_session=True)
            if self._config.username:
                client.username_pw_set(self._config.username, self._config.password)
            client.connect_async(self._config.host, self._config.port, keepalive=self._config.keepalive)
            client.loop_start()
            self._client = client
            return client
        except Exception as exc:
            if not self._warned:
                LOGGER.warning("MQTT heartbeat connect failed (%s:%s): %s", self._config.host, self._config.port, exc)
                self._warned = True
            return None

    def publish(self, payload: str) -> bool:
        client = self._ensure_client()
        if client is None:
            return False
        try:
            retain = bool(getattr(self._config, "retain", False))
            client.publish(self._config.topic, payload, qos=self._config.qos, retain=retain)
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.debug("MQTT publish failed: %s", exc)
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # pragma: no cover - best effort
                pass
            self._client = None


class HeartbeatBroadcaster:
    """Periodically broadcasts a liveliness signal for this Pi runtime.

    - Declares a Zenoh liveliness token (so the runtime *enumerates* on the graph).
    - Publishes a periodic heartbeat message on a Zenoh key.
    - Optionally mirrors the heartbeat to MQTT for redundancy.
    """

    def __init__(
        self,
        session: "zenoh.Session",
        settings: PiRuntimeSettings,
        capture_count: Callable[[], int] | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._capture_count = capture_count or (lambda: 0)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._liveliness_token: Any | None = None
        self._mqtt = _MqttPublisher(settings.heartbeat.mqtt) if settings.heartbeat.mqtt.enabled else None

    def start(self) -> None:
        cfg = self._settings.heartbeat
        if not cfg.enabled:
            LOGGER.info("heartbeat disabled by config")
            return
        self._declare_liveliness()
        self._thread = threading.Thread(target=self._loop, name="dslr-heartbeat", daemon=True)
        self._thread.start()
        LOGGER.info(
            "heartbeat started: zenoh_key=%s interval=%ss mqtt=%s",
            cfg.zenoh_key,
            cfg.interval_s,
            "on" if self._mqtt else "off",
        )

    def _declare_liveliness(self) -> None:
        key = self._settings.heartbeat.liveliness_key
        if not key:
            return
        try:
            self._liveliness_token = self._session.liveliness().declare_token(key)
            LOGGER.info("declared zenoh liveliness token: %s", key)
        except Exception as exc:  # pragma: no cover - zenoh API/runtime dependent
            LOGGER.warning("could not declare liveliness token %s: %s", key, exc)

    def _loop(self) -> None:
        cfg = self._settings.heartbeat
        seq = 0
        while not self._stop_event.is_set():
            core_temp_c = read_core_temp_c(cfg.thermal_zone_path) if cfg.report_core_temp else None
            throttled = read_throttled() if cfg.report_throttled else None
            payload = build_heartbeat_payload(
                self._settings,
                seq,
                self._capture_count(),
                core_temp_c=core_temp_c,
                throttled=throttled,
            )
            encoded = json.dumps(payload)
            try:
                self._session.put(cfg.zenoh_key, encoded)
            except Exception as exc:  # pragma: no cover - runtime dependent
                LOGGER.debug("zenoh heartbeat put failed: %s", exc)
            if self._mqtt is not None:
                self._mqtt.publish(encoded)
            seq += 1
            self._stop_event.wait(cfg.interval_s)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._liveliness_token is not None:
            try:
                self._liveliness_token.undeclare()
            except Exception:  # pragma: no cover - best effort
                pass
            self._liveliness_token = None
        if self._mqtt is not None:
            self._mqtt.close()


class PgwaamOnlineBroadcaster:
    """Publishes a periodic 'pgwaam online' liveness pulse over MQTT.

    Focused, independent of the Zenoh-coupled :class:`HeartbeatBroadcaster`: it
    only needs a configured MQTT broker, so it runs anywhere on the Pi. Reuses
    the failure-tolerant :class:`_MqttPublisher`, so a down broker never crashes
    the runtime.
    """

    def __init__(self, settings: PiRuntimeSettings) -> None:
        self._settings = settings
        self._cfg = settings.pgwaam
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._mqtt = _MqttPublisher(self._cfg) if self._cfg.enabled else None

    def start(self) -> None:
        if not self._cfg.enabled or self._mqtt is None:
            LOGGER.info("pgwaam online pulse disabled by config")
            return
        # Emit one pulse immediately so the mothership learns we're online
        # without waiting a full interval, then continue periodically.
        self.publish_once()
        self._thread = threading.Thread(target=self._loop, name="pgwaam-online", daemon=True)
        self._thread.start()
        LOGGER.info(
            "pgwaam online pulse started: topic=%s broker=%s:%s interval=%ss",
            self._cfg.topic,
            self._cfg.host,
            self._cfg.port,
            self._cfg.interval_s,
        )

    def publish_once(self) -> bool:
        if self._mqtt is None:
            return False
        payload = json.dumps(build_pgwaam_online_payload(self._settings))
        return self._mqtt.publish(payload)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._cfg.interval_s)
            if self._stop_event.is_set():
                break
            self.publish_once()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._mqtt is not None:
            self._mqtt.close()

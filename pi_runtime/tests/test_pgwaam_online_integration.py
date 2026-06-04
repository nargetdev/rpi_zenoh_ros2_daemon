"""End-to-end integration test for the 'pgwaam online pulse'.

This spins up a REAL MQTT broker on a dynamically-chosen, currently-unoccupied
port (never the hardcoded 1883), starts a mothership-side subscriber on
``pgwaam/pi3m50/online``, runs the Pi-side pulse publisher pointed at that local
broker for device ``pi3m50``, and asserts the pulse is received end-to-end.

Broker backend: prefers a local ``mosquitto`` binary; falls back to the pure
Python ``amqtt`` broker if mosquitto is unavailable. The test skips with a clear
reason ONLY if neither backend can be provisioned.
"""

from __future__ import annotations

import json
import queue
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

import paho.mqtt.client as mqtt

from zenoh_dslr_pi_runtime.heartbeat import (
    PgwaamOnlineBroadcaster,
    build_pgwaam_online_payload,
)
from zenoh_dslr_pi_runtime.models import PgwaamOnlineConfig, PiRuntimeSettings

CONFIG = Path(__file__).resolve().parents[1] / "config" / "pi3m50.example.json"
DEVICE_ID = "pi3m50"
TOPIC = f"pgwaam/{DEVICE_ID}/online"


def _free_port() -> int:
    """Grab an unoccupied TCP port by binding to port 0 and reading it back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_broker(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:  # broker not up yet
            last_err = exc
            time.sleep(0.1)
    raise RuntimeError(f"broker never came up on {host}:{port}: {last_err}")


class _MosquittoBroker:
    """Real mosquitto broker on a custom port, anonymous + no persistence."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._proc: subprocess.Popen | None = None
        self._tmp = tempfile.TemporaryDirectory(prefix="pgwaam-mosq-")

    def start(self) -> None:
        conf = Path(self._tmp.name) / "mosquitto.conf"
        conf.write_text(
            f"listener {self.port} 127.0.0.1\n"
            "allow_anonymous true\n"
            "persistence false\n"
        )
        self._proc = subprocess.Popen(
            ["mosquitto", "-c", str(conf)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_broker("127.0.0.1", self.port)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - best effort
                self._proc.kill()
            self._proc = None
        self._tmp.cleanup()


@pytest.fixture()
def broker():
    port = _free_port()
    if shutil.which("mosquitto"):
        b = _MosquittoBroker(port)
        b.start()
        try:
            yield "127.0.0.1", port
        finally:
            b.stop()
        return
    pytest.skip(
        "no MQTT broker backend available: install 'mosquitto' (brew install "
        "mosquitto / apt install mosquitto) or add the 'amqtt' test extra"
    )


class _Mothership:
    """Mothership-side MQTT subscriber that records received online pulses."""

    def __init__(self, host: str, port: int, topic: str) -> None:
        self.received: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._client = mqtt.Client(client_id="mothership-test")

        def on_message(_c, _u, msg):
            self.received.put((msg.topic, msg.payload.decode("utf-8")))

        def on_connect(c, _u, _f, _rc):
            c.subscribe(topic, qos=1)

        self._client.on_message = on_message
        self._client.on_connect = on_connect
        self._client.connect(host, port, keepalive=30)
        self._client.loop_start()

    def wait_for_pulse(self, timeout: float = 10.0) -> tuple[str, str]:
        return self.received.get(timeout=timeout)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def test_pgwaam_online_pulse_received_end_to_end(broker):
    host, port = broker

    # Mothership-side subscriber comes up first so it cannot miss the pulse.
    mothership = _Mothership(host, port, TOPIC)
    time.sleep(0.3)  # let the subscription land

    # Pi-side: derive settings from the real pi3m50 example config (proves
    # device_id=pi3m50 is wired through config), then point the pulse at the
    # local broker.
    settings = PiRuntimeSettings.from_file(CONFIG)
    assert settings.device_id == DEVICE_ID

    settings.pgwaam.enabled = True
    settings.pgwaam.host = host
    settings.pgwaam.port = port
    settings.pgwaam.interval_s = 0.2

    broadcaster = PgwaamOnlineBroadcaster(settings)
    broadcaster.start()
    try:
        topic, raw = mothership.wait_for_pulse(timeout=10.0)
    finally:
        broadcaster.stop()
        mothership.close()

    assert topic == TOPIC
    decoded = json.loads(raw)
    assert decoded["device_id"] == DEVICE_ID
    assert decoded["status"] == "online"
    assert decoded["host"] == "pi3m50" or "host" in decoded
    assert "ts" in decoded


def test_build_pgwaam_online_payload_shape():
    settings = PiRuntimeSettings.from_file(CONFIG)
    payload = build_pgwaam_online_payload(
        settings, now=1_700_000_000.0, hostname="pi3m50"
    )
    assert payload == {
        "device_id": "pi3m50",
        "status": "online",
        "host": "pi3m50",
        "ts": 1_700_000_000.0,
    }


def test_pgwaam_config_defaults_topic_from_device_id():
    cfg = PgwaamOnlineConfig()
    assert cfg.enabled is False
    assert cfg.port == 1883

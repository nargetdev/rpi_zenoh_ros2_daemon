import json
import time
from dataclasses import asdict
from pathlib import Path

from zenoh_dslr_pi_runtime.heartbeat import (
    HeartbeatBroadcaster,
    build_heartbeat_payload,
    read_core_temp_c,
)
from zenoh_dslr_pi_runtime.models import PiRuntimeSettings

CONFIG = Path(__file__).resolve().parents[1] / "config" / "id2-rpi4.example.json"
ARTIFACTS_DIR = Path(__file__).parent / "test_heartbeat_schema_artifacts"


def _artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    return ARTIFACTS_DIR


class _FakeToken:
    def __init__(self) -> None:
        self.undeclared = False

    def undeclare(self) -> None:
        self.undeclared = True


class _FakeLiveliness:
    def __init__(self) -> None:
        self.tokens: list[tuple[str, _FakeToken]] = []

    def declare_token(self, key: str) -> _FakeToken:
        token = _FakeToken()
        self.tokens.append((key, token))
        return token


class _FakeSession:
    def __init__(self) -> None:
        self.puts: list[tuple[str, str]] = []
        self._liveliness = _FakeLiveliness()

    def liveliness(self) -> _FakeLiveliness:
        return self._liveliness

    def put(self, key: str, payload: str) -> None:
        self.puts.append((key, payload))


def test_heartbeat_defaults_derived_from_camera_id():
    settings = PiRuntimeSettings.from_file(CONFIG)
    hb = settings.heartbeat
    assert hb.enabled is True
    assert hb.zenoh_key == "dslr/Canon_EOS_6D/heartbeat"
    assert hb.liveliness_key == "dslr/Canon_EOS_6D/alive"
    assert hb.mqtt.enabled is True
    assert hb.mqtt.host == "172.31.1.252"
    assert hb.mqtt.port == 1883
    assert hb.mqtt.topic == "dslr/Canon_EOS_6D/heartbeat"
    assert hb.mqtt.client_id == "dslr-Canon_EOS_6D-heartbeat"


def test_build_heartbeat_payload_shape():
    settings = PiRuntimeSettings.from_file(CONFIG)
    payload = build_heartbeat_payload(
        settings,
        seq=3,
        capture_count=7,
        now=1_700_000_000.0,
        hostname="notbroken",
        core_temp_c=48.3,
        throttled="0x0",
    )
    assert payload == {
        "status": "alive",
        "camera_id": "Canon_EOS_6D",
        "camera_model": "Canon EOS 6D",
        "host": "notbroken",
        "capture_service": "/dslr/Canon_EOS_6D/capture",
        "frame_key_prefix": "dslr/Canon_EOS_6D/frames",
        "seq": 3,
        "capture_count": 7,
        "ts": 1_700_000_000.0,
        "interval_s": 5.0,
        "core_temp_c": 48.3,
        "throttled": "0x0",
    }

    out = _artifacts_dir() / "test_heartbeat_schema_pydantic.json"
    out.write_text(json.dumps({"settings": asdict(settings), "sample_heartbeat": payload}, indent=2, default=str))


def test_build_heartbeat_payload_temp_defaults_to_none():
    settings = PiRuntimeSettings.from_file(CONFIG)
    payload = build_heartbeat_payload(settings, seq=0)
    assert payload["core_temp_c"] is None
    assert payload["throttled"] is None


def test_read_core_temp_c_parses_millidegrees(tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("48300\n")
    assert read_core_temp_c(str(zone)) == 48.3


def test_read_core_temp_c_missing_path_returns_none(tmp_path):
    assert read_core_temp_c(str(tmp_path / "does_not_exist")) is None


def test_broadcaster_publishes_zenoh_heartbeat_and_liveliness():
    settings = PiRuntimeSettings.from_file(CONFIG)
    settings.heartbeat.mqtt.enabled = False  # keep test hermetic (no broker)
    settings.heartbeat.interval_s = 0.05

    session = _FakeSession()
    broadcaster = HeartbeatBroadcaster(session, settings, capture_count=lambda: 0)
    broadcaster.start()
    time.sleep(0.2)
    broadcaster.stop()

    assert session.liveliness().tokens, "expected a liveliness token to be declared"
    assert session.liveliness().tokens[0][0] == "dslr/Canon_EOS_6D/alive"
    assert session.liveliness().tokens[0][1].undeclared is True
    assert len(session.puts) >= 1
    key, payload = session.puts[0]
    assert key == "dslr/Canon_EOS_6D/heartbeat"
    decoded = json.loads(payload)
    assert decoded["camera_id"] == "Canon_EOS_6D"
    assert decoded["seq"] == 0

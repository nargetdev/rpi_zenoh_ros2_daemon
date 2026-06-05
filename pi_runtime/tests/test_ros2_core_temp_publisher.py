import sys
import types

from zenoh_dslr_pi_runtime.models import CoreTempPublishConfig, PiRuntimeSettings, ros2_safe_name
from zenoh_dslr_pi_runtime.ros2_core_temp_publisher import Ros2CoreTempBroadcaster


# ---- ROS 2 name sanitization ---------------------------------------------


def test_ros2_safe_name_collapses_hyphens():
    assert ros2_safe_name("id2-rpi4") == "id2_rpi4"
    assert ros2_safe_name("pgwaam") == "pgwaam"
    assert ros2_safe_name("a..b--c") == "a_b_c"
    assert ros2_safe_name("--x--") == "x"
    assert ros2_safe_name("") == "device"


# ---- config parsing -------------------------------------------------------


def test_core_temp_defaults_disabled_with_derived_topic(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text(
        '{"camera_id": "cam9", "device_id": "id2-rpi4", "capture_backend": {"type": "mock"}}'
    )
    settings = PiRuntimeSettings.from_file(path)
    ct = settings.core_temp_publish
    assert ct.enabled is False
    # hostname hyphen sanitized into a ROS 2-legal topic
    assert ct.topic == "/pgwaam/id2_rpi4/online/core_temp"
    assert ct.application == "pgwaam"
    assert ct.interval_s == 5.0
    assert ct.domain_id == 0
    assert ct.router_ip == "172.31.1.252"
    assert ct.router_port == 7447
    assert ct.qos_reliability == "reliable"
    assert ct.qos_history_depth == 5
    assert ct.thermal_zone_path == "/sys/class/thermal/thermal_zone0/temp"


def test_core_temp_block_parsed(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text(
        """
        {
          "camera_id": "Canon_EOS_6D",
          "device_id": "id2-rpi4",
          "capture_backend": {"type": "mock"},
          "core_temp_publish": {
            "enabled": true,
            "application": "pgwaam",
            "interval_s": 2.0,
            "domain_id": 0,
            "router_ip": "172.31.1.252",
            "router_port": 7447
          }
        }
        """
    )
    settings = PiRuntimeSettings.from_file(path)
    ct = settings.core_temp_publish
    assert ct.enabled is True
    assert ct.interval_s == 2.0
    assert ct.topic == "/pgwaam/id2_rpi4/online/core_temp"


def test_core_temp_explicit_topic_overrides_default(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text(
        '{"camera_id": "c", "capture_backend": {"type": "mock"}, '
        '"core_temp_publish": {"enabled": true, "topic": "/custom/core_temp"}}'
    )
    settings = PiRuntimeSettings.from_file(path)
    assert settings.core_temp_publish.topic == "/custom/core_temp"


# ---- publisher behaviour (hermetic: SDK stubbed) --------------------------


class _FakePublisher:
    keyexpr = "0/pgwaam/id2_rpi4/online/core_temp/...fakehash"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.published: list[dict] = []
        self.closed = False

    def publish(self, **fields):
        self.published.append(fields)

    def close(self):
        self.closed = True


def _install_fake_sdk(monkeypatch, capture: dict):
    """Install a fake ``zenoh_ros2_sdk`` so publish() runs without a router."""

    def _ros2_publisher(**kwargs):
        pub = _FakePublisher(**kwargs)
        capture["publisher"] = pub
        return pub

    sdk = types.ModuleType("zenoh_ros2_sdk")
    sdk.ROS2Publisher = _ros2_publisher
    monkeypatch.setitem(sys.modules, "zenoh_ros2_sdk", sdk)

    qos_mod = types.ModuleType("zenoh_ros2_sdk.qos")

    class _Rel:
        RELIABLE = "RELIABLE"
        BEST_EFFORT = "BEST_EFFORT"

    class _Profile:
        def __init__(self, reliability=None, history_depth=None):
            self.reliability = reliability
            self.history_depth = history_depth

    qos_mod.QosReliability = _Rel
    qos_mod.QosProfile = _Profile
    monkeypatch.setitem(sys.modules, "zenoh_ros2_sdk.qos", qos_mod)


def test_publish_value_emits_float32_data(monkeypatch):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)

    config = CoreTempPublishConfig(enabled=True, topic="/pgwaam/id2_rpi4/online/core_temp")
    bc = Ros2CoreTempBroadcaster(config)
    assert bc.publish_value(67.3) is True

    pub = capture["publisher"]
    assert pub.kwargs["topic"] == "/pgwaam/id2_rpi4/online/core_temp"
    assert pub.kwargs["msg_type"] == "std_msgs/msg/Float32"
    fields = pub.published[0]
    assert fields == {"data": 67.3}
    assert isinstance(fields["data"], float)


def test_publish_once_reads_thermal_zone(monkeypatch, tmp_path):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)
    # millidegrees in sysfs -> 48.3 C
    zone = tmp_path / "temp"
    zone.write_text("48300\n")

    config = CoreTempPublishConfig(enabled=True, thermal_zone_path=str(zone))
    bc = Ros2CoreTempBroadcaster(config)
    assert bc.publish_once() is True
    assert capture["publisher"].published[0]["data"] == 48.3


def test_publish_once_noop_when_zone_unreadable(monkeypatch):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)
    config = CoreTempPublishConfig(enabled=True, thermal_zone_path="/no/such/thermal/zone")
    bc = Ros2CoreTempBroadcaster(config)
    # No probe -> no publish, but never raises and never inits a publisher.
    assert bc.publish_once() is False
    assert "publisher" not in capture


def test_publish_returns_false_when_sdk_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "zenoh_ros2_sdk", None)
    config = CoreTempPublishConfig(enabled=True, topic="/t")
    bc = Ros2CoreTempBroadcaster(config)
    assert bc.publish_value(40.0) is False


def test_close_is_safe_before_init():
    bc = Ros2CoreTempBroadcaster(CoreTempPublishConfig(enabled=True, topic="/t"))
    bc.close()  # no publisher yet -> no error
    bc.stop()  # idempotent, no thread started


def test_start_disabled_is_noop():
    bc = Ros2CoreTempBroadcaster(CoreTempPublishConfig(enabled=False))
    bc.start()  # disabled -> no thread, no publisher
    bc.stop()

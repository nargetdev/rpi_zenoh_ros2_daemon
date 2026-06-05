import io
import sys
import types

import numpy as np
import pytest
from PIL import Image as PilImage

from zenoh_dslr_pi_runtime.models import PiRuntimeSettings, Ros2PublishConfig
from zenoh_dslr_pi_runtime.ros2_image_publisher import Ros2ImagePublisher

CONFIG_JSON = """
{
  "camera_model": "Canon EOS 6D",
  "camera_id": "Canon_EOS_6D",
  "capture_backend": {"type": "mock"},
  "ros2_publish": {"enabled": true, "max_width": 64, "max_height": 48}
}
"""


def _write_config(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text(CONFIG_JSON)
    return path


def _colorbars_jpeg(width: int, height: int) -> bytes:
    bars = [
        (255, 255, 255),
        (255, 255, 0),
        (0, 255, 255),
        (0, 255, 0),
        (255, 0, 255),
        (255, 0, 0),
        (0, 0, 255),
        (0, 0, 0),
    ]
    row = np.empty((width, 3), dtype=np.uint8)
    for x in range(width):
        row[x] = bars[(x * len(bars)) // width]
    frame = np.ascontiguousarray(np.broadcast_to(row, (height, width, 3)))
    buf = io.BytesIO()
    PilImage.fromarray(frame, mode="RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ---- config parsing -------------------------------------------------------


def test_ros2_publish_defaults_disabled_with_derived_topic(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text('{"camera_id": "cam9", "capture_backend": {"type": "mock"}}')
    settings = PiRuntimeSettings.from_file(path)
    rp = settings.ros2_publish
    assert rp.enabled is False
    assert rp.topic == "/dslr/cam9/image_raw"
    assert rp.encoding == "rgb8"
    assert rp.max_width == 640
    assert rp.max_height == 480
    assert rp.domain_id == 0
    assert rp.router_ip == "172.31.1.252"
    assert rp.router_port == 7447
    assert rp.qos_reliability == "reliable"
    assert rp.qos_history_depth == 5


def test_ros2_publish_block_parsed(tmp_path):
    settings = PiRuntimeSettings.from_file(_write_config(tmp_path))
    rp = settings.ros2_publish
    assert rp.enabled is True
    assert rp.max_width == 64
    assert rp.max_height == 48
    assert rp.topic == "/dslr/Canon_EOS_6D/image_raw"


# ---- publisher behaviour (hermetic: SDK + numpy stubbed) ------------------


class _FakePublisher:
    keyexpr = "0/dslr/Canon_EOS_6D/image_raw/...fakehash"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.published: list[dict] = []
        self.closed = False

    def publish(self, **fields):
        self.published.append(fields)

    def close(self):
        self.closed = True


class _FakeMsg:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _install_fake_sdk(monkeypatch, capture: dict):
    """Install a fake ``zenoh_ros2_sdk`` so publish() runs without a router."""

    def _ros2_publisher(**kwargs):
        pub = _FakePublisher(**kwargs)
        capture["publisher"] = pub
        return pub

    sdk = types.ModuleType("zenoh_ros2_sdk")
    sdk.ROS2Publisher = _ros2_publisher
    sdk.get_message_class = lambda name: _FakeMsg
    monkeypatch.setitem(sys.modules, "zenoh_ros2_sdk", sdk)

    # QoS module: a trivial profile is fine, the fake publisher ignores it.
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


def test_publish_decodes_downsamples_and_emits_rgb8(monkeypatch):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)

    config = Ros2PublishConfig(enabled=True, topic="/dslr/Canon_EOS_6D/image_raw", max_width=64, max_height=48)
    pub = Ros2ImagePublisher(config, frame_id="Canon_EOS_6D")

    jpeg = _colorbars_jpeg(320, 240)  # 4:3 -> 64x48 after downsample
    assert pub.publish(jpeg, "image/jpeg", frame_id="Canon_EOS_6D") is True

    fields = capture["publisher"].published[0]
    assert fields["encoding"] == "rgb8"
    assert fields["is_bigendian"] == 0
    assert fields["width"] == 64
    assert fields["height"] == 48
    assert fields["step"] == 64 * 3
    # data must be a numpy uint8 array (rosbags CDR calls .view() on it)
    assert isinstance(fields["data"], np.ndarray)
    assert fields["data"].dtype == np.uint8
    assert fields["data"].size == 64 * 48 * 3
    assert fields["header"].frame_id == "Canon_EOS_6D"
    # first pixel is the white colorbar
    assert list(fields["data"][:3]) == [255, 255, 255]


def test_publish_no_downsample_when_limits_zero(monkeypatch):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)
    config = Ros2PublishConfig(enabled=True, topic="/t", max_width=0, max_height=0)
    pub = Ros2ImagePublisher(config)
    pub.publish(_colorbars_jpeg(128, 96), "image/jpeg")
    fields = capture["publisher"].published[0]
    assert fields["width"] == 128
    assert fields["height"] == 96


def test_publish_is_failure_tolerant_on_bad_image(monkeypatch):
    capture: dict = {}
    _install_fake_sdk(monkeypatch, capture)
    config = Ros2PublishConfig(enabled=True, topic="/t")
    pub = Ros2ImagePublisher(config)
    # Undecodable bytes must NOT raise — capture must never break.
    assert pub.publish(b"not-an-image", "image/jpeg") is False


def test_publish_returns_false_when_sdk_unavailable(monkeypatch):
    # Force the lazy import to fail; publish must swallow it.
    monkeypatch.setitem(sys.modules, "zenoh_ros2_sdk", None)
    config = Ros2PublishConfig(enabled=True, topic="/t")
    pub = Ros2ImagePublisher(config)
    assert pub.publish(_colorbars_jpeg(32, 24), "image/jpeg") is False


def test_close_is_safe_before_init():
    pub = Ros2ImagePublisher(Ros2PublishConfig(enabled=True, topic="/t"))
    pub.close()  # no publisher yet -> no error

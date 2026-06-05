"""Parse-path guard for the exposure config block.

These tests are deliberately import-light: they touch only ``models`` and
``exposure_params`` (no ``zenoh`` / ``zenoh_ros2_sdk``), so they run as a fast
unit gate. Their real job is to be a regression tripwire for the
build-breaking ``SyntaxError`` that landed on ``main`` via PR #9: both
``models.py`` (unclosed ``ExposureParamsConfig(...)`` ctor) and ``runtime.py``
(unterminated ``self._exposure`` ternary) were *unimportable*, so the
production daemon could not start. Collection of this module alone would have
failed on the broken tree.
"""

from zenoh_dslr_pi_runtime.exposure_params import ExposureParameterServer
from zenoh_dslr_pi_runtime.models import ExposureParamsConfig, PiRuntimeSettings


# ---- config parsing -------------------------------------------------------


def test_exposure_defaults_disabled(tmp_path):
    path = tmp_path / "pi.json"
    path.write_text(
        '{"camera_id": "cam9", "device_id": "id2-rpi4", "capture_backend": {"type": "mock"}}'
    )
    settings = PiRuntimeSettings.from_file(path)
    exp = settings.exposure
    assert isinstance(exp, ExposureParamsConfig)
    assert exp.enabled is False
    assert exp.node_name == "dslr_cam9"  # derived from camera_id
    # the four gphoto2 keys are always present, defaulting to "leave as-is"
    assert exp.params == {
        "shutterspeed": "",
        "aperture": "",
        "iso": "",
        "autoexposuremode": "",
    }


def test_exposure_block_parsed(tmp_path):
    """The exact ctor that was unclosed on main -- asserts the now-closed value."""
    path = tmp_path / "pi.json"
    path.write_text(
        """
        {
          "camera_id": "Canon_EOS_6D",
          "capture_backend": {"type": "mock"},
          "exposure": {
            "enabled": true,
            "node_name": "dslr_studio",
            "router_ip": "10.0.0.9",
            "router_port": 7448,
            "domain_id": 3,
            "params": {"iso": "400", "aperture": "2.8", "autoexposuremode": null}
          }
        }
        """
    )
    settings = PiRuntimeSettings.from_file(path)
    exp = settings.exposure
    assert exp.enabled is True
    assert exp.node_name == "dslr_studio"
    assert exp.router_ip == "10.0.0.9"
    assert exp.router_port == 7448
    assert exp.domain_id == 3
    # supplied params overlay the defaults; null collapses to "" (leave as-is)
    assert exp.params["iso"] == "400"
    assert exp.params["aperture"] == "2.8"
    assert exp.params["autoexposuremode"] == ""
    assert exp.params["shutterspeed"] == ""


def test_exposure_router_falls_back_to_ros2_publish(tmp_path):
    """Omitted exposure router inherits the ros2_publish router (models.py wiring)."""
    path = tmp_path / "pi.json"
    path.write_text(
        """
        {
          "camera_id": "c",
          "capture_backend": {"type": "mock"},
          "ros2_publish": {"router_ip": "192.168.5.5", "router_port": 7450},
          "exposure": {"enabled": true}
        }
        """
    )
    settings = PiRuntimeSettings.from_file(path)
    assert settings.exposure.router_ip == "192.168.5.5"
    assert settings.exposure.router_port == 7450


# ---- enabled=True construction branch (runtime.py:38-42) -------------------


def test_exposure_server_constructs_when_enabled():
    """Exercise the ``exposure.enabled`` true-arm: construct the server.

    This mirrors ``PiDslrRuntime.__init__`` (runtime.py:38), whose ternary's
    true branch was syntactically broken on main. ``ExposureParameterServer``
    is hermetic on init (pico-ros-py is imported lazily in ``start()``), so the
    construction path is unit-testable without a router or the SDK.
    """
    config = ExposureParamsConfig(
        enabled=True,
        node_name="dslr_test",
        params={"iso": "200", "shutterspeed": "1/250"},
    )
    server = ExposureParameterServer(config)
    # The server captures the declared param names up front, before any I/O.
    assert sorted(server._param_names) == ["iso", "shutterspeed"]

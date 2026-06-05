"""Hermetic coverage for the capture backends — the gphoto2-facing service code.

The gphoto2 / command backends shell out to external binaries (a real DSLR, a
shell pipeline). To keep these tests runnable anywhere with no camera and no
network, ``subprocess.run`` is monkeypatched at the module boundary. Everything
else — file selection, encoding inference, metadata assembly, persistence — is
exercised for real against a tmp persistence buffer.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image as PilImage

from zenoh_dslr_pi_runtime import capture_backends
from zenoh_dslr_pi_runtime.capture_backends import (
    CommandCaptureBackend,
    GPhoto2CaptureBackend,
    MockCaptureBackend,
    build_backend,
)
from zenoh_dslr_pi_runtime.models import PiRuntimeSettings


# ---- helpers --------------------------------------------------------------


def _jpeg_bytes(width: int = 12, height: int = 8) -> bytes:
    buf = io.BytesIO()
    PilImage.new("RGB", (width, height), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _settings(tmp_path: Path, backend: dict, **extra) -> PiRuntimeSettings:
    """Build settings from a real config file so parsing is exercised too.

    Persistence is rooted under ``tmp_path`` so captures land in an isolated dir.
    """
    import json

    payload = {
        "camera_model": "Canon EOS 6D",
        "camera_id": "Canon_EOS_6D",
        "capture_backend": backend,
        "persistence": {"enabled": True, "directory": "caps"},
        **extra,
    }
    cfg = tmp_path / "pi.json"
    cfg.write_text(json.dumps(payload))
    return PiRuntimeSettings.from_file(cfg)


# ---- build_backend dispatch ----------------------------------------------


def test_build_backend_dispatch(tmp_path):
    assert isinstance(build_backend(_settings(tmp_path, {"type": "mock"})), MockCaptureBackend)
    assert isinstance(
        build_backend(_settings(tmp_path, {"type": "command", "command": "true"})),
        CommandCaptureBackend,
    )
    assert isinstance(
        build_backend(_settings(tmp_path, {"type": "gphoto2"})), GPhoto2CaptureBackend
    )


def test_build_backend_rejects_unknown(tmp_path):
    with pytest.raises(ValueError, match="unsupported capture backend"):
        build_backend(_settings(tmp_path, {"type": "nope"}))


# ---- mock backend ---------------------------------------------------------


def test_mock_backend_captures_and_persists(tmp_path):
    settings = _settings(tmp_path, {"type": "mock"})
    frame = build_backend(settings).capture()

    assert frame.payload == capture_backends.MOCK_IMAGE_BYTES
    assert frame.encoding == "image/jpeg"  # CaptureBackendConfig default
    assert (frame.width, frame.height) == (1, 1)  # the embedded 1x1 PNG
    assert frame.metadata["camera_id"] == "Canon_EOS_6D"
    assert frame.metadata["camera_model"] == "Canon EOS 6D"
    assert frame.image_key == f"dslr/Canon_EOS_6D/frames/{frame.capture_id}"
    # persistence wrote the bytes to disk and recorded the path
    persisted = Path(frame.metadata["persisted_path"])
    assert persisted.exists()
    assert persisted.read_bytes() == capture_backends.MOCK_IMAGE_BYTES


# ---- command backend ------------------------------------------------------


def test_command_backend_requires_command(tmp_path):
    with pytest.raises(ValueError, match="requires a command"):
        CommandCaptureBackend(
            _settings(tmp_path, {"type": "command"}),
            capture_backends.CaptureBackendConfig(type="command"),
            capture_backends.PersistenceBuffer(_settings(tmp_path, {"type": "mock"}).persistence),
        )


def test_command_backend_runs_and_finalizes(tmp_path, monkeypatch):
    payload = _jpeg_bytes(20, 10)
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(command, 0, stdout=payload, stderr=b"warn!")

    monkeypatch.setattr(capture_backends.subprocess, "run", fake_run)

    settings = _settings(
        tmp_path,
        {"type": "command", "command": "shoot --id {camera_id}", "encoding": "image/jpeg"},
    )
    frame = build_backend(settings).capture()

    # the {camera_id} placeholder was interpolated and the shell pipeline used
    assert seen["command"] == "shoot --id Canon_EOS_6D"
    assert seen["shell"] is True
    assert frame.payload == payload
    assert (frame.width, frame.height) == (20, 10)
    assert frame.metadata["stderr"] == "warn!"
    assert Path(frame.metadata["persisted_path"]).exists()


# ---- gphoto2 backend ------------------------------------------------------


def _fake_gphoto2(downloaded_name: str | None, stdout: str = "", stderr: str = ""):
    """Build a fake ``subprocess.run`` that mimics gphoto2 downloading a file.

    It parses the ``--filename`` template out of the command to learn the temp
    dir gphoto2 was told to write into, then drops ``downloaded_name`` there
    (unless ``None``, simulating a capture that produced no file).
    """

    def fake_run(command, **kwargs):
        target_template = command[command.index("--filename") + 1]
        out_dir = Path(target_template).parent
        if downloaded_name is not None:
            (out_dir / downloaded_name).write_bytes(_jpeg_bytes(16, 9))
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=stderr)

    return fake_run


def test_gphoto2_backend_captures_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(
        capture_backends.subprocess,
        "run",
        _fake_gphoto2("frame.jpg", stdout="New file is in folder", stderr="warn"),
    )
    settings = _settings(tmp_path, {"type": "gphoto2"})
    frame = build_backend(settings).capture()

    assert frame.encoding == "image/jpeg"  # inferred from the .jpg suffix
    assert (frame.width, frame.height) == (16, 9)
    assert frame.metadata["gphoto2_stdout"] == "New file is in folder"
    assert frame.metadata["gphoto2_stderr"] == "warn"
    assert frame.metadata["source_path"].endswith("frame.jpg")
    assert any(p.endswith("frame.jpg") for p in frame.metadata["downloaded_files"])
    assert Path(frame.metadata["persisted_path"]).exists()


def test_gphoto2_backend_builds_command_with_flags(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        out_dir = Path(command[command.index("--filename") + 1]).parent
        (out_dir / "x.jpg").write_bytes(_jpeg_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(capture_backends.subprocess, "run", fake_run)
    settings = _settings(
        tmp_path,
        {
            "type": "gphoto2",
            "port": "usb:001,007",
            "keep_on_camera": True,
            "extra_args": ["--set-config", "iso=100"],
        },
    )
    frame = build_backend(settings).capture()

    cmd = seen["command"]
    assert cmd[0] == "gphoto2"
    assert "--capture-image-and-download" in cmd
    assert cmd[cmd.index("--port") + 1] == "usb:001,007"
    assert "--keep" in cmd
    assert cmd[-2:] == ["--set-config", "iso=100"]
    assert frame.metadata["gphoto2_port"] == "usb:001,007"


def test_gphoto2_backend_applies_exposure_before_capture(tmp_path, monkeypatch):
    """Per-capture exposure is injected as --set-config BEFORE the capture action.

    gphoto2 runs options left-to-right, so a --set-config that lands after
    --capture-image-and-download would have no effect on the frame. Order is the
    contract here, plus the applied values are echoed into metadata.
    """
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        out_dir = Path(command[command.index("--filename") + 1]).parent
        (out_dir / "x.jpg").write_bytes(_jpeg_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(capture_backends.subprocess, "run", fake_run)
    settings = _settings(tmp_path, {"type": "gphoto2", "port": "usb:001,007"})

    frame = build_backend(settings).capture(
        exposure={"shutterspeed": "1/250", "iso": "400", "aperture": ""}
    )

    cmd = seen["command"]
    capture_at = cmd.index("--capture-image-and-download")
    # both non-empty settings present, each as a `key=value` after --set-config
    assert cmd[cmd.index("--set-config") + 1] in {"shutterspeed=1/250", "iso=400"}
    set_pairs = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--set-config"]
    assert set_pairs == ["shutterspeed=1/250", "iso=400"]
    # every --set-config index is before the capture action
    assert all(i < capture_at for i, tok in enumerate(cmd) if tok == "--set-config")
    # the empty aperture is skipped entirely
    assert "aperture=" not in cmd and "aperture" not in " ".join(cmd)
    assert frame.metadata["exposure"] == {"shutterspeed": "1/250", "iso": "400"}


def test_gphoto2_backend_no_exposure_means_no_set_config(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        out_dir = Path(command[command.index("--filename") + 1]).parent
        (out_dir / "x.jpg").write_bytes(_jpeg_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(capture_backends.subprocess, "run", fake_run)
    settings = _settings(tmp_path, {"type": "gphoto2"})

    frame = build_backend(settings).capture()  # no exposure passed

    assert "--set-config" not in seen["command"]
    assert "exposure" not in frame.metadata


def test_gphoto2_backend_raises_when_no_file_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_backends.subprocess, "run", _fake_gphoto2(None))
    settings = _settings(tmp_path, {"type": "gphoto2"})
    with pytest.raises(RuntimeError, match="without downloading a file"):
        build_backend(settings).capture()


# ---- static helpers -------------------------------------------------------


@pytest.mark.parametrize(
    "suffix,expected",
    [
        (".jpg", "image/jpeg"),
        (".JPEG", "image/jpeg"),
        (".png", "image/png"),
        (".webp", "image/webp"),
        (".cr3", "FALLBACK"),
    ],
)
def test_encoding_for_suffix(suffix, expected):
    assert GPhoto2CaptureBackend._encoding_for_suffix(suffix, "FALLBACK") == expected


def test_sort_key_prefers_jpeg_over_raw():
    files = [Path("a.cr3"), Path("b.jpg"), Path("c.png"), Path("d.unknown")]
    ordered = sorted(files, key=GPhoto2CaptureBackend._sort_key_for_download)
    # JPEG first (preferred 0), then PNG (1), unknown (20), raw (10) — by rank
    assert ordered[0] == Path("b.jpg")
    assert ordered[-1] == Path("d.unknown")  # rank 20 sorts after the cr3 rank 10

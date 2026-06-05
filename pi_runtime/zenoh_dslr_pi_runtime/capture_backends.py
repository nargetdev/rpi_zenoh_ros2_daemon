from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import io
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from PIL import Image as PilImage

from .models import CaptureBackendConfig, CaptureResult, PiRuntimeSettings
from .persistence import PersistenceBuffer


MOCK_IMAGE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y3ioAAAAASUVORK5CYII="
)


class CaptureBackend(ABC):
    @abstractmethod
    def capture(self, exposure: dict[str, str] | None = None) -> CaptureResult:
        """Capture a frame.

        ``exposure`` is an optional ``{gphoto2_key: value}`` mapping of camera
        settings to apply for this capture (only the gphoto2 backend uses it;
        other backends ignore it).
        """
        raise NotImplementedError

    def _build_metadata(
        self,
        capture_id: str,
        image_key: str,
        encoding: str,
        width: int,
        height: int,
        persisted_path: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "camera_id": self._settings.camera_id,
            "camera_model": self._settings.camera_model,
            "capture_id": capture_id,
            "image_key": image_key,
            "captured_at_unix": time.time(),
            "width": width,
            "height": height,
            "encoding": encoding,
        }
        if persisted_path:
            metadata["persisted_path"] = persisted_path
        if source_path:
            metadata["source_path"] = source_path
        return metadata

    def _finalize_capture(
        self,
        capture_id: str,
        payload: bytes,
        encoding: str,
        width: int,
        height: int,
        source_path: str | None = None,
    ) -> CaptureResult:
        image_key = f"{self._settings.frame_key_prefix}/{capture_id}"
        metadata = self._build_metadata(
            capture_id=capture_id,
            image_key=image_key,
            encoding=encoding,
            width=width,
            height=height,
            source_path=source_path,
        )
        frame = CaptureResult(
            capture_id=capture_id,
            payload=payload,
            encoding=encoding,
            width=width,
            height=height,
            metadata=metadata,
        )
        persisted_path = self._persistence.persist(frame)
        if persisted_path:
            frame.metadata["persisted_path"] = persisted_path
        return frame

    def _read_dimensions(self, payload: bytes) -> tuple[int, int]:
        try:
            with PilImage.open(io.BytesIO(payload)) as image:
                return image.size
        except Exception:
            return 0, 0


class MockCaptureBackend(CaptureBackend):
    def __init__(self, settings: PiRuntimeSettings, config: CaptureBackendConfig, persistence: PersistenceBuffer) -> None:
        self._settings = settings
        self._config = config
        self._persistence = persistence

    def capture(self, exposure: dict[str, str] | None = None) -> CaptureResult:
        capture_id = uuid.uuid4().hex
        width, height = self._read_dimensions(MOCK_IMAGE_BYTES)
        return self._finalize_capture(
            capture_id=capture_id,
            payload=MOCK_IMAGE_BYTES,
            encoding=self._config.encoding,
            width=width,
            height=height,
        )


class CommandCaptureBackend(CaptureBackend):
    def __init__(self, settings: PiRuntimeSettings, config: CaptureBackendConfig, persistence: PersistenceBuffer) -> None:
        self._settings = settings
        self._config = config
        self._persistence = persistence
        if not self._config.command:
            raise ValueError("command backend requires a command field")

    def capture(self, exposure: dict[str, str] | None = None) -> CaptureResult:
        capture_id = uuid.uuid4().hex
        command = self._config.command.format(
            camera_id=self._settings.camera_id,
            camera_model=self._settings.camera_model,
            capture_id=capture_id,
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
        )
        width, height = self._read_dimensions(completed.stdout)
        frame = self._finalize_capture(
            capture_id=capture_id,
            payload=completed.stdout,
            encoding=self._config.encoding,
            width=width,
            height=height,
        )
        stderr = completed.stderr.decode("utf-8", errors="ignore")
        if stderr:
            frame.metadata["stderr"] = stderr
        return frame


class GPhoto2CaptureBackend(CaptureBackend):
    def __init__(self, settings: PiRuntimeSettings, config: CaptureBackendConfig, persistence: PersistenceBuffer) -> None:
        self._settings = settings
        self._config = config
        self._persistence = persistence

    def capture(self, exposure: dict[str, str] | None = None) -> CaptureResult:
        capture_id = uuid.uuid4().hex
        filename_pattern = self._config.filename_pattern.format(
            camera_id=self._settings.camera_id,
            camera_model=self._settings.camera_model,
            capture_id=capture_id,
        )
        with tempfile.TemporaryDirectory(prefix="zenoh-dslr-") as temp_dir:
            target_template = str(Path(temp_dir) / f"{filename_pattern}.%C")
            command = ["gphoto2"]
            if self._config.port:
                command.extend(["--port", self._config.port])
            # gphoto2 runs actions left-to-right, so any --set-config must come
            # BEFORE --capture-image-and-download to take effect for this frame.
            applied_exposure: dict[str, str] = {}
            for key, value in (exposure or {}).items():
                text = str(value).strip()
                if not text:
                    continue
                command.extend(["--set-config", f"{key}={text}"])
                applied_exposure[key] = text
            command.extend(
                [
                    "--capture-image-and-download",
                    "--force-overwrite",
                    "--filename",
                    target_template,
                ]
            )
            if self._config.keep_on_camera:
                command.append("--keep")
            if self._config.extra_args:
                command.extend(self._config.extra_args)

            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )

            downloaded = sorted(Path(temp_dir).iterdir(), key=self._sort_key_for_download)
            if not downloaded:
                raise RuntimeError("gphoto2 completed without downloading a file")
            source_path = downloaded[0]
            payload = source_path.read_bytes()
            encoding = self._encoding_for_suffix(source_path.suffix, self._config.encoding)
            width, height = self._read_dimensions(payload)
            frame = self._finalize_capture(
                capture_id=capture_id,
                payload=payload,
                encoding=encoding,
                width=width,
                height=height,
                source_path=str(source_path),
            )
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            if stdout:
                frame.metadata["gphoto2_stdout"] = stdout
            if stderr:
                frame.metadata["gphoto2_stderr"] = stderr
            if self._config.port:
                frame.metadata["gphoto2_port"] = self._config.port
            if applied_exposure:
                frame.metadata["exposure"] = applied_exposure
            frame.metadata["downloaded_files"] = [str(path) for path in downloaded]
            return frame

    @staticmethod
    def _encoding_for_suffix(suffix: str, fallback: str) -> str:
        mapping = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        return mapping.get(suffix.lower(), fallback)

    @staticmethod
    def _sort_key_for_download(path: Path) -> tuple[int, str]:
        preferred = {
            ".jpg": 0,
            ".jpeg": 0,
            ".png": 1,
            ".webp": 2,
            ".cr3": 10,
            ".cr2": 10,
            ".raw": 10,
        }
        return (preferred.get(path.suffix.lower(), 20), path.name)


def build_backend(settings: PiRuntimeSettings) -> CaptureBackend:
    persistence = PersistenceBuffer(settings.persistence)
    backend_type = settings.capture_backend.type
    if backend_type == "mock":
        return MockCaptureBackend(settings, settings.capture_backend, persistence)
    if backend_type == "command":
        return CommandCaptureBackend(settings, settings.capture_backend, persistence)
    if backend_type == "gphoto2":
        return GPhoto2CaptureBackend(settings, settings.capture_backend, persistence)
    raise ValueError(f"unsupported capture backend: {backend_type}")

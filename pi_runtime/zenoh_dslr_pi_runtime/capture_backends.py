from __future__ import annotations

from abc import ABC, abstractmethod
import base64
from datetime import datetime
import io
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from PIL import Image as PilImage, ImageDraw, ImageFont

from .models import CaptureBackendConfig, CaptureResult, PiRuntimeSettings
from .persistence import PersistenceBuffer


MOCK_IMAGE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y3ioAAAAASUVORK5CYII="
)


def _synthesize_dated_png(width: int, height: int, date_str: str) -> bytes:
    """Render a deterministic, date-stamped RGB test frame as PNG bytes.

    Unlike the embedded 1x1 ``MOCK_IMAGE_BYTES`` placeholder, this produces a
    real ``width`` x ``height`` image with non-trivial dimensions so downstream
    width/height/encoding/step assertions (native + gateway Image CDR) are
    meaningful. The date string is drawn onto the frame with Pillow's built-in
    bitmap font (no font-file dependency) and reference colored bars are added so
    the frame is visually distinguishable.
    """
    if width <= 0 or height <= 0:
        raise ValueError(
            f"mock_width/mock_height must be positive, got {width}x{height}"
        )
    image = PilImage.new("RGB", (width, height), (32, 32, 40))
    draw = ImageDraw.Draw(image)

    # Reference colored bars across the top so the frame is obviously non-blank.
    bar_colors = [(220, 60, 60), (60, 200, 90), (70, 120, 230), (230, 200, 60)]
    bar_height = max(1, height // 8)
    bar_width = max(1, width // len(bar_colors))
    for index, color in enumerate(bar_colors):
        x0 = index * bar_width
        x1 = width if index == len(bar_colors) - 1 else x0 + bar_width
        draw.rectangle([x0, 0, x1, bar_height], fill=color)

    font = ImageFont.load_default()
    draw.text((8, bar_height + 8), f"CI MOCK {date_str}", fill=(255, 255, 255), font=font)
    draw.text((8, bar_height + 24), f"{width}x{height} rgb8", fill=(200, 200, 200), font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class CaptureBackend(ABC):
    def __init__(self, settings: PiRuntimeSettings, persistence: PersistenceBuffer) -> None:
        self._settings = settings
        self._persistence = persistence

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
        super().__init__(settings, persistence)
        self._config = config

    def capture(self, exposure: dict[str, str] | None = None) -> CaptureResult:
        capture_id = uuid.uuid4().hex
        date_str = datetime.now().strftime("%Y-%m-%d")
        if self._config.mock_synthesize:
            payload = _synthesize_dated_png(
                self._config.mock_width, self._config.mock_height, date_str
            )
        else:
            payload = MOCK_IMAGE_BYTES
        width, height = self._read_dimensions(payload)
        # The synth path *generated* these bytes, so it can validate its own
        # output against the known config dims instead of trusting the lenient
        # _read_dimensions (which returns (0, 0) on any decode failure). This
        # turns a silent Pillow encode/decode mismatch into an immediate,
        # source-local error rather than a confusing downstream CDR dimension
        # mismatch 90s later at the verifier.
        if self._config.mock_synthesize and (width, height) != (
            self._config.mock_width,
            self._config.mock_height,
        ):
            raise RuntimeError(
                f"synthesized mock frame decoded to {width}x{height}, expected "
                f"{self._config.mock_width}x{self._config.mock_height} "
                "(Pillow encode/decode mismatch?)"
            )
        frame = self._finalize_capture(
            capture_id=capture_id,
            payload=payload,
            encoding=self._config.encoding,
            width=width,
            height=height,
        )
        if self._config.mock_synthesize:
            frame.metadata["synthesized_date"] = date_str
        return frame


class CommandCaptureBackend(CaptureBackend):
    def __init__(self, settings: PiRuntimeSettings, config: CaptureBackendConfig, persistence: PersistenceBuffer) -> None:
        super().__init__(settings, persistence)
        self._config = config
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
        super().__init__(settings, persistence)
        self._config = config

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

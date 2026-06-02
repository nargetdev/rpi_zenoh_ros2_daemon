from __future__ import annotations

from pathlib import Path

from .models import CaptureResult, PersistenceConfig


class PersistenceBuffer:
    def __init__(self, config: PersistenceConfig) -> None:
        self._config = config
        self._directory = Path(config.directory)
        if self._config.enabled:
            self._directory.mkdir(parents=True, exist_ok=True)

    def persist(self, frame: CaptureResult) -> str | None:
        if not self._config.enabled:
            return None

        suffix = self._suffix_for_encoding(frame.encoding)
        target = self._directory / f"{frame.capture_id}{suffix}"
        target.write_bytes(frame.payload)
        self._prune()
        return str(target)

    def _prune(self) -> None:
        files = [path for path in self._directory.iterdir() if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime)
        total_bytes = sum(path.stat().st_size for path in files)
        while total_bytes > self._config.max_bytes and files:
            oldest = files.pop(0)
            size = oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            total_bytes -= size

    @staticmethod
    def _suffix_for_encoding(encoding: str) -> str:
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        return mapping.get(encoding, ".bin")

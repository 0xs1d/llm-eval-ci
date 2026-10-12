from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import EvalReport


class JsonReportStore:
    """Small filesystem-backed report history suitable for CI artifacts."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, report: EvalReport) -> Path:
        target = self.directory / f"{report.run_id}.json"
        fd, temporary = tempfile.mkstemp(prefix=f".{report.run_id}-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(report.to_dict(), stream, indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return target

    def load(self, run_id: str) -> dict:
        return json.loads((self.directory / f"{run_id}.json").read_text())

    def latest(self) -> dict | None:
        reports = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        return json.loads(reports[0].read_text()) if reports else None

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from utils.time_utils import now_iso


@dataclass
class ProcessLock:
    path: Path
    acquired: bool = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"pid": os.getpid(), "acquired_at": now_iso()}, handle, ensure_ascii=False, indent=2)
                self.acquired = True
                return True
            except FileExistsError:
                if not self._clear_if_stale():
                    return False

    def release(self) -> None:
        if self.acquired and self.path.exists():
            self.path.unlink(missing_ok=True)
        self.acquired = False

    def _clear_if_stale(self) -> bool:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            self.path.unlink(missing_ok=True)
            return True

        pid = payload.get("pid")
        if not isinstance(pid, int):
            self.path.unlink(missing_ok=True)
            return True

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.path.unlink(missing_ok=True)
            return True
        except PermissionError:
            return False
        return False

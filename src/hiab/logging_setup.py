"""Program log: structured JSON lines on stdout plus a rotating file.

This is the log about the software. What happens inside the world goes to the
database (events, world_log, metrics), never here.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

COMPONENTS = ("worker", "api", "chronicler", "packs", "store", "cli")
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": record.name.removeprefix("hiab."),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"hiab.{component}")


def setup_logging(
    level: str = "INFO",
    component_levels: dict[str, str] | None = None,
    log_dir: Path | None = None,
) -> None:
    root = logging.getLogger("hiab")
    root.handlers.clear()
    root.setLevel(level.upper())
    root.propagate = False

    formatter = JsonFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_dir / "hiab.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        root.addHandler(rotating)

    for component, component_level in sorted((component_levels or {}).items()):
        get_logger(component).setLevel(component_level.upper())

"""Humankind in a Box: a self-hosted idle civilization simulation."""

import os
import subprocess
from pathlib import Path

__version__ = "0.0.1"


def build_commit() -> str:
    """Which code is running: the commit given at image build time, or the git
    checkout this package runs from, or 'unknown'."""
    given = os.environ.get("HIAB_COMMIT", "").strip()
    if given and given != "unknown":
        return given[:12]
    try:
        found = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return found.stdout.strip() or "unknown"

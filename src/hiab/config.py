"""Settings in four layers: defaults < hiab.yaml < HIAB_* environment < command line.

Secrets (API token, LLM key) are never printed: ``Settings.public_dict`` masks them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SECRET_FIELDS = frozenset({"api_token", "llm_key"})

# Environment variable -> settings field. Anything not listed here is HIAB_<FIELD>.
ENV_ALIASES = {"HIAB_DATA": "data_dir", "HIAB_PACE": "pace"}


class ConfigError(Exception):
    """A configuration source is invalid. The message is safe to show to the user."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # System (start only)
    port: int = Field(2222, ge=1, le=65535)
    bind: str = "0.0.0.0"
    data_dir: Path = Path()
    language: Literal["de", "en"] = "de"
    api_token: str | None = None

    # Logging (changeable at runtime later)
    log_level: str = "INFO"
    log_levels: dict[str, str] = Field(default_factory=dict)
    log_to_file: bool = True
    world_log: Literal["chronicle", "decisions", "full"] = "decisions"
    world_log_years: int = Field(50, ge=1)

    # New world (fixed once the world exists)
    seed: int | None = Field(None, ge=0, lt=2**63)
    map_width: int = Field(64, ge=16, le=512)
    map_height: int = Field(64, ge=16, le=512)
    land_share: int = Field(45, ge=5, le=95, description="Percent of tiles that are land")
    packs: list[str] = Field(default_factory=lambda: ["base"])

    # Running world
    pace: float = Field(120.0, gt=0, description="World days (ticks) per real minute")
    autosave_seconds: int = Field(15, ge=2)
    api: bool = True

    # Reserved for later stages; accepted now so config files stay valid.
    interventions: bool = False
    llm_provider: Literal["none", "local", "openai", "claude"] = "none"
    llm_base_url: str | None = None
    llm_key: str | None = None
    llm_model: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hiab.sqlite"

    def public_dict(self) -> dict[str, Any]:
        """Settings as plain data with secrets masked, for logs and (later) the API."""
        out = self.model_dump(mode="json")
        for name in SECRET_FIELDS:
            if out.get(name):
                out[name] = "***"
        return out


def default_data_dir() -> Path:
    """Per-user data folder of the operating system."""
    home = Path.home()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / "hiab"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "hiab"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / "hiab"


def _env_layer(environ: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(environ):
        if not key.startswith("HIAB_"):
            continue
        field = ENV_ALIASES.get(key, key[5:].lower())
        if field not in Settings.model_fields:
            raise ConfigError(f"Unknown environment variable {key}")
        raw = environ[key]
        if field in ("packs",):
            out[field] = [p.strip() for p in raw.split(",") if p.strip()]
        elif field == "log_levels":
            out[field] = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
        elif field == "interventions":
            out[field] = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            out[field] = raw
    return out


def load_settings(
    cli: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    """Merge the four layers. ``cli`` holds only options the user actually passed."""
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    env = _env_layer(dict(os.environ) if environ is None else environ)

    # The data folder decides where hiab.yaml lives, so resolve it first.
    data_dir = Path(cli.get("data_dir") or env.get("data_dir") or default_data_dir())

    file_layer: dict[str, Any] = {}
    config_file = data_dir / "hiab.yaml"
    if config_file.is_file():
        try:
            loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{config_file} is not valid YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"{config_file} must contain a mapping of settings")
        file_layer = loaded

    merged = {**file_layer, **env, **cli, "data_dir": data_dir}
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_input=False)
        )
        raise ConfigError(f"Invalid configuration: {problems}") from exc

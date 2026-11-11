from __future__ import annotations

from pathlib import Path

import pytest

from hiab.config import ConfigError, load_settings


def test_defaults_need_no_configuration(tmp_path: Path) -> None:
    settings = load_settings({"data_dir": str(tmp_path)}, {})
    assert settings.port == 2222
    assert settings.packs == ["base"]
    assert settings.world_log == "decisions"


def test_layers_override_in_order(tmp_path: Path) -> None:
    (tmp_path / "hiab.yaml").write_text("port: 1000\npace: 10\nlanguage: en\n", encoding="utf-8")
    env = {"HIAB_DATA": str(tmp_path), "HIAB_PORT": "2000", "HIAB_PACE": "20", "OTHER": "x"}
    settings = load_settings({"port": 3000}, env)
    assert settings.port == 3000  # command line beats environment
    assert settings.pace == 20  # environment beats file
    assert settings.language == "en"  # file beats default


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="HIAB_NOPE"):
        load_settings({"data_dir": str(tmp_path)}, {"HIAB_NOPE": "1"})
    (tmp_path / "hiab.yaml").write_text("prot: 1000\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="prot"):
        load_settings({"data_dir": str(tmp_path)}, {})


def test_secrets_are_masked(tmp_path: Path) -> None:
    env = {"HIAB_DATA": str(tmp_path), "HIAB_API_TOKEN": "s3cret", "HIAB_LLM_KEY": "k3y"}
    public = load_settings({}, env).public_dict()
    assert public["api_token"] == "***"
    assert public["llm_key"] == "***"
    assert "s3cret" not in str(public)

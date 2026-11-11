from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hiab.packs import PackError, find_pack, load_packs


def test_base_pack_loads() -> None:
    packs = load_packs(["base"])
    assert "game" in packs.stocks()
    assert "flint" in packs.deposits()
    assert packs.rules["drought"].event == "drought"
    for event in packs.events.values():
        assert event.text.de and event.text.en


def copy_base(data_dir: Path) -> Path:
    target = data_dir / "packs" / "base"
    shutil.copytree(find_pack("base", None), target)
    return target


def test_unknown_event_is_rejected_with_a_clear_message(tmp_path: Path) -> None:
    pack = copy_base(tmp_path)
    rules = (pack / "rules.yaml").read_text(encoding="utf-8")
    (pack / "rules.yaml").write_text(
        rules.replace("event: drought", "event: no_such_event"), encoding="utf-8"
    )
    with pytest.raises(
        PackError, match=r"rules\.drought\.event: unknown event type 'no_such_event'"
    ):
        load_packs(["base"], tmp_path)


def test_unknown_fact_and_biome_are_rejected(tmp_path: Path) -> None:
    pack = copy_base(tmp_path)
    rules = (pack / "rules.yaml").read_text(encoding="utf-8")
    (pack / "rules.yaml").write_text(rules.replace("arid: 2.5", "soggy: 2.5"), encoding="utf-8")
    resources = (pack / "resources.yaml").read_text(encoding="utf-8")
    (pack / "resources.yaml").write_text(
        resources.replace("tundra: 250", "jungle: 250"), encoding="utf-8"
    )
    with pytest.raises(PackError) as error:
        load_packs(["base"], tmp_path)
    assert "unknown fact 'soggy'" in str(error.value)
    assert "unknown biome 'jungle'" in str(error.value)


def test_broken_yaml_names_the_file(tmp_path: Path) -> None:
    pack = copy_base(tmp_path)
    (pack / "events.yaml").write_text("drought: [unclosed", encoding="utf-8")
    with pytest.raises(PackError, match=r"events\.yaml"):
        load_packs(["base"], tmp_path)


def test_missing_pack(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="Pack 'nope' not found"):
        load_packs(["nope"], tmp_path)


def test_overrides_change_values_and_checksum(tmp_path: Path) -> None:
    plain = load_packs(["base"], tmp_path)
    local = tmp_path / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(
        "rules.drought.base_chance_per_year: 0.5\n", encoding="utf-8"
    )
    patched = load_packs(["base"], tmp_path)
    assert patched.rules["drought"].base_chance_per_year == 0.5
    assert patched.checksum != plain.checksum
    assert "local" in patched.versions


def test_override_of_missing_path_is_rejected(tmp_path: Path) -> None:
    local = tmp_path / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(
        "rules.volcano.base_chance_per_year: 0.5\n", encoding="utf-8"
    )
    with pytest.raises(PackError, match="does not exist"):
        load_packs(["base"], tmp_path)

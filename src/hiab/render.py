"""Turn language-neutral events into text for display."""

from __future__ import annotations

from typing import Any

from hiab.packs import PackSet
from hiab.sim.engine import DAYS_PER_MONTH, DAYS_PER_YEAR, season_of


def render_event(packs: PackSet, event_type: str, data: dict[str, Any], language: str) -> str:
    definition = packs.events.get(event_type)
    if definition is None:
        return event_type
    values = {key: str(value) for key, value in data.items()}
    if "region" in data:
        values["region"] = f"Region {data['region']}"
    technology = packs.technologies.get(str(data.get("tech")))
    if technology is not None:
        values["tech"] = getattr(technology.name, language)
    text: str = getattr(definition.text, language)
    for key in sorted(values):
        text = text.replace("{" + key + "}", values[key])
    return text


def calendar(tick: int) -> dict[str, Any]:
    year, day = divmod(tick, DAYS_PER_YEAR)
    return {
        "tick": tick,
        "year": year,
        "month": day // DAYS_PER_MONTH + 1,
        "day": day % DAYS_PER_MONTH + 1,
        "season": season_of(tick),
    }


def date_label(tick: int) -> str:
    when = calendar(tick)
    return f"{when['year']:>5}-{when['month']:02}-{when['day']:02}"

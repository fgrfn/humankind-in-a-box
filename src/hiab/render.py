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
    building = packs.buildings.get(str(data.get("building")))
    if building is not None:
        values["building"] = getattr(building.name, language)
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


# What the land is called where a place is named after it. Deposits and other
# resources take their names from the data pack.
LAND_WORDS: dict[str, dict[str, str]] = {
    "river": {"de": "Fluss", "en": "river"},
    "water": {"de": "Wasser", "en": "water"},
    "ocean": {"de": "Meer", "en": "sea"},
    "coast": {"de": "Küste", "en": "coast"},
    "tundra": {"de": "Kältesteppe", "en": "tundra"},
    "taiga": {"de": "Nadelwald", "en": "pine forest"},
    "forest": {"de": "Wald", "en": "forest"},
    "grassland": {"de": "Grasland", "en": "grassland"},
    "steppe": {"de": "Steppe", "en": "steppe"},
    "desert": {"de": "Wüste", "en": "desert"},
    "mountain": {"de": "Berg", "en": "mountain"},
    "marsh": {"de": "Sumpf", "en": "marsh"},
}


def meaning_text(packs: PackSet, meaning: str, language: str) -> str:
    """What a place name means, e.g. "place by the river"."""
    if not meaning:
        return ""
    resource = packs.resources.get(meaning)
    if resource is not None:
        word = getattr(resource.name, language)
    elif meaning in LAND_WORDS:
        word = LAND_WORDS[meaning][language]
    else:
        return ""
    return f"Ort: {word}" if language == "de" else f"place: {word}"

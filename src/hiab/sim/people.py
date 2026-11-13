"""People, families and clans.

Every person exists individually. Clans act as units: they forage around their
camp, go hungry, move on, learn things, split and sometimes settle. Nothing is
scripted; each step is a chance with factors, rolled through ``World.roll``.

A family is the household founded when two people pair up. Children belong to
their mother's family. Clans split along family lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from hiab.logging_setup import get_logger
from hiab.packs import BIOMES, LifeParams

if TYPE_CHECKING:
    from hiab.sim.engine import World

DAYS_PER_MONTH = 30
_watch_log = get_logger("sim.watch")
DAYS_PER_YEAR = 360
TRAITS = ("vigor", "curiosity", "sociability", "craft")
CONSONANTS = "bdfghjklmnprstvz"
VOWELS = "aeiou"
NEVER = -(10**9)


@dataclass(slots=True)
class Person:
    id: int
    name: str
    sex: int  # 0 female, 1 male
    born: int
    mother: int
    father: int
    family: int
    clan: int
    traits: list[int]
    partner: int = 0
    children: int = 0
    last_birth: int = NEVER
    moved: int = 0
    discoveries: int = 0
    died: int | None = None
    cause: str | None = None
    # What the person does this month: a food resource they go out for,
    # "build:<building>", or "" for children. Where they do it, and how many
    # months of their life went into each kind of work.
    activity: str = ""
    target_y: int = -1
    target_x: int = -1
    work: dict[str, int] = field(default_factory=dict)
    # A rare gift that sets someone apart: "leader", "inventor", "warrior" or "healer".
    gift: str = ""


@dataclass(slots=True)
class Clan:
    id: int
    name: str
    y: int
    x: int
    founded: int
    parent: int
    month: int  # month of the year in which the clan's yearly matters are decided
    language: dict[str, str]
    culture: int = 0  # the people the clan belongs to
    leader: int = 0  # the adult the clan follows
    realm: int = 0  # the chiefdom the clan belongs to, 0 for none
    partners: dict[int, int] = field(default_factory=dict)  # trading partner -> since tick
    unused: dict[str, int] = field(default_factory=dict)  # technology -> tick it fell out of use
    # Goods besides food, by resource. And what came and went this year and
    # last, by good ("food" included): [gained, used, traded in, traded out].
    stores: dict[str, int] = field(default_factory=dict)
    flows: dict[str, list[int]] = field(default_factory=dict)
    last_flows: dict[str, list[int]] = field(default_factory=dict)
    members: list[int] = field(default_factory=list)
    techs: dict[str, int] = field(default_factory=dict)
    food: int = 0
    unmet: list[int] = field(default_factory=list)  # percent of need unmet, last 12 months
    arrived: int = 0
    settled: bool = False
    place: int = 0
    famine: bool = False
    dissolved: int | None = None
    faith: int = 0  # what the clan worships, 0 for nothing yet
    sick_until: int = 0  # a fever goes round until this tick
    immune_until: int = 0  # who lived through one is spared until this tick
    sick_dead: int = 0  # who died of the current fever
    herd: int = 0  # head of tame animals


@dataclass(slots=True)
class Realm:
    """A chiefdom: clans that follow the leader of one settled clan, the seat."""

    id: int
    name: str
    founded: int
    seat: int  # clan
    ruler: int  # person
    people: int  # the people of the seat when it was founded
    ended: int | None = None
    # When the chiefdom grew into a land: its clans are villages from then on,
    # sharing stores, faith and fate, and no longer go their own ways.
    land_since: int | None = None


@dataclass(slots=True)
class War:
    """Two chiefdoms at war. The outcome: 'peace', 'conquest' or 'faded'."""

    id: int
    attacker: int  # realm
    defender: int  # realm
    started: int
    ended: int | None = None
    outcome: str = ""
    battles: int = 0
    fallen: int = 0
    winner: int = 0  # realm, for a conquest
    field_y: int = -1  # where the two sides meet
    field_x: int = -1
    last_battle: int = 0  # tick
    last_fallen: int = 0


@dataclass(slots=True)
class Faith:
    """What some clans worship: named in the tongue of the people it began in."""

    id: int
    name: str
    aspect: str
    founded: int
    origin: int  # clan
    people: int
    ended: int | None = None


@dataclass(slots=True)
class Culture:
    """A people: clans of common descent that still speak alike."""

    id: int
    name: str
    parent: int
    founded: int
    origin: int  # the clan it began with
    language: dict[str, str]  # how the people spoke when it formed
    words: dict[str, str] = field(default_factory=dict)  # meaning -> word, made when first needed
    ended: int | None = None
    # The people's ways, 0..100 each: how warlike, how keen on trade, how
    # inventive, how bound to its land, how devout. Drawn when it forms, close to
    # those of the people it came from, so peoples differ and stay themselves.
    ways: dict[str, int] = field(default_factory=dict)


WAYS = ("warlike", "trading", "inventive", "rooted", "devout")


def sound_distance(a: dict[str, str], b: dict[str, str]) -> int:
    """How many sounds two ways of speaking do not share."""
    consonants = len(set(a["c"]) ^ set(b["c"])) // 2
    vowels = len(set(a["v"]) ^ set(b["v"]))
    return consonants + vowels


def _box_sum(grid: np.ndarray, radius: int) -> np.ndarray:
    """Sum of each tile's square neighbourhood, edges clipped."""
    padded = np.pad(grid.astype(np.int64), radius + 1)
    cumulative = padded.cumsum(axis=0).cumsum(axis=1)
    size = 2 * radius + 1
    return (
        cumulative[size:, size:]
        - cumulative[:-size, size:]
        - cumulative[size:, :-size]
        + cumulative[:-size, :-size]
    )[: grid.shape[0], : grid.shape[1]]


class Society:
    def __init__(self, world: World, params: LifeParams) -> None:
        self.world = world
        self.p = params
        self.persons: dict[int, Person] = {}
        self.clans: dict[int, Clan] = {}
        self.places: dict[int, dict[str, Any]] = {}
        self.by_month: dict[int, list[int]] = {month: [] for month in range(12)}
        self.next_person = 1
        self.next_clan = 1
        self.next_family = 1
        self.next_place = 1
        self.next_building = 1
        self.extinct = False
        self.steps = np.zeros((world.map.height, world.map.width), dtype=np.int32)
        # Which clan holds each tile (0: nobody), and the people that clan belongs to.
        self.territory = np.zeros((world.map.height, world.map.width), dtype=np.int32)
        self.land_people = np.zeros((world.map.height, world.map.width), dtype=np.int32)
        self.dirty_persons: set[int] = set()
        self.dirty_clans: set[int] = set()
        self.dirty_places: set[int] = set()
        self.cultures: dict[int, Culture] = {}
        self.realms: dict[int, Realm] = {}
        self.next_realm = 1
        self.faiths: dict[int, Faith] = {}
        self.next_faith = 1
        self.dirty_faiths: set[int] = set()
        self.wars: dict[int, War] = {}
        self.next_war = 1
        self.dirty_wars: set[int] = set()
        self.dirty_realms: set[int] = set()
        self.next_culture = 1
        self.dirty_cultures: set[int] = set()
        self.new_discoveries: list[tuple[int, str, int, int, str]] = []
        self.forgotten: list[tuple[int, str, int]] = []  # clan, technology, tick
        self.new_links: list[tuple[int, int, int]] = []  # clan, clan, since tick
        self.ended_links: list[tuple[int, int, int]] = []  # clan, clan, end tick
        self.food_ids = world.packs.foods()
        self.campable = ~world.map.water & ~world.map.river
        self.landmass, self.landmass_size = self.label_landmasses()
        self.landed: set[int] = set()  # landmasses anyone has ever camped on
        # Answers that depend only on the fixed map, per camp tile.
        self._goods_at: dict[tuple[int, int], list[str]] = {}
        self._fixed_points: dict[str, tuple[int, int]] = {}  # diagnostics, see watch_fixed_points
        self._grows_at: dict[tuple[str, int, int], bool] = {}
        self._effects: dict[int, tuple[dict[str, int], float, int, int]] = {}
        self._labour: dict[int, int] = {}
        self.gifts: dict[int, set[str]] = {}
        self.retired: dict[int, Clan] = {}  # clans dissolved since the last save
        self.dead: dict[int, Person] = {}  # people who died since the last save
        self.vanished: set[int] = set()  # ruins that disappeared since the last save
        self.good_ids = sorted(
            rid
            for rid, resource in world.packs.resources.items()
            if resource.gather_per_worker > 0 and resource.food_value == 0
        )
        self._effort: dict[int, int] = {}  # this month's building work per clan

    # ---- small helpers --------------------------------------------------

    def quiet(self, low: int, high: int) -> int:
        """Cosmetic draw (names, traits, days). Deterministic but not logged."""
        return int(self.world.streams.get("people").integers(low, high + 1))

    def age(self, person: Person) -> int:
        return (self.world.tick - person.born) // DAYS_PER_YEAR

    def adults(self, clan: Clan) -> list[Person]:
        # Born on or before this day: grown up. The same as age() >= adult_age.
        cutoff = self.world.tick - self.p.adult_age * DAYS_PER_YEAR
        persons = self.persons
        members = map(persons.__getitem__, clan.members)
        return [person for person in members if person.born <= cutoff]

    def living(self) -> int:
        return sum(len(self.clans[cid].members) for cid in self.clans)

    def radius(self, clan: Clan) -> int:
        """How far around its camp a clan gathers. Settled people range a little further."""
        return self.p.forage_radius + (self.p.settled_forage_bonus if clan.settled else 0)

    def effects(self, clan: Clan) -> tuple[dict[str, int], float, int, int]:
        """Harvest percent per food, mortality factor, storage months and how many
        adults the clan can hold together before it splits."""
        cached = self._effects.get(clan.id)
        if cached is not None:
            return cached
        packs = self.world.packs
        harvest = {rid: packs.resources[rid].harvest_base_percent for rid in self.food_ids}
        mortality = 1.0
        storage = self.p.storage_months
        together = self.p.clan_split_adults
        labour = 0
        for tech_id in sorted(clan.techs):
            tech = packs.technologies.get(tech_id)
            if tech is None:
                continue
            for rid in sorted(tech.effects.harvest_percent):
                if rid in harvest:
                    harvest[rid] += tech.effects.harvest_percent[rid]
            mortality = mortality * tech.effects.mortality_percent / 100
            storage += tech.effects.storage_months
            together += tech.effects.group_adults
            labour += tech.effects.labour_percent
        if clan.settled:
            seen: set[str] = set()
            for building in self.places[clan.place]["buildings"]:
                definition = packs.buildings.get(building["type"])
                if building["state"] != "standing" or definition is None:
                    continue
                storage += definition.storage_months
                if building["type"] not in seen:
                    seen.add(building["type"])
                    mortality = mortality * definition.mortality_percent / 100
        result = (harvest, mortality, storage, together)
        self._effects[clan.id] = result
        self._labour[clan.id] = labour
        return result

    def labour(self, clan: Clan) -> int:
        """Percent more food a worker brings in, from what the clan knows."""
        if clan.id not in self._effects or clan.id not in self._labour:
            self._effects.pop(clan.id, None)
            self.effects(clan)
        return self._labour[clan.id]

    def unmet_average(self, clan: Clan) -> int:
        return sum(clan.unmet) // len(clan.unmet) if clan.unmet else 0

    # ---- names ----------------------------------------------------------

    def new_language(self) -> dict[str, str]:
        consonants = list(CONSONANTS)
        chosen = ""
        for _ in range(8):
            chosen += consonants.pop(self.quiet(0, len(consonants) - 1))
        vowels = list(VOWELS)
        vowel_set = ""
        for _ in range(self.quiet(3, 4)):
            vowel_set += vowels.pop(self.quiet(0, len(vowels) - 1))
        return {"c": chosen, "v": vowel_set, "end": chosen[:3]}

    def drift_language(self, language: dict[str, str]) -> dict[str, str]:
        unused = [c for c in CONSONANTS if c not in language["c"]]
        index = self.quiet(0, len(language["c"]) - 1)
        replacement = unused[self.quiet(0, len(unused) - 1)]
        consonants = language["c"][:index] + replacement + language["c"][index + 1 :]
        return {"c": consonants, "v": language["v"], "end": consonants[:3]}

    def make_name(self, language: dict[str, str], sex: int | None = None) -> str:
        consonants, vowels, endings = language["c"], language["v"], language["end"]
        word = ""
        for _ in range(self.quiet(2, 3)):
            word += consonants[self.quiet(0, len(consonants) - 1)]
            word += vowels[self.quiet(0, len(vowels) - 1)]
        if sex == 1 or (sex is None and self.quiet(0, 1) == 1):
            word += endings[self.quiet(0, len(endings) - 1)]
        return word.capitalize()

    # ---- creation -------------------------------------------------------

    def add_person(
        self,
        clan: Clan,
        sex: int,
        born: int,
        mother: int,
        father: int,
        family: int,
        traits: list[int],
    ) -> Person:
        person = Person(
            id=self.next_person,
            name=self.make_name(clan.language, sex),
            sex=sex,
            born=born,
            mother=mother,
            father=father,
            family=family,
            clan=clan.id,
            traits=traits,
        )
        self.next_person += 1
        self.persons[person.id] = person
        clan.members.append(person.id)
        self.by_month[(born // DAYS_PER_MONTH) % 12].append(person.id)
        self.dirty_persons.add(person.id)
        return person

    def add_culture(self, clan: Clan, parent: int) -> Culture:
        endings = self.place_endings(clan.language)
        culture = Culture(
            id=self.next_culture,
            name=self.make_name(clan.language, sex=0) + endings[self.quiet(0, len(endings) - 1)],
            parent=parent,
            founded=self.world.tick,
            origin=clan.id,
            language=dict(clan.language),
        )
        before = self.cultures.get(parent)
        for way in WAYS:
            if before is not None and way in before.ways:
                drift = self.world.draw_int(f"people_ways.{way}", -15, 15)
                culture.ways[way] = max(0, min(100, before.ways[way] + drift))
            else:
                culture.ways[way] = self.world.draw_int(f"people_ways.{way}", 15, 85)
        self.next_culture += 1
        self.cultures[culture.id] = culture
        self.dirty_cultures.add(culture.id)
        clan.culture = culture.id
        self.dirty_clans.add(clan.id)
        return culture

    def way(self, clan: Clan, way: str) -> float:
        """How strongly the clan's people leans one way: 0.4 for not at all, 1.6 for very."""
        culture = self.cultures.get(clan.culture)
        value = culture.ways.get(way, 50) if culture is not None else 50
        return 0.4 + 1.2 * value / 100

    @staticmethod
    def place_endings(language: dict[str, str]) -> list[str]:
        """The endings a people gives its own name and its places. Follows from its sounds."""
        c, v = language["c"], language["v"]
        return [v[0] + c[0], v[-1] + c[1], v[0] + c[2] + v[-1]]

    def word(self, culture: Culture, meaning: str) -> str:
        """The people's word for something. Coined when first needed, then kept."""
        if meaning not in culture.words:
            culture.words[meaning] = self.make_name(culture.language, sex=0)
            self.dirty_cultures.add(culture.id)
        return culture.words[meaning]

    def place_meaning(self, y: int, x: int) -> str:
        """What a place is named after: what is found there, or the land itself."""
        world = self.world
        found = int(world.map.deposit[y, x])
        if found >= 0:
            return str(world.map.deposit_ids[found])
        if world.map.river[y, x]:
            return "river"
        area = self.window(y, x, 1)
        if world.map.water[area].any():
            return "water"
        return BIOMES[int(world.map.biome[y, x])]

    def place_name(self, clan: Clan) -> tuple[str, str]:
        culture = self.cultures[clan.culture]
        meaning = self.place_meaning(clan.y, clan.x)
        endings = self.place_endings(culture.language)
        taken = {place["name"] for place in self.places.values()}
        stem = self.word(culture, meaning)
        for ending in endings:
            if stem + ending not in taken:
                return stem + ending, meaning
        # Every plain form is taken: tell it apart by who founded it.
        return f"{stem}{endings[0]} {clan.name}", meaning

    def label_landmasses(self) -> tuple[np.ndarray, dict[int, int]]:
        """Number each piece of land cut off from the others by the sea, in
        reading order, and count its tiles. Rivers can be forded."""
        land = ~self.world.map.water
        height, width = land.shape
        label = np.zeros(land.shape, dtype=np.int32)
        sizes: dict[int, int] = {}
        flat_land = land.ravel().tolist()
        flat = label.ravel()
        for start in range(height * width):
            if not flat_land[start] or flat[start]:
                continue
            number = len(sizes) + 1
            flat[start] = number
            stack = [start]
            count = 0
            while stack:
                index = stack.pop()
                count += 1
                y, x = divmod(index, width)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < height and 0 <= nx < width:
                            other = ny * width + nx
                            if flat_land[other] and not flat[other]:
                                flat[other] = number
                                stack.append(other)
            sizes[number] = count
        return flat.reshape(land.shape), sizes

    def sea_reach(self, clan: Clan) -> int:
        """How far over open water the clan can take its people and goods."""
        packs = self.world.packs
        return max(
            (
                packs.technologies[t].effects.sea_reach
                for t in sorted(clan.techs)
                if t in packs.technologies
            ),
            default=0,
        )

    def arrive(self, clan: Clan, crossed: bool) -> None:
        """Note where the clan now camps; the first landing on a new land is history."""
        mass = int(self.landmass[clan.y, clan.x])
        if not mass or mass in self.landed:
            return
        self.landed.add(mass)
        if not crossed:
            return
        self.world.count("seafaring.new_lands")
        self.world.emit(
            "new_land_reached",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "tiles": self.landmass_size.get(mass, 0),
            },
        )

    def add_clan(
        self, y: int, x: int, parent: int, language: dict[str, str], culture: int = 0
    ) -> Clan:
        clan = Clan(
            id=self.next_clan,
            name=self.make_name(language),
            y=y,
            x=x,
            founded=self.world.tick,
            parent=parent,
            month=self.quiet(0, 11),
            language=language,
            culture=culture,
            arrived=self.world.tick,
        )
        self.next_clan += 1
        self.clans[clan.id] = clan
        self.dirty_clans.add(clan.id)
        parent_clan = self.clans.get(parent)
        crossed = parent_clan is not None and int(self.landmass[y, x]) != int(
            self.landmass[parent_clan.y, parent_clan.x]
        )
        self.arrive(clan, crossed)
        return clan

    def found(self) -> None:
        """Place the first peoples, each on a good spot far from the others."""
        world = self.world
        potential = np.zeros((world.map.height, world.map.width), dtype=np.int64)
        for rid in self.food_ids:
            resource = world.packs.resources[rid]
            potential += (
                world.capacity[rid].astype(np.int64)
                * resource.harvest_base_percent
                * resource.food_value
            )
        score = _box_sum(potential, self.p.forage_radius)
        mild = (world.map.temperature >= 80) & (world.map.temperature <= 230)
        score = np.where(self.campable, score, -1)
        score = np.where(mild, score, score // 3)
        order = np.argsort(-score, axis=None, kind="stable")
        positive = int((score > 0).sum())
        # The best quarter of the habitable land: room enough to spread out.
        good = order[: max(20, positive // 4)]
        good = good[score.ravel()[good] > 0]
        # Each people begins on one of the best spots that lies far from the
        # others. Where there is not enough room, they may begin closer.
        sites: list[tuple[int, int]] = []
        apart = max(world.map.width, world.map.height) // 3
        for number in range(self.p.start_peoples):
            while True:
                free = [
                    int(index)
                    for index in good
                    if all(
                        max(
                            abs(int(index) // world.map.width - y),
                            abs(int(index) % world.map.width - x),
                        )
                        >= apart
                        for y, x in sites
                    )
                ][:20]
                if free or apart <= 2:
                    break
                apart = apart * 2 // 3
            if not free:
                break
            pick = free[world.draw_int(f"start_site.{number}", 0, len(free) - 1)]
            sites.append(divmod(pick, world.map.width))
        for y, x in sites:
            self.found_people(y, x)

    def found_people(self, y: int, x: int) -> None:
        """One starting people: a few families with a speech of their own."""
        world = self.world
        clan = self.add_clan(y, x, 0, self.new_language())
        culture = self.add_culture(clan, 0)
        for tech_id in sorted(self.p.start_technologies):
            if tech_id in world.packs.technologies:
                self.learn(clan, tech_id, 0, "known")
        for _ in range(self.p.start_families):
            family = self.next_family
            self.next_family += 1
            couple = []
            for sex in (0, 1):
                born = -self.quiet(17, 28) * DAYS_PER_YEAR - self.quiet(0, DAYS_PER_YEAR - 1)
                traits = [self.quiet(30, 70) for _ in TRAITS]
                couple.append(self.add_person(clan, sex, born, 0, 0, family, traits))
            couple[0].partner, couple[1].partner = couple[1].id, couple[0].id
            for _ in range(self.quiet(0, 2)):
                self.birth(
                    couple[0], couple[1], clan, -self.quiet(0, 8 * DAYS_PER_YEAR), quiet=True
                )
        world.emit(
            "humankind_begins",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "people": culture.name,
                "people_id": culture.id,
                "y": y,
                "x": x,
            },
        )

    def birth(
        self, mother: Person, father: Person, clan: Clan, born: int, quiet: bool = False
    ) -> Person:
        traits = [
            max(0, min(100, (mother.traits[i] + father.traits[i]) // 2 + self.quiet(-8, 8)))
            for i in range(len(TRAITS))
        ]
        child = self.add_person(
            clan, self.quiet(0, 1), born, mother.id, father.id, mother.family, traits
        )
        for parent in (mother, father):
            parent.children += 1
            self.dirty_persons.add(parent.id)
        mother.last_birth = born
        if not quiet:
            self.world.count("people.births")
            self.world.emit(
                "birth",
                data={
                    "name": child.name,
                    "person": child.id,
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "mother": mother.id,
                    "father": father.id,
                },
            )
        return child

    # ---- the month ------------------------------------------------------

    def month(self, month: int) -> None:
        if self.extinct:
            return
        if month == 0:
            self.new_year()
        for clan_id in sorted(self.clans):
            clan = self.clans.get(clan_id)
            if clan is not None:
                self.forage(clan)
                if clan.settled:
                    self.build(clan)
        for person_id in list(self.by_month[month]):
            person = self.persons.get(person_id)
            if person is not None and person.died is None:
                self.person_year(person)
        for clan_id in sorted(self.clans):
            clan = self.clans.get(clan_id)
            if clan is None:
                continue
            if clan.month == month and self.world.tick > clan.founded:
                self.clan_year(clan)
            if clan.id in self.clans:
                self.maybe_migrate(clan, month)
        if not self.clans and not self.extinct:
            self.extinct = True
            self.world.emit("humankind_extinct")

    # ---- food -----------------------------------------------------------

    def window(self, y: int, x: int, radius: int) -> tuple[slice, slice]:
        world_map = self.world.map
        return (
            slice(max(0, y - radius), min(world_map.height, y + radius + 1)),
            slice(max(0, x - radius), min(world_map.width, x + radius + 1)),
        )

    def monthly_need(self, clan: Clan) -> int:
        p = self.p
        adults = len(self.adults(clan))
        children = len(clan.members) - adults
        return (
            (adults * 100 + children * p.child_need_percent) * p.food_need_per_person_month // 100
        )

    def forage(self, clan: Clan) -> None:
        world, p = self.world, self.p
        need = self.monthly_need(clan)
        if need <= 0:
            return
        harvest_percent, _mortality, storage_months, _together = self.effects(clan)
        capacity = need * storage_months
        _builders, foragers = self.crews(clan)
        # A strong forager brings home more than a weak one.
        strength = sum(50 + person.traits[0] for person in foragers)
        want = min(
            need + max(0, capacity - clan.food),
            strength * p.harvest_per_adult_month * (100 + self.labour(clan)) // 10000,
        )
        area = self.window(clan.y, clan.x, self.radius(clan))

        raws: dict[str, np.ndarray] = {}
        foods: dict[str, int] = {}
        # On land another people holds, strangers get less: they are watched and driven off.
        held_by = self.land_people[area]
        foreign = (held_by != 0) & (held_by != clan.culture)
        any_foreign = bool(foreign.any())
        for rid in self.food_ids:
            percent = harvest_percent[rid]
            if percent <= 0:
                continue
            raw = world.stocks[rid][area].astype(np.int64) * p.harvest_share_percent // 100
            if any_foreign:
                raw = np.where(foreign, raw * p.foreign_harvest_percent // 100, raw)
            amount = int(raw.sum()) * percent // 100 * world.packs.resources[rid].food_value
            if amount > 0:
                raws[rid], foods[rid] = raw, amount
        total = sum(foods.values())
        take_total = min(want, total)
        gathered = 0
        takes: dict[str, int] = {}
        for rid in sorted(foods):
            take = take_total * foods[rid] // total
            if take <= 0:
                continue
            reduction = raws[rid] * take // foods[rid]
            world.stocks[rid][area] = (world.stocks[rid][area] - reduction).astype(np.int32)
            gathered += take
            takes[rid] = take
            world.count(f"food.{rid}.gathered", take)
        self.send_out(clan, foragers, takes or foods, raws, area)

        clan.food += gathered
        self.flow(clan, "food", 0, gathered)
        self.tend_herd(clan, need)
        if clan.food < need:
            # Trading partners with more than they need this month help out.
            helpers = sorted(set(clan.partners) | set(self.realm_members(clan)))
            for partner_id in helpers:
                partner = self.clans.get(partner_id)
                if partner is None:
                    continue
                spare = partner.food - self.monthly_need(partner)
                given = min(spare, need - clan.food)
                if given <= 0:
                    continue
                partner.food -= given
                clan.food += given
                self.flow(clan, "food", 2, given)
                self.flow(partner, "food", 3, given)
                world.count("trade.food", given)
                if clan.food >= need:
                    break
        eaten = min(clan.food, need)
        spoiled = max(0, clan.food - eaten - capacity)  # what there is no room to keep
        clan.food = clan.food - eaten - spoiled
        self.flow(clan, "food", 1, eaten + spoiled)
        clan.unmet.append(100 - eaten * 100 // need)
        if len(clan.unmet) > 12:
            del clan.unmet[0]
        world.count("food.eaten", eaten)
        world.count("food.needed", need)

        starving = self.unmet_average(clan) >= 25
        if starving and not clan.famine:
            world.emit("famine", data={"clan": clan.name, "clan_id": clan.id})
        clan.famine = starving

    # ---- herds -----------------------------------------------------------

    def keeps_herds(self, clan: Clan) -> bool:
        packs = self.world.packs
        return any(
            packs.technologies[t].effects.keeps_herds
            for t in sorted(clan.techs)
            if t in packs.technologies
        )

    def pasture(self, clan: Clan) -> tuple[tuple[slice, slice], int]:
        """The grazing land around the camp and how much grass it holds."""
        area = self.window(clan.y, clan.x, self.radius(clan) + 1)
        grass = self.world.stocks[self.p.herd_grazes][area]
        return area, int(grass.astype(np.int64).sum())

    def herders(self, clan: Clan, adults: list[Person]) -> list[Person]:
        """One adult in so many head goes out with the animals to the best grass."""
        if clan.herd <= 0 or len(adults) < 2:
            return adults
        count = min(len(adults) // 2, -(-clan.herd // self.p.herd_heads_per_herder))
        area, _grass = self.pasture(clan)
        grass = self.world.stocks[self.p.herd_grazes][area]
        flat = int(np.argmax(grass))  # first maximum: lowest y, then lowest x
        y, x = divmod(flat, grass.shape[1])
        y, x = y + area[0].start, x + area[1].start
        chosen = sorted(adults, key=lambda person: (-person.traits[0], person.id))[:count]
        self.set_work(chosen, self.p.herd_grazes, y, x)
        self.walk(clan.y, clan.x, y, x, len(chosen))
        taken = {person.id for person in chosen}
        return [person for person in adults if person.id not in taken]

    def tend_herd(self, clan: Clan, need: int) -> None:
        """The animals graze, give food, starve where grass is short, and are
        slaughtered when the people go hungry."""
        world, p = self.world, self.p
        if clan.herd <= 0:
            return
        if not self.keeps_herds(clan):
            # Nobody left who knows how to keep them: the animals run off.
            world.count("herds.scattered", clan.herd)
            clan.herd = 0
            self.dirty_clans.add(clan.id)
            return
        area, grass = self.pasture(clan)
        want = clan.herd * p.herd_graze_per_head_month
        eaten = min(want, grass)
        if eaten > 0:
            stock = world.stocks[p.herd_grazes][area].astype(np.int64)
            world.stocks[p.herd_grazes][area] = (stock - stock * eaten // grass).astype(np.int32)
        fed = eaten * 100 // want
        food = clan.herd * p.herd_food_per_head_month * fed // 100
        if food:
            clan.food += food
            self.flow(clan, "food", 0, food)
            world.count("food.herds.gathered", food)
        if fed < 50:
            # Not enough grass: the weakest animals die.
            lost = max(1, clan.herd * (50 - fed) // 500)
            clan.herd = max(0, clan.herd - lost)
            world.count("herds.starved", lost)
        if clan.food < need and p.herd_meat_per_head > 0:
            # Only so many a month, and never the breeding stock.
            spare = clan.herd * p.herd_slaughter_percent_per_month // 100
            killed = min(spare, -(-(need - clan.food) // p.herd_meat_per_head))
            if killed > 0:
                clan.herd -= killed
                meat = killed * p.herd_meat_per_head
                clan.food += meat
                self.flow(clan, "food", 0, meat)
                world.count("herds.slaughtered", killed)
        self.dirty_clans.add(clan.id)

    def herd_year(self, clan: Clan) -> None:
        """Young ones each year, as many as the grass around allows."""
        world, p = self.world, self.p
        if not self.keeps_herds(clan) or clan.herd <= 0:
            return
        _area, grass = self.pasture(clan)
        room = grass // (p.herd_graze_per_head_month * 3)  # what the grass would carry
        if clan.herd >= room:
            return
        born = max(1, clan.herd * p.herd_growth_percent_per_year // 100)
        clan.herd = min(room, clan.herd + born)
        self.dirty_clans.add(clan.id)
        world.count("herds.born", born)

    def crews(self, clan: Clan) -> tuple[list[Person], list[Person]]:
        """Who builds and who goes out for food this month.

        Children do neither. With an open construction site and enough to eat,
        a share of the adults builds, the most skilful first. The rest forage.
        """
        adults = sorted(self.adults(clan), key=lambda person: person.id)
        grown = {person.id for person in adults}
        for person_id in clan.members:
            person = self.persons[person_id]
            if person.activity and person_id not in grown:
                person.activity, person.target_y, person.target_x = "", -1, -1
                self.dirty_persons.add(person.id)
        self._effort.pop(clan.id, None)
        site = None
        if clan.settled:
            place = self.places[clan.place]
            site = next((b for b in place["buildings"] if b["state"] == "site"), None)
        hungry = (clan.unmet[-1] if clan.unmet else 0) >= 20
        adults = self.nurse(clan, adults)
        adults = self.rites(clan, adults)
        adults = self.muster(clan, adults)
        adults = self.herders(clan, adults)
        adults = self.fetch_goods(clan, adults)
        if site is None or hungry or len(adults) < 2:
            return [], adults
        count = max(1, len(adults) * self.p.builders_share_percent // 100)
        skilled = sorted(adults, key=lambda person: (-person.traits[3], person.id))
        builders = sorted(skilled[:count], key=lambda person: person.id)
        chosen = {person.id for person in builders}
        self._effort[clan.id] = max(1, sum(50 + person.traits[3] for person in builders) // 100)
        self.set_work(builders, f"build:{site['type']}", site["y"], site["x"])
        self.walk(clan.y, clan.x, site["y"], site["x"], len(builders))
        return builders, [person for person in adults if person.id not in chosen]

    def flow(self, clan: Clan, good: str, column: int, amount: int) -> None:
        """Book what came or went: 0 gained, 1 used, 2 traded in, 3 traded out."""
        if amount > 0:
            clan.flows.setdefault(good, [0, 0, 0, 0])[column] += amount

    def room(self, clan: Clan) -> int:
        """How much of each good a clan can keep: by heads, and by what it has built for storing."""
        units = self.p.store_per_adult * len(self.adults(clan))
        if clan.settled:
            buildings = self.world.packs.buildings
            for building in self.places[clan.place]["buildings"]:
                if building["state"] == "standing" and building["type"] in buildings:
                    units += buildings[building["type"]].storage_units
        return units

    def fetch_goods(self, clan: Clan, adults: list[Person]) -> list[Person]:
        """When nobody is hungry, some adults go out for wood and for what can be dug up.

        They fetch what the clan has least of, as much as there is room for.
        Returns the adults who are left for building and foraging.
        """
        world, p = self.world, self.p
        if (clan.unmet[-1] if clan.unmet else 0) >= 10 or len(adults) < 4:
            return adults
        count = len(adults) * p.gatherers_share_percent // 100
        if count <= 0:
            return adults
        room = self.room(clan)
        area = self.window(clan.y, clan.x, self.radius(clan))
        found = set(self.goods(clan))
        wanted: list[tuple[int, str]] = []
        for rid in self.good_ids:
            resource = world.packs.resources[rid]
            if any(tech not in clan.techs for tech in resource.gather_requires):
                continue
            have = clan.stores.get(rid, 0)
            if have >= room:
                continue
            if resource.kind == "deposit":
                if rid not in found:
                    continue
            elif int(world.stocks[rid][area].sum()) <= 0:
                continue
            wanted.append((have, rid))
        if not wanted:
            return adults
        wanted.sort()
        crews: dict[str, list[Person]] = {}
        going = adults[-count:]  # the youngest adults fetch and carry
        for index, person in enumerate(going):
            crews.setdefault(wanted[index % len(wanted)][1], []).append(person)
        for rid in sorted(crews):
            crew = crews[rid]
            resource = world.packs.resources[rid]
            amount = min(len(crew) * resource.gather_per_worker, room - clan.stores.get(rid, 0))
            if resource.kind == "deposit":
                index = world.map.deposit_ids.index(rid)
                wide = self.window(clan.y, clan.x, p.forage_radius + 2)
                ys, xs = np.nonzero(world.map.deposit[wide] == index)
                gaps = np.maximum(
                    np.abs(ys + wide[0].start - clan.y), np.abs(xs + wide[1].start - clan.x)
                )
                nearest = int(np.argmin(gaps))
                y, x = int(ys[nearest]) + wide[0].start, int(xs[nearest]) + wide[1].start
            else:
                stock = world.stocks[rid][area].astype(np.int64)
                amount = min(amount, int(stock.sum()) // 4)  # never strip the land bare
                # Taken where there is most, tile by tile. Spread over all tiles in
                # proportion, a small crew's share rounds down to nothing.
                flat = stock.ravel()
                taken = np.zeros_like(flat)
                left = amount
                for index in np.argsort(-flat, kind="stable").tolist():
                    if left <= 0:
                        break
                    part = min(left, int(flat[index]) // 2)
                    taken[index] = part
                    left -= part
                world.stocks[rid][area] = (stock - taken.reshape(stock.shape)).astype(np.int32)
                amount -= left
                ty, tx = divmod(int(np.argmax(stock)), stock.shape[1])
                y, x = area[0].start + ty, area[1].start + tx
            clan.stores[rid] = clan.stores.get(rid, 0) + amount
            self.flow(clan, rid, 0, amount)
            world.count(f"goods.{rid}.gathered", amount)
            self.set_work(crew, rid, y, x)
            self.walk(clan.y, clan.x, y, x, len(crew))
        self.dirty_clans.add(clan.id)
        gone = {person.id for person in going}
        return [person for person in adults if person.id not in gone]

    def muster(self, clan: Clan, adults: list[Person]) -> list[Person]:
        """At war, a share of the men of fighting age goes to the field. The rest stay."""
        if not clan.realm:
            return adults
        wars = [w for w in self.at_war(clan.realm) if w.field_y >= 0]
        if not wars:
            return adults
        war = wars[0]
        if max(abs(clan.y - war.field_y), abs(clan.x - war.field_x)) > self.p.war_reach:
            return adults
        men = [a for a in adults if a.sex == 1 and self.age(a) <= 45]
        count = len(men) * self.p.war_fighters_percent // 100
        if count == 0:
            return adults
        fighters = sorted(men, key=lambda a: (-a.traits[0], a.id))[:count]
        enemy = war.defender if war.attacker == clan.realm else war.attacker
        self.set_work(fighters, f"fight:{enemy}", war.field_y, war.field_x)
        self.walk(clan.y, clan.x, war.field_y, war.field_x, len(fighters))
        chosen = {a.id for a in fighters}
        return [a for a in adults if a.id not in chosen]

    def set_work(self, people: list[Person], activity: str, y: int, x: int) -> None:
        kind = activity.split(":", 1)[0]
        for person in people:
            person.activity, person.target_y, person.target_x = activity, y, x
            person.work[kind] = person.work.get(kind, 0) + 1
            self.dirty_persons.add(person.id)
        if people:
            self.world.count(f"work.{kind}", len(people))

    def send_out(
        self,
        clan: Clan,
        foragers: list[Person],
        shares: dict[str, int],
        raws: dict[str, np.ndarray],
        area: tuple[slice, slice],
    ) -> None:
        """Give every forager a food to go out for, in proportion to what each food yields.

        Each group walks to the tile where its food is richest. The footsteps become paths.
        """
        if not foragers:
            return
        foods = [rid for rid in sorted(shares) if shares[rid] > 0 and rid in raws]
        if not foods:
            self.set_work(foragers, "search", clan.y, clan.x)
            return
        total = sum(shares[rid] for rid in foods)
        counts = {rid: len(foragers) * shares[rid] // total for rid in foods}
        # Hands left over by rounding go to the foods with the largest share.
        by_share = sorted(foods, key=lambda rid: (-shares[rid], rid))
        for index in range(len(foragers) - sum(counts.values())):
            counts[by_share[index % len(by_share)]] += 1
        start = 0
        for rid in by_share:
            crew = foragers[start : start + counts[rid]]
            start += counts[rid]
            if not crew:
                continue
            ty, tx = divmod(int(np.argmax(raws[rid])), raws[rid].shape[1])
            y, x = area[0].start + ty, area[1].start + tx
            self.set_work(crew, rid, y, x)
            self.walk(clan.y, clan.x, y, x, len(crew))

    # ---- faith ------------------------------------------------------------

    def same_faith(self, clan: Clan, other: Clan) -> bool:
        return bool(clan.faith) and clan.faith == other.faith

    def worship(self, clan: Clan) -> None:
        """A faith is born in the clan, or comes to it from those around."""
        world, p = self.world, self.p
        devout = self.way(clan, "devout")
        prophet = "prophet" in self.gifts.get(clan.id, ())
        # Where faith can come from: the chiefdom's seat first, then partners and neighbours.
        realm = self.realms.get(clan.realm)
        seat = self.clans.get(realm.seat) if realm is not None and realm.ended is None else None
        sources = []
        if seat is not None and seat.id != clan.id and seat.faith and seat.faith != clan.faith:
            # A land has one faith: the villages follow the seat.
            sources.append((seat, 12.0 if realm is not None and realm.land_since else 4.0))
        for other in (self.clans[cid] for cid in sorted(self.clans)):
            if other.id == clan.id or not other.faith or other.faith == clan.faith:
                continue
            if other.id in clan.partners or (
                max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.contact_radius
            ):
                sources.append((other, 1.0))
        if sources:
            source, weight = sources[0]
            preacher = "prophet" in self.gifts.get(source.id, ())
            factors = [("from_the_ruler" if weight > 1 else "from_neighbours", weight)]
            factors.append(("devout_people", devout))
            if source.culture == clan.culture:
                factors.append(("same_people", 2.0))
            if preacher:
                factors.append(("prophet_preaches", 3.0))
            if clan.faith:
                factors.append(("holds_its_own_faith", 0.3))
            if world.roll("faith_spreads", "group", clan.id, p.faith_spread_chance, factors):
                self.convert(clan, source.faith, source)
                return
        if clan.faith:
            return
        factors = [("devout_people", devout)]
        if prophet:
            factors.append(("prophet", 10.0))
        if clan.settled:
            factors.append(("settled", 1.5))
        if not world.roll("faith_born", "group", clan.id, p.faith_chance_per_year, factors):
            return
        aspects = sorted(p.faith_aspects)
        aspect = aspects[world.draw_int("faith_aspect", 0, len(aspects) - 1)]
        culture = self.cultures[clan.culture]
        faith = Faith(
            id=self.next_faith,
            name=self.word(culture, f"faith.{aspect}"),
            aspect=aspect,
            founded=world.tick,
            origin=clan.id,
            people=clan.culture,
        )
        self.next_faith += 1
        self.faiths[faith.id] = faith
        self.dirty_faiths.add(faith.id)
        clan.faith = faith.id
        self.dirty_clans.add(clan.id)
        world.count("faiths.born")
        world.emit(
            "faith_born",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "faith": faith.name,
                "faith_id": faith.id,
                "aspect": aspect,
            },
        )

    def rites(self, clan: Clan, adults: list[Person]) -> list[Person]:
        """A clan with a faith has someone who keeps its rites at the camp."""
        if not clan.faith or len(adults) < 4:
            return adults
        keeper = max(adults, key=lambda a: (a.gift == "prophet", a.traits[2], -a.id))
        self.set_work([keeper], "pray", clan.y, clan.x)
        return [a for a in adults if a.id != keeper.id]

    def convert(self, clan: Clan, faith_id: int, source: Clan) -> None:
        before = self.faiths.get(clan.faith)
        clan.faith = faith_id
        self.dirty_clans.add(clan.id)
        faith = self.faiths[faith_id]
        self.world.count("faiths.converted")
        self.world.emit(
            "faith_spread",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "faith": faith.name,
                "faith_id": faith.id,
                "from": source.name,
                "from_id": source.id,
            },
        )
        if before is not None and not any(c.faith == before.id for c in self.clans.values()):
            before.ended = self.world.tick
            self.dirty_faiths.add(before.id)
            self.world.emit("faith_forgotten", data={"faith": before.name, "faith_id": before.id})

    # ---- sickness -----------------------------------------------------------

    def fever(self, clan: Clan) -> None:
        """A fever ends, breaks out, or comes over from a neighbour."""
        world, p = self.world, self.p
        if clan.sick_until and clan.sick_until <= world.tick:
            if clan.sick_dead:  # a fever nobody died of is not worth telling
                world.emit(
                    "epidemic_ended",
                    data={"clan": clan.name, "clan_id": clan.id, "dead": clan.sick_dead},
                )
            clan.sick_until, clan.sick_dead = 0, 0
            clan.immune_until = world.tick + p.disease_immunity_years * DAYS_PER_YEAR
            self.dirty_clans.add(clan.id)
            return
        if clan.sick_until or clan.immune_until > world.tick:
            return
        # Where it can come from: trade partners, the chiefdom, neighbours.
        near = [
            other
            for other in (self.clans[cid] for cid in sorted(self.clans))
            if other.id != clan.id
            and other.sick_until > world.tick
            and (
                other.id in clan.partners
                or (clan.realm and other.realm == clan.realm)
                or max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.contact_radius
            )
        ]
        if near:
            source = near[0]
            if world.roll(
                "infection",
                "group",
                clan.id,
                p.disease_spread_chance,
                [("contacts", float(len(near)))],
            ):
                self.fall_sick(clan, source)
            return
        factors = []
        if clan.settled:
            factors.append(("settled", 2.0))
        if len(clan.members) > 60:
            factors.append(("crowded", len(clan.members) / 60))
        if clan.unmet and sum(clan.unmet) // len(clan.unmet) >= 15:
            factors.append(("hungry", 1.5))
        if clan.realm and self.at_war(clan.realm):
            factors.append(("at_war", 1.5))
        if world.roll("outbreak", "group", clan.id, p.disease_chance_per_year, factors):
            self.fall_sick(clan, None)

    def fall_sick(self, clan: Clan, source: Clan | None) -> None:
        world = self.world
        clan.sick_until = world.tick + self.p.disease_months * DAYS_PER_MONTH
        clan.sick_dead = 0
        self.dirty_clans.add(clan.id)
        world.count("disease.outbreaks" if source is None else "disease.spread")
        if source is None:
            world.emit("epidemic_began", data={"clan": clan.name, "clan_id": clan.id})
        else:
            world.emit(
                "epidemic_spread",
                data={
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "from": source.name,
                    "from_id": source.id,
                },
            )

    def nurse(self, clan: Clan, adults: list[Person]) -> list[Person]:
        """In a fever some lie sick at the camp, and who can heal tends them."""
        if clan.sick_until <= self.world.tick:
            return adults
        count = len(adults) * self.p.disease_sick_percent // 100
        if count == 0:
            return adults
        sick = sorted(adults, key=lambda a: (a.traits[0], a.id))[:count]
        self.set_work(sick, "sick", clan.y, clan.x)
        healers = [a for a in adults if a.gift == "healer" and a not in sick]
        if healers:
            self.set_work(healers, "heal", clan.y, clan.x)
        resting = {a.id for a in sick} | {a.id for a in healers}
        return [a for a in adults if a.id not in resting]

    # ---- the gifted -------------------------------------------------------

    GIFTS = ("leader", "inventor", "warrior", "healer", "prophet")

    def maybe_gifted(self, person: Person, clan: Clan) -> None:
        """Seldom someone comes of age who will change things for the clan."""
        world = self.world
        if not world.roll("gifted", "person", person.id, self.p.gifted_chance, [], detail=True):
            return
        gift = self.GIFTS[world.draw_int("gift", 0, len(self.GIFTS) - 1)]
        person.gift = gift
        # The gift shows in what the person is: the leader wins people over, the
        # warrior is strong, the inventor and the healer have skilled hands.
        index = {"leader": 2, "warrior": 0, "inventor": 1, "healer": 3, "prophet": 2}[gift]
        person.traits[index] = max(person.traits[index], 95)
        self.dirty_persons.add(person.id)
        world.count(f"gifted.{gift}")
        world.emit(
            f"gifted_{gift}",
            data={"name": person.name, "person": person.id, "clan": clan.name, "clan_id": clan.id},
        )

    def note_gifts(self, clan: Clan) -> None:
        """Which gifts the clan's living adults have, for this year's rolls."""
        found = {
            self.persons[pid].gift
            for pid in clan.members
            if pid in self.persons and self.persons[pid].gift
        }
        if found:
            self.gifts[clan.id] = found
        else:
            self.gifts.pop(clan.id, None)

    # ---- one year in a life ----------------------------------------------

    def person_year(self, person: Person) -> None:
        world, p = self.world, self.p
        clan = self.clans[person.clan]
        age = self.age(person)
        unmet = self.unmet_average(clan)
        _harvest, mortality, _storage, _together = self.effects(clan)

        if age < 1:
            band, base = "infant", p.death_chance_infant
        elif age < p.adult_age:
            band, base = "child", p.death_chance_child
        elif age < p.elder_age:
            band, base = "adult", p.death_chance_adult
        else:
            band = "elder"
            base = p.death_chance_elder + p.elder_extra_per_year * (age - p.elder_age)
        factors: list[tuple[str, float]] = []
        if unmet > 0:
            factors.append(("hunger", 1.0 + p.hunger_death_factor * unmet / 100))
        if mortality != 1.0:
            factors.append(("knowledge", mortality))
        if person.traits[0] != 50:
            factors.append(("vigor", 1.5 - person.traits[0] / 100))
        if "healer" in self.gifts.get(clan.id, ()):
            factors.append(("healer_in_clan", 0.85))
        sick = clan.sick_until > world.tick
        if sick:
            fever = p.disease_death_factor
            if "healer" in self.gifts.get(clan.id, ()):
                fever = 1.0 + (fever - 1.0) / 2  # a healer halves what the fever adds
            factors.append(("fever", fever))
        if world.roll(f"death.{band}", "person", person.id, min(base, 1.0), factors, detail=True):
            if sick:
                clan.sick_dead += 1
            self.die(person, "disease" if sick else "hunger" if unmet >= 25 else band)
            return

        if age < p.adult_age:
            return
        if age == p.adult_age and not person.gift:
            self.maybe_gifted(person, clan)
        if person.partner == 0:
            self.maybe_pair(person, clan)
            # Pairing can take somebody to the partner's clan;
            # a child is born where the mother lives now.
            clan = self.clans[person.clan]
        if (
            person.sex == 0
            and person.partner != 0
            and age <= p.max_fertile_age
            and world.tick - person.last_birth >= p.birth_spacing_years * DAYS_PER_YEAR
        ):
            factors = []
            if unmet > 0:
                factors.append(("hunger", max(0.05, 1.0 - p.hunger_birth_factor * unmet / 100)))
            if world.roll(
                "birth", "person", person.id, p.birth_chance_per_year, factors, detail=True
            ):
                self.birth(person, self.persons[person.partner], clan, world.tick)

    def related(self, first: Person, second: Person) -> bool:
        if first.id in (second.mother, second.father) or second.id in (first.mother, first.father):
            return True
        return (first.mother != 0 and first.mother == second.mother) or (
            first.father != 0 and first.father == second.father
        )

    def maybe_pair(self, person: Person, clan: Clan) -> None:
        world, p = self.world, self.p
        candidates: list[tuple[int, int, int]] = []
        nearby = [clan.id] + [
            other.id
            for other in (self.clans[cid] for cid in sorted(self.clans))
            if other.id != clan.id
            and max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.contact_radius
        ]
        for rank, clan_id in enumerate(nearby):
            for other_id in self.clans[clan_id].members:
                other = self.persons[other_id]
                if other.sex == person.sex or other.partner != 0:
                    continue
                if self.age(other) < p.adult_age or self.related(person, other):
                    continue
                candidates.append((rank, abs(other.born - person.born), other.id))
            if candidates:
                break
        if not candidates:
            return
        if not world.roll(
            "pairing", "person", person.id, p.pairing_chance_per_year, [], detail=True
        ):
            return
        partner = self.persons[min(candidates)[2]]
        family = self.next_family
        self.next_family += 1
        person.partner, partner.partner = partner.id, person.id
        person.family = partner.family = family
        if partner.clan != person.clan:
            self.move_person(person, self.clans[partner.clan])
        self.dirty_persons.update((person.id, partner.id))
        world.count("people.pairings")
        home = self.clans[person.clan]
        world.emit(
            "pairing",
            data={
                "name": person.name,
                "person": person.id,
                "partner": partner.name,
                "partner_id": partner.id,
                "clan": home.name,
                "clan_id": home.id,
            },
        )

    def move_person(self, person: Person, target: Clan) -> None:
        source = self.clans[person.clan]
        source.members.remove(person.id)
        target.members.append(person.id)
        target.members.sort()
        person.clan = target.id
        if source.leader == person.id:
            source.leader = 0  # the clan chooses again at the turn of the year
        # A new clan gives new work, from next month on.
        person.activity, person.target_y, person.target_x = "", -1, -1
        self.dirty_persons.add(person.id)
        if not source.members:
            self.dissolve(source, "clan_died_out", {})

    def die(self, person: Person, cause: str) -> None:
        world = self.world
        clan = self.clans[person.clan]
        age = self.age(person)
        person.died, person.cause = world.tick, cause
        clan.members.remove(person.id)
        self.by_month[(person.born // DAYS_PER_MONTH) % 12].remove(person.id)
        if person.partner:
            partner = self.persons.get(person.partner)
            if partner is not None:
                partner.partner = 0
                self.dirty_persons.add(partner.id)
        self.dirty_persons.add(person.id)
        world.count("people.deaths")
        world.count(f"people.deaths.{cause}")
        world.count("people.age_at_death_sum", age)
        world.emit(
            "death",
            data={
                "name": person.name,
                "person": person.id,
                "age": age,
                "cause": cause,
                "clan": clan.name,
                "clan_id": clan.id,
            },
        )
        self.dead[person.id] = person
        del self.persons[person.id]
        if not clan.members:
            self.dissolve(clan, "clan_died_out", {})

    def dissolve(self, clan: Clan, event: str, data: dict[str, Any]) -> None:
        clan.dissolved = self.world.tick
        self.dirty_clans.add(clan.id)
        self.abandon_place(clan, quiet=True)
        self.world.emit(event, data={"clan": clan.name, "clan_id": clan.id, **data})
        for partner_id in sorted(clan.partners):
            self.unlink(clan, partner_id)
        self.retired[clan.id] = clan
        del self.clans[clan.id]
        realm = self.realms.get(clan.realm)
        if realm is not None and realm.ended is None and realm.seat == clan.id:
            self.move_seat(realm)
        faith = self.faiths.get(clan.faith)
        if (
            faith is not None
            and faith.ended is None
            and not any(other.faith == faith.id for other in self.clans.values())
        ):
            faith.ended = self.world.tick
            self.dirty_faiths.add(faith.id)
            self.world.emit("faith_forgotten", data={"faith": faith.name, "faith_id": faith.id})
        self._effects.pop(clan.id, None)
        if clan.culture in self.cultures:
            self.fade(self.cultures[clan.culture])

    # ---- one year of a clan ----------------------------------------------

    def clan_has_fact(self, clan: Clan, fact: str, adults: list[Person]) -> bool:
        if fact.startswith("has:"):
            return fact[4:] in clan.techs
        unmet = self.unmet_average(clan)
        count = max(1, len(adults))
        match fact:
            case "hungry":
                return unmet >= 15
            case "well_fed":
                return unmet == 0 and len(clan.unmet) == 12
            case "large":
                return len(adults) >= 20
            case "small":
                return len(adults) < 8
            case "curious":
                return sum(a.traits[1] for a in adults) >= 55 * count
            case "crafty":
                return sum(a.traits[3] for a in adults) >= 55 * count
            case "coastal":
                area = self.window(clan.y, clan.x, self.p.forage_radius)
                return bool((self.world.map.water[area] | self.world.map.river[area]).any())
            case "cold":
                return int(self.world.map.temperature[clan.y, clan.x]) < 60
            case "settled":
                return clan.settled
        return False

    def nearby(self, clan: Clan, resource_id: str) -> bool:
        world = self.world
        if resource_id in world.capacity:
            key = (resource_id, clan.y, clan.x)
            if key not in self._grows_at:
                area = self.window(clan.y, clan.x, self.p.forage_radius)
                self._grows_at[key] = bool((world.capacity[resource_id][area] > 0).any())
            return self._grows_at[key]
        if resource_id in world.map.deposit_ids:
            if clan.stores.get(resource_id, 0) > 0 or resource_id in self.goods(clan):
                return True
            # What a trading partner has within reach can be had from them.
            return any(
                resource_id in self.goods(self.clans[partner_id])
                for partner_id in sorted(clan.partners)
                if partner_id in self.clans
            )
        return False

    def goods(self, clan: Clan) -> list[str]:
        """The deposits a clan has within reach of its camp. The map never
        changes, so the answer per camp tile is worked out once."""
        key = (clan.y, clan.x)
        cache = self._goods_at
        if key not in cache:
            world = self.world
            area = self.window(clan.y, clan.x, self.p.forage_radius + 2)
            present = {int(index) for index in np.unique(world.map.deposit[area]) if index >= 0}
            cache[key] = [world.map.deposit_ids[index] for index in sorted(present)]
        return cache[key]

    def unlink(self, clan: Clan, partner_id: int) -> None:
        clan.partners.pop(partner_id, None)
        self.dirty_clans.add(clan.id)
        other = self.clans.get(partner_id)
        if other is not None:
            other.partners.pop(clan.id, None)
            self.dirty_clans.add(other.id)
        low, high = sorted((clan.id, partner_id))
        self.ended_links.append((low, high, self.world.tick))

    def trade(self, clan: Clan) -> None:
        """Partnerships begin between neighbours with something to offer each
        other, and end when the two drift apart."""
        world, p = self.world, self.p
        for partner_id in sorted(clan.partners):
            other = self.clans.get(partner_id)
            apart = (
                other is None
                or max(abs(other.y - clan.y), abs(other.x - clan.x)) > 2 * p.contact_radius
                or self.hostile(clan, other)
            )
            if apart:
                self.unlink(clan, partner_id)
                world.count("trade.ended")
        mine = set(self.goods(clan))
        if len(clan.partners) < p.trade_partners_max:
            near = sorted(
                (
                    (max(abs(other.y - clan.y), abs(other.x - clan.x)), other.id)
                    for other in self.clans.values()
                    if other.id != clan.id and other.id not in clan.partners
                ),
            )
            for distance, other_id in near:
                if distance > p.contact_radius:
                    break
                other = self.clans[other_id]
                if len(other.partners) >= p.trade_partners_max or self.hostile(clan, other):
                    continue
                theirs = set(self.goods(other))
                offered = sorted((theirs - mine) | (mine - theirs))
                if not offered and not (clan.settled and other.settled):
                    continue  # nothing either of them lacks
                factors = []
                if other.culture == clan.culture:
                    factors.append(("same_people", 2.0))
                if clan.settled and other.settled:
                    factors.append(("both_settled", 2.0))
                if offered:
                    factors.append(("goods_to_offer", 2.0))
                if not world.roll(
                    "trade_begins",
                    "group",
                    clan.id,
                    p.trade_chance_per_year,
                    [
                        *factors,
                        ("trading_people", self.way(clan, "trading")),
                        *([("same_faith", 1.5)] if self.same_faith(clan, other) else []),
                    ],
                ):
                    continue
                clan.partners[other.id] = world.tick
                other.partners[clan.id] = world.tick
                self.dirty_clans.update((clan.id, other.id))
                low, high = sorted((clan.id, other.id))
                self.new_links.append((low, high, world.tick))
                world.count("trade.begun")
                world.emit(
                    "trade_begun",
                    data={
                        "clan": clan.name,
                        "clan_id": clan.id,
                        "partner": other.name,
                        "partner_id": other.id,
                        "goods": offered,
                    },
                )
                break
        # The yearly coming and going wears a path between partners.
        for partner_id in sorted(clan.partners):
            other = self.clans.get(partner_id)
            if other is not None and partner_id > clan.id and p.trade_walkers_per_year:
                self.walk(clan.y, clan.x, other.y, other.x, p.trade_walkers_per_year)
                world.count("trade.journeys")

    def learn(self, clan: Clan, tech_id: str, discoverer: int, how: str) -> None:
        clan.techs[tech_id] = self.world.tick
        self._effects.pop(clan.id, None)
        self.dirty_clans.add(clan.id)
        tech = self.world.packs.technologies.get(tech_id)
        if tech is not None and tech.effects.keeps_herds and clan.herd <= 0:
            # Who learns to keep animals catches or gets a few to begin with.
            clan.herd = self.p.herd_start
            self.world.count("herds.started")
            self.world.emit("herd_started", data={"clan": clan.name, "clan_id": clan.id})
        self.new_discoveries.append((clan.id, tech_id, self.world.tick, discoverer, how))

    # ---- leaders and chiefdoms -------------------------------------------

    def realm_members(self, clan: Clan) -> list[int]:
        if not clan.realm:
            return []
        return [
            other_id
            for other_id in sorted(self.clans)
            if other_id != clan.id and self.clans[other_id].realm == clan.realm
        ]

    def land_of(self, clan: Clan) -> Realm | None:
        """The land the clan is a village of, if its chiefdom has become one."""
        realm = self.realms.get(clan.realm)
        if realm is None or realm.ended is not None or realm.land_since is None:
            return None
        return realm

    def land_year(self, realm: Realm, seat: Clan) -> None:
        """Decided once a year at the seat: a chiefdom old and large enough becomes
        a land, and a land evens out its stores among its villages."""
        world, p = self.world, self.p
        villages = self.realm_clans(realm)
        if realm.land_since is None:
            old = world.tick - realm.founded >= p.land_after_years * DAYS_PER_YEAR
            if not old or len(villages) < p.land_min_villages:
                return
            realm.land_since = world.tick
            self.dirty_realms.add(realm.id)
            world.count("lands.formed")
            world.emit(
                "land_formed",
                data={
                    "realm": realm.name,
                    "realm_id": realm.id,
                    "villages": len(villages),
                    "clan": seat.name,
                    "clan_id": seat.id,
                },
            )
        # A village stays where it is: clans that came under the land wandering
        # put down roots where they stand.
        for village in villages:
            if not village.settled:
                self.settle(village)
                world.count("lands.villages_rooted")
        # One store for the land: what villages hold beyond their share goes to
        # those that hold less, so no village starves while another's food spoils.
        needs = {v.id: self.monthly_need(v) for v in villages}
        total_need = sum(needs.values())
        total_food = sum(v.food for v in villages)
        if total_need <= 0 or len(villages) < 2:
            return
        fair = {v.id: total_food * needs[v.id] // total_need for v in villages}
        moved = 0
        for village in villages:
            change = fair[village.id] - village.food
            if change > 0:
                self.flow(village, "food", 2, change)
                moved += change
            elif change < 0:
                self.flow(village, "food", 3, -change)
            village.food = fair[village.id]
            self.dirty_clans.add(village.id)
        # What rounding left over stays at the seat.
        seat.food += total_food - sum(fair.values())
        if moved:
            world.count("lands.shared_food", moved)

    def follow(self, clan: Clan, adults: list[Person]) -> None:
        """A clan follows one of its adults: the one others listen to most.

        No dice: whoever is sociable, strong and experienced. A leader keeps the
        place until death, leaving or growing old.
        """
        current = self.persons.get(clan.leader)
        if (
            current is not None
            and current.clan == clan.id
            and self.age(current) < self.p.elder_age + 15
        ):
            return
        if not adults:
            return
        chosen = max(
            adults,
            key=lambda a: (
                2 * a.traits[2] + a.traits[0] + a.traits[3] + min(self.age(a), 45),
                -a.id,
            ),
        )
        before = clan.leader
        clan.leader = chosen.id
        self.dirty_clans.add(clan.id)
        self.world.count("leaders.chosen")
        realm = self.realms.get(clan.realm)
        if realm is not None and realm.seat == clan.id:
            realm.ruler = chosen.id
            self.dirty_realms.add(realm.id)
            self.world.emit(
                "ruler_follows",
                data={
                    "realm": realm.name,
                    "realm_id": realm.id,
                    "ruler": chosen.name,
                    "person": chosen.id,
                },
            )
            if before:
                self.succession(realm)

    def succession(self, realm: Realm) -> None:
        """A new ruler: clans that only followed the old one may go their own way."""
        world, p = self.world, self.p
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            if clan.realm != realm.id or clan.id == realm.seat:
                continue
            factors = [] if clan.culture == realm.people else [("other_people", 2.0)]
            if world.tick - realm.founded >= p.realm_settled_years * DAYS_PER_YEAR:
                factors.append(("old_realm", 0.4))
            if realm.land_since is not None:
                factors.append(("one_land", p.land_break_factor))
            if world.roll(
                "realm_breaks_away", "group", clan.id, p.realm_break_on_succession, factors
            ):
                self.leave_realm(clan, realm, "succession")
        seat = self.clans.get(realm.seat)
        if seat is not None and not self.realm_members(seat):
            self.end_realm(realm)  # nobody but the seat's own follows the new ruler
            return
        if seat is not None:
            self.submit(realm, seat)

    def leave_realm(self, clan: Clan, realm: Realm, why: str) -> None:
        clan.realm = 0
        self.dirty_clans.add(clan.id)
        self.world.count("realms.left")
        self.world.emit(
            "realm_left",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "realm": realm.name,
                "realm_id": realm.id,
                "why": why,
            },
        )

    def end_realm(self, realm: Realm) -> None:
        for war in self.at_war(realm.id):
            self.end_war(war, "faded")
        realm.ended = self.world.tick
        self.dirty_realms.add(realm.id)
        for clan in self.clans.values():
            if clan.realm == realm.id:
                clan.realm = 0
                self.dirty_clans.add(clan.id)
        self.world.count("realms.fallen")
        self.world.emit("realm_fell", data={"realm": realm.name, "realm_id": realm.id})

    def rule(self, clan: Clan, adults: list[Person]) -> None:
        """Chiefdoms form, grow, and hold or lose their clans."""
        world, p = self.world, self.p
        realm = self.realms.get(clan.realm)
        if realm is not None and realm.ended is None:
            seat = self.clans.get(realm.seat)
            if seat is None:
                return
            if clan.id != seat.id:
                far = p.realm_reach * (3 if realm.land_since is not None else 2)
                if max(abs(clan.y - seat.y), abs(clan.x - seat.x)) > far:
                    self.leave_realm(clan, realm, "too_far")
                    return
                self.assimilate(clan, realm)
                return
            self.reach_out(clan, realm, adults)
            self.land_year(realm, clan)
            self.war_year(realm, clan)
            return
        if clan.realm:  # a realm that has ended
            clan.realm = 0
            self.dirty_clans.add(clan.id)
        leader = self.persons.get(clan.leader)
        if not clan.settled or leader is None or len(adults) < p.realm_min_adults:
            return
        free = [
            other
            for other in self.clans.values()
            if other.id != clan.id
            and not other.realm
            and max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.realm_reach
        ]
        if not free:
            return  # nobody around to rule over
        factors = []
        if leader.traits[2] >= 60:
            factors.append(("persuasive_leader", 2.0))
        standing = sum(1 for b in self.places[clan.place]["buildings"] if b["state"] == "standing")
        if standing >= 4:
            factors.append(("built_up", 1.5))
        if sum(1 for other in free if other.culture == clan.culture) >= 2:
            factors.append(("kin_around", 1.5))
        if len(free) == 1:
            factors.append(("few_around", 0.5))
        if not world.roll(
            "realm_founded", "group", clan.id, p.realm_found_chance_per_year, factors
        ):
            return
        realm = Realm(
            id=self.next_realm,
            name=self.places[clan.place]["name"],
            founded=world.tick,
            seat=clan.id,
            ruler=leader.id,
            people=clan.culture,
        )
        self.next_realm += 1
        self.realms[realm.id] = realm
        self.dirty_realms.add(realm.id)
        clan.realm = realm.id
        self.dirty_clans.add(clan.id)
        world.count("realms.founded")
        world.emit(
            "realm_founded",
            data={
                "realm": realm.name,
                "realm_id": realm.id,
                "ruler": leader.name,
                "person": leader.id,
                "clan": clan.name,
                "clan_id": clan.id,
            },
        )

    def reach_out(self, seat: Clan, realm: Realm, adults: list[Person]) -> None:
        """The seat draws clans around it under its rule, one at a time."""
        world, p = self.world, self.p
        members = 1 + len(self.realm_members(seat))
        if members >= p.realm_max_clans:
            return
        ruler = self.persons.get(realm.ruler)
        candidates = sorted(
            (max(abs(other.y - seat.y), abs(other.x - seat.x)), other.id)
            for other in self.clans.values()
            if not other.realm and other.id != seat.id
        )
        for distance, other_id in candidates:
            if distance > p.realm_reach:
                break
            other = self.clans[other_id]
            factors = []
            if other.culture == seat.culture:
                factors.append(("same_people", 2.0))
            else:
                factors.append(("other_people", 0.4))
            if len(other.members) * 2 < len(seat.members):
                factors.append(("smaller", 1.5))
            if ruler is not None and ruler.traits[2] >= 60:
                factors.append(("persuasive_ruler", 1.5))
            if other.unmet and other.unmet[-1] >= 20:
                factors.append(("hungry", 1.5))  # the seat's stores are a pull
            if members >= 5:
                factors.append(("mighty", 1.0 + members / 10))  # the large draw the small
            if not other.settled:
                # Wanderers seldom bind themselves: they would soon be gone again.
                factors.append(("wandering", 0.4))
            if self.same_faith(seat, other):
                factors.append(("same_faith", 1.5))
            if realm.land_since is not None:
                factors.append(("a_land", p.land_draw_factor))  # its stores and peace draw
            if not world.roll(
                "realm_joined", "group", other.id, p.realm_join_chance_per_year, factors
            ):
                continue
            other.realm = realm.id
            self.dirty_clans.add(other.id)
            if realm.land_since is not None and not other.settled:
                self.settle(other)  # a village of a land stays where it is
            world.count("realms.joined")
            world.emit(
                "realm_joined",
                data={
                    "clan": other.name,
                    "clan_id": other.id,
                    "realm": realm.name,
                    "realm_id": realm.id,
                },
            )
            return  # one a year

    def assimilate(self, clan: Clan, realm: Realm) -> None:
        """A clan of another people under the rule of a chiefdom takes up its tongue."""
        if clan.culture == realm.people:
            return
        target = self.cultures.get(realm.people)
        if target is None or target.ended is not None:
            return
        world, p = self.world, self.p
        seat = self.clans[realm.seat]
        factors = []
        if max(abs(clan.y - seat.y), abs(clan.x - seat.x)) <= p.realm_reach // 2:
            factors.append(("near_the_seat", 2.0))
        if not world.roll(
            "realm_assimilates", "group", clan.id, p.realm_assimilate_chance_per_year, factors
        ):
            return
        before = self.cultures[clan.culture]
        clan.culture = target.id
        clan.language = dict(target.language)
        self.dirty_clans.add(clan.id)
        world.count("peoples.assimilated")
        world.emit(
            "people_assimilated",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "people": target.name,
                "people_id": target.id,
                "from": before.name,
                "from_id": before.id,
                "realm": realm.name,
                "realm_id": realm.id,
            },
        )
        self.fade(before)

    def submit(self, realm: Realm, seat: Clan) -> None:
        """A chiefdom with a new ruler may bow to a larger neighbour and become part of it."""
        world, p = self.world, self.p
        mine = [clan for clan in self.clans.values() if clan.realm == realm.id]
        sizes: dict[int, int] = {}
        for clan in self.clans.values():
            if clan.realm and clan.realm != realm.id:
                sizes[clan.realm] = sizes.get(clan.realm, 0) + 1
        candidates = []
        for other_id in sorted(sizes):
            other = self.realms[other_id]
            other_seat = self.clans.get(other.seat)
            if other.ended is not None or other_seat is None:
                continue
            if max(abs(other_seat.y - seat.y), abs(other_seat.x - seat.x)) > p.realm_reach:
                continue
            if sizes[other_id] <= len(mine) or sizes[other_id] + len(mine) > p.realm_max_clans:
                continue
            candidates.append((-sizes[other_id], other_id))
        if not candidates:
            return
        larger = self.realms[min(candidates)[1]]
        factors = (
            [("same_people", 2.0)] if larger.people == realm.people else [("other_people", 0.5)]
        )
        if not world.roll("realm_submits", "group", seat.id, p.realm_union_chance, factors):
            return
        for clan in sorted(mine, key=lambda c: c.id):
            clan.realm = larger.id
            self.dirty_clans.add(clan.id)
        for war in self.at_war(realm.id):
            self.end_war(war, "faded")
        realm.ended = world.tick
        self.dirty_realms.add(realm.id)
        world.count("realms.united")
        world.emit(
            "realm_submitted",
            data={
                "realm": realm.name,
                "realm_id": realm.id,
                "to": larger.name,
                "to_id": larger.id,
                "clans": len(mine),
            },
        )

    # ---- war ---------------------------------------------------------------

    def clan_strength(self, clan: Clan) -> int:
        packs = self.world.packs
        bonus = sum(
            packs.technologies[t].effects.war_percent
            for t in sorted(clan.techs)
            if t in packs.technologies
        )
        if "warrior" in self.gifts.get(clan.id, ()):
            bonus += 50  # a great warrior leads the others
        return len(self.adults(clan)) * (100 + bonus)

    def realm_clans(self, realm: Realm) -> list[Clan]:
        return [self.clans[cid] for cid in sorted(self.clans) if self.clans[cid].realm == realm.id]

    def strength(self, realm: Realm) -> int:
        return sum(self.clan_strength(clan) for clan in self.realm_clans(realm))

    def at_war(self, realm_id: int) -> list[War]:
        return [
            war
            for war in (self.wars[wid] for wid in sorted(self.wars))
            if war.ended is None and realm_id in (war.attacker, war.defender)
        ]

    def hostile(self, clan: Clan, other: Clan) -> bool:
        """Whether the two clans belong to chiefdoms at war with each other."""
        if not clan.realm or not other.realm or clan.realm == other.realm:
            return False
        return any(
            {war.attacker, war.defender} == {clan.realm, other.realm}
            for war in self.at_war(clan.realm)
        )

    def war_year(self, realm: Realm, seat: Clan) -> None:
        """Once a year at the seat: fight the wars this chiefdom started, or start one."""
        for war in self.at_war(realm.id):
            if war.attacker == realm.id:
                self.battle(war)
        if realm.ended is None and not self.at_war(realm.id):
            self.declare(realm, seat)

    def declare(self, realm: Realm, seat: Clan) -> None:
        world, p = self.world, self.p
        mine = self.realm_clans(realm)
        if len(mine) < 2:
            return
        own = self.strength(realm)
        targets = []
        for other_id in sorted(self.realms):
            other = self.realms[other_id]
            other_seat = self.clans.get(other.seat)
            if other.ended is not None or other_id == realm.id or other_seat is None:
                continue
            if max(abs(other_seat.y - seat.y), abs(other_seat.x - seat.x)) > p.war_reach:
                continue
            if self.at_war(other_id):
                continue
            theirs = max(1, self.strength(other))
            targets.append((-own * 100 // theirs, other_id))
        if not targets:
            return
        target = self.realms[min(targets)[1]]
        ratio = own * 100 // max(1, self.strength(target))
        theirs_clans = {clan.id for clan in self.realm_clans(target)}
        factors = []
        factors.append(
            ("same_people", 0.5) if target.people == realm.people else ("other_people", 2.0)
        )
        if ratio >= 150:
            factors.append(("much_stronger", 2.0))
        elif ratio < 100:
            factors.append(("weaker", 0.3))
        if seat.unmet and sum(seat.unmet) // len(seat.unmet) >= 15:
            factors.append(("hungry", 2.0))
        ruler = self.persons.get(realm.ruler)
        if ruler is not None and ruler.traits[0] >= 60:
            factors.append(("warlike_ruler", 1.5))
        factors.append(("warlike_people", self.way(seat, "warlike")))
        target_seat = self.clans.get(target.seat)
        if target_seat is not None and seat.faith and target_seat.faith:
            factors.append(
                ("same_faith", 0.5) if seat.faith == target_seat.faith else ("other_faith", 1.4)
            )
        if any(set(clan.partners) & theirs_clans for clan in mine):
            factors.append(("trade_partners", 0.3))
        if not world.roll("war_declared", "realm", realm.id, p.war_chance_per_year, factors):
            return
        war = War(id=self.next_war, attacker=realm.id, defender=target.id, started=world.tick)
        self.place_field(war)
        self.next_war += 1
        self.wars[war.id] = war
        self.dirty_wars.add(war.id)
        # Trade between the two sides ends.
        for clan in mine:
            for partner_id in sorted(set(clan.partners) & theirs_clans):
                self.unlink(clan, partner_id)
        world.count("wars.begun")
        world.emit(
            "war_begun",
            data={
                "realm": realm.name,
                "realm_id": realm.id,
                "enemy": target.name,
                "enemy_id": target.id,
                "war_id": war.id,
            },
        )

    def place_field(self, war: War) -> None:
        """The two sides meet halfway between their clans nearest each other."""
        attacker, defender = self.realms[war.attacker], self.realms[war.defender]
        a_seat, d_seat = self.clans.get(attacker.seat), self.clans.get(defender.seat)
        if a_seat is None or d_seat is None:
            return
        a_front, d_front = self.front(attacker, d_seat), self.front(defender, a_seat)
        y, x = (a_front.y + d_front.y) // 2, (a_front.x + d_front.x) // 2
        if not self.campable[y, x]:
            y, x = d_front.y, d_front.x  # across water: at the defender's door
        war.field_y, war.field_x = y, x
        self.dirty_wars.add(war.id)

    def front(self, realm: Realm, enemy_seat: Clan) -> Clan:
        """The clan of a chiefdom nearest the enemy's seat."""
        return min(
            self.realm_clans(realm),
            key=lambda c: (max(abs(c.y - enemy_seat.y), abs(c.x - enemy_seat.x)), c.id),
        )

    def fall(self, clan: Clan, count: int, cause: str = "war") -> int:
        """Fighters of a clan fall: men of fighting age, the weakest first."""
        fighters = sorted(
            (
                person
                for person in (self.persons[pid] for pid in clan.members)
                if person.sex == 1 and 16 <= self.age(person) <= 45
            ),
            key=lambda person: (person.traits[0], person.id),
        )[:count]
        for person in fighters:
            if person.clan in self.clans:
                self.die(person, cause)
        return len(fighters)

    def end_war(self, war: War, outcome: str, winner: int = 0) -> None:
        war.ended, war.outcome, war.winner = self.world.tick, outcome, winner
        self.dirty_wars.add(war.id)
        self.world.count(f"wars.{outcome}")

    def battle(self, war: War) -> None:
        world, p = self.world, self.p
        attacker, defender = self.realms[war.attacker], self.realms[war.defender]
        a_seat, d_seat = self.clans.get(attacker.seat), self.clans.get(defender.seat)
        if attacker.ended is not None or defender.ended is not None or not a_seat or not d_seat:
            self.end_war(war, "faded")
            return
        theirs = {clan.id for clan in self.realm_clans(defender)}
        for clan in self.realm_clans(attacker):
            for partner_id in sorted(set(clan.partners) & theirs):
                self.unlink(clan, partner_id)  # who came under either side since
        a_front, d_front = self.front(attacker, d_seat), self.front(defender, a_seat)
        a_strength = self.strength(attacker)
        d_strength = self.strength(defender) * p.war_defender_percent // 100
        chance = a_strength / max(1, a_strength + d_strength)
        won = world.roll("battle_won", "war", war.id, chance, [])
        winner, loser = (attacker, defender) if won else (defender, attacker)
        w_front, l_front = (a_front, d_front) if won else (d_front, a_front)
        l_adults = sum(len(self.adults(c)) for c in self.realm_clans(loser))
        w_adults = sum(len(self.adults(c)) for c in self.realm_clans(winner))
        names = {"winner": winner.name, "winner_id": winner.id, "loser": loser.name}
        names["loser_id"] = loser.id
        fallen = self.fall(l_front, max(1, l_adults // p.war_fallen_per_adults))
        fallen += self.fall(w_front, max(1, w_adults // (2 * p.war_fallen_per_adults)))
        war.battles += 1
        war.fallen += fallen
        war.last_battle, war.last_fallen = world.tick, fallen
        plunder = self.plunder(w_front, l_front) if l_front.id in self.clans else 0
        if plunder:
            names["plunder"] = plunder
        self.dirty_wars.add(war.id)
        world.count("wars.battles")
        world.count("wars.fallen", fallen)
        world.emit(
            "battle_plunder" if plunder else "battle",
            data={**names, "fallen": fallen, "war_id": war.id},
        )
        # The loser gives up the clan nearest the enemy, or all when only the seat is left.
        loser_seat = self.clans.get(loser.seat)
        winner_seat = self.clans[winner.seat]
        # The seat is the last to fall: first every other clan, the nearest first.
        outer = [c for c in self.realm_clans(loser) if loser_seat is None or c.id != loser_seat.id]
        taken = (
            min(
                outer,
                key=lambda c: (max(abs(c.y - winner_seat.y), abs(c.x - winner_seat.x)), c.id),
            )
            if outer
            else loser_seat
        )
        room = p.realm_max_clans - len(self.realm_clans(winner))
        if loser_seat is None or loser.ended is not None:
            self.end_war(war, "conquest", winner.id)
            return
        if taken is not None and taken.id != loser_seat.id and room > 0:
            taken.realm = winner.id
            self.dirty_clans.add(taken.id)
            world.count("wars.clans_taken")
            world.emit(
                "clan_conquered",
                data={**names, "clan": taken.name, "clan_id": taken.id, "war_id": war.id},
            )
        elif taken is not None and taken.id == loser_seat.id:
            self.conquer(war, winner, loser, winner_seat, names)
            return
        self.place_field(war)  # the front moves with what was won
        if world.roll(
            "peace",
            "war",
            war.id,
            p.peace_chance_per_year,
            [("long_war", 2.0)] if war.battles >= 5 else [],
        ):
            self.end_war(war, "peace")
            world.emit("peace_made", data={**names, "battles": war.battles, "war_id": war.id})

    def plunder(self, winner: Clan, loser: Clan) -> int:
        """The winners carry off a share of the beaten clan's stores."""
        share = self.p.war_plunder_percent
        taken = 0
        food = loser.food * share // 100
        if food:
            loser.food -= food
            winner.food += food
            self.flow(loser, "food", 3, food)
            self.flow(winner, "food", 2, food)
            taken += food
        for good in sorted(loser.stores):
            amount = loser.stores[good] * share // 100
            if amount <= 0:
                continue
            loser.stores[good] -= amount
            winner.stores[good] = winner.stores.get(good, 0) + amount
            self.flow(loser, good, 3, amount)
            self.flow(winner, good, 2, amount)
            taken += amount
        driven = loser.herd * share // 100
        if driven and self.keeps_herds(winner):
            loser.herd -= driven
            winner.herd += driven
            self.world.count("herds.plundered", driven)
        if taken:
            self.dirty_clans.update((winner.id, loser.id))
            self.world.count("wars.plundered", taken)
        return taken

    def conquer(
        self, war: War, winner: Realm, loser: Realm, winner_seat: Clan, names: dict[str, Any]
    ) -> None:
        """The seat itself has fallen: the chiefdom is no more, its clans pass to the winner."""
        room = self.p.realm_max_clans - len(self.realm_clans(winner))
        clans = sorted(
            self.realm_clans(loser),
            key=lambda c: (max(abs(c.y - winner_seat.y), abs(c.x - winner_seat.x)), c.id),
        )
        for clan in clans:
            clan.realm = winner.id if room > 0 else 0
            room -= 1
            self.dirty_clans.add(clan.id)
        loser.ended = self.world.tick
        self.dirty_realms.add(loser.id)
        self.end_war(war, "conquest", winner.id)
        self.world.count("realms.conquered")
        self.world.emit("realm_conquered", data={**names, "war_id": war.id})

    def move_seat(self, realm: Realm) -> None:
        """The seat is gone: the largest settled clan of the realm takes over, or it falls."""
        heirs = sorted(
            (
                clan
                for clan in self.clans.values()
                if clan.realm == realm.id and clan.settled and clan.leader in self.persons
            ),
            key=lambda clan: (-len(clan.members), clan.id),
        )
        if not heirs:
            self.end_realm(realm)
            return
        heir = heirs[0]
        realm.seat, realm.ruler = heir.id, heir.leader
        self.dirty_realms.add(realm.id)
        self.world.emit(
            "realm_new_seat",
            data={"realm": realm.name, "realm_id": realm.id, "clan": heir.name, "clan_id": heir.id},
        )

    def kinship(self, clan: Clan) -> None:
        """Peoples form and fade: a clan grown strange to its people founds its
        own, and a clan alone among strangers may become one of them."""
        world, p = self.world, self.p
        culture = self.cultures.get(clan.culture)
        if culture is None:
            return
        near = [
            other
            for other in (self.clans[cid] for cid in sorted(self.clans))
            if other.id != clan.id
            and max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.contact_radius
        ]
        kin = [other for other in near if other.culture == clan.culture]
        drifted = sound_distance(clan.language, culture.language) >= p.people_sound_distance
        # Too many clans for one people: those far from its middle break away.
        members = [other for other in self.clans.values() if other.culture == clan.culture]
        outlying = False
        far_side: set[int] = set()
        if len(members) > p.people_max_clans:
            middle_y = sum(other.y for other in members) // len(members)
            middle_x = sum(other.x for other in members) // len(members)
            distances = sorted(
                max(abs(other.y - middle_y), abs(other.x - middle_x)) for other in members
            )
            mine = max(abs(clan.y - middle_y), abs(clan.x - middle_x))
            edge = distances[len(distances) * 3 // 4]
            outlying = mine >= edge
            far_side = {
                other.id
                for other in members
                if max(abs(other.y - middle_y), abs(other.x - middle_x)) >= edge
            }
        if clan.id != culture.origin and (drifted or outlying):
            factors = [("no_kin_near", 3.0)] if not kin else []
            if outlying:
                factors.append(("people_too_large", 1.0 + 4.0 * len(members) / p.people_max_clans))
            if clan.realm:
                bound = self.realms.get(clan.realm)
                own = bound is not None and bound.people == clan.culture
                factors.append(
                    ("speaks_the_rulers_tongue", 0.05) if own else ("bound_by_realm", 0.2)
                )
                if bound is not None and bound.land_since is not None:
                    factors.append(("one_land", 0.1))  # villages of a land stay one people
            if clan.settled:
                factors.append(("settled", 1.5))
            if world.roll(
                "people_emerges", "group", clan.id, p.people_emerge_chance_per_year, factors
            ):
                new = self.add_culture(clan, culture.id)
                # Neighbours who by now speak more like the founders go with them.
                followers = 0
                for other in kin:
                    # Neighbours on the same far side go too when a people falls apart.
                    closer = sound_distance(other.language, new.language) < sound_distance(
                        other.language, culture.language
                    )
                    if closer or other.id in far_side:
                        other.culture = new.id
                        self.dirty_clans.add(other.id)
                        followers += 1
                world.count("peoples.emerged")
                world.emit(
                    "people_emerged",
                    data={
                        "people": new.name,
                        "people_id": new.id,
                        "from": culture.name,
                        "from_id": culture.id,
                        "clan": clan.name,
                        "clan_id": clan.id,
                        "followers": followers,
                    },
                )
                self.fade(culture)
                return
        if kin or len(near) < 3:
            return
        # Alone among strangers: the people most of the neighbours belong to.
        counts: dict[int, int] = {}
        for other in near:
            counts[other.culture] = counts.get(other.culture, 0) + 1
        host_id = min(counts, key=lambda cid: (-counts[cid], cid))
        if counts[host_id] < 3:
            return
        alone = sum(1 for other in self.clans.values() if other.culture == clan.culture) == 1
        if not world.roll(
            "people_joined",
            "group",
            clan.id,
            p.people_join_chance_per_year,
            [("people_of_one_clan", 3.0)] if alone else [],
        ):
            return
        host = self.cultures[host_id]
        clan.culture = host_id
        self.dirty_clans.add(clan.id)
        world.count("peoples.joined")
        world.emit(
            "people_joined",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "people": host.name,
                "people_id": host.id,
                "from": culture.name,
                "from_id": culture.id,
            },
        )
        self.fade(culture)

    def fade(self, culture: Culture) -> None:
        """A people nobody belongs to any more is history."""
        if culture.ended is not None:
            return
        if any(clan.culture == culture.id for clan in self.clans.values()):
            return
        culture.ended = self.world.tick
        self.dirty_cultures.add(culture.id)
        self.world.count("peoples.vanished")
        self.world.emit("people_vanished", data={"people": culture.name, "people_id": culture.id})

    def forget(self, clan: Clan, adults: list[Person]) -> None:
        """Knowledge nobody can keep up is lost.

        At risk is only what nothing else the clan knows builds on, and only when
        too few adults are left to pass it on or when what the craft needs is no
        longer to be found near the camp.
        """
        world, p = self.world, self.p
        packs = world.packs
        if p.knowledge_loss_chance_per_year <= 0:
            return
        needed = {
            required
            for tech_id in clan.techs
            if tech_id in packs.technologies
            for required in packs.technologies[tech_id].requires
        }
        few = len(adults) < p.knowledge_keepers
        neighbours: list[Clan] | None = None
        for tech_id in sorted(clan.techs):
            tech = packs.technologies.get(tech_id)
            if tech is None:
                continue
            missing = any(not self.nearby(clan, resource) for resource in tech.needs_nearby)
            if not missing:
                clan.unused.pop(tech_id, None)
            elif tech_id not in clan.unused:
                clan.unused[tech_id] = world.tick
            if tech_id in needed:
                continue
            # Out of use only counts once a generation has grown up without it.
            unused = (
                missing
                and world.tick - clan.unused[tech_id] >= p.knowledge_unused_years * DAYS_PER_YEAR
            )
            if not few and not unused:
                continue
            factors = [("few_keepers", 1.0)] if few else []
            if unused:
                factors.append(("out_of_use", 2.0 if few else 1.0))
            if neighbours is None:
                neighbours = [
                    other
                    for other in (self.clans[cid] for cid in sorted(self.clans))
                    if other.id != clan.id
                    and (
                        other.culture == clan.culture or (clan.realm and other.realm == clan.realm)
                    )
                    and max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.contact_radius
                ]
            if any(tech_id in other.techs for other in neighbours):
                factors.append(("reminded_by_neighbours", p.knowledge_reminded_factor))
            if not world.roll(
                f"forget.{tech_id}", "group", clan.id, p.knowledge_loss_chance_per_year, factors
            ):
                continue
            del clan.techs[tech_id]
            clan.unused.pop(tech_id, None)
            self._effects.pop(clan.id, None)
            self.dirty_clans.add(clan.id)
            self.forgotten.append((clan.id, tech_id, world.tick))
            world.count(f"tech.{tech_id}.lost")
            world.count("knowledge.lost")
            world.emit(
                "knowledge_lost",
                data={"tech": tech_id, "clan": clan.name, "clan_id": clan.id},
            )
            if not any(tech_id in other.techs for other in self.clans.values()):
                world.count("knowledge.vanished")
                world.emit("knowledge_vanished", data={"tech": tech_id, "clan": clan.name})

    def raid(self, clan: Clan, adults: list[Person]) -> None:
        """Herders and warlike clans ride out against settled neighbours of
        another people for food and animals. The raided fight back."""
        world, p = self.world, self.p
        packs = world.packs
        if len(adults) < 4:
            return
        riding = sum(
            packs.technologies[t].effects.raid_percent
            for t in sorted(clan.techs)
            if t in packs.technologies
        )
        if clan.herd <= 0 and riding <= 0 and self.way(clan, "warlike") < 1.0:
            return
        targets = sorted(
            (max(abs(other.y - clan.y), abs(other.x - clan.x)), other.id)
            for other in self.clans.values()
            if other.id != clan.id
            and other.settled
            and other.culture != clan.culture
            and not (clan.realm and other.realm == clan.realm)
            and max(abs(other.y - clan.y), abs(other.x - clan.x)) <= p.raid_reach
            and (other.food > 0 or other.herd > 0)
        )
        if not targets:
            return
        target = self.clans[targets[0][1]]
        factors = [("warlike_people", self.way(clan, "warlike"))]
        if riding:
            factors.append(("riders", 1.0 + riding / 100))
        if clan.herd > 0:
            factors.append(("herders", 1.5))
        if not clan.settled:
            factors.append(("wanderers", 1.5))
        if clan.unmet and clan.unmet[-1] >= 20:
            factors.append(("hungry", 3.0))
        if self.same_faith(clan, target):
            factors.append(("same_faith", 0.5))
        if target.id in clan.partners:
            factors.append(("trade_partner", 0.2))
        if not world.roll("raid", "group", clan.id, p.raid_chance_per_year, factors):
            return
        attack = self.clan_strength(clan) * (100 + riding) // 100
        defence = self.clan_strength(target) * 120 // 100
        chance = attack / max(1, attack + defence)
        won = world.roll("raid_succeeds", "group", clan.id, chance, [])
        data = {
            "clan": clan.name,
            "clan_id": clan.id,
            "target": target.name,
            "target_id": target.id,
        }
        if won:
            food = target.food * p.raid_take_percent // 100
            driven = target.herd * p.raid_take_percent // 100 if self.keeps_herds(clan) else 0
            target.food -= food
            clan.food += food
            self.flow(target, "food", 3, food)
            self.flow(clan, "food", 2, food)
            target.herd -= driven
            clan.herd += driven
            fallen = self.fall(target, 1, "raid")
            world.count("raids.won")
            world.count("raids.food", food)
            world.count("herds.raided", driven)
            world.emit("raid", data={**data, "food": food, "herd": driven, "fallen": fallen})
        else:
            fallen = self.fall(clan, 1, "raid")
            world.count("raids.repelled")
            world.emit("raid_repelled", data={**data, "fallen": fallen})
        self.dirty_clans.update((clan.id, target.id))

    def year_of_goods(self, clan: Clan) -> None:
        """Close the year's books, use up what the crafts need, and pass goods between partners."""
        world, p = self.world, self.p
        clan.last_flows = {good: list(clan.flows[good]) for good in sorted(clan.flows)}
        clan.flows = {}
        room = self.room(clan)
        needs: set[str] = set()
        for tech_id in sorted(clan.techs):
            tech = world.packs.technologies.get(tech_id)
            if tech is not None:
                needs.update(rid for rid in tech.needs_nearby if rid in self.good_ids)
        for rid in sorted(needs):
            used = min(clan.stores.get(rid, 0), p.craft_use_per_year)
            if used > 0:
                clan.stores[rid] -= used
                self.flow(clan, rid, 1, used)
                world.count(f"goods.{rid}.used", used)
        # What there is no longer room for is lost (a smaller clan keeps less).
        for rid in sorted(clan.stores):
            over = clan.stores[rid] - room
            if over > 0:
                clan.stores[rid] = room
                self.flow(clan, rid, 1, over)
        # Partners: who has plenty passes on to who has little and a use for it.
        wants = needs | {
            rid
            for building in world.packs.buildings.values()
            if all(tech in clan.techs for tech in building.requires)
            for rid in building.materials
        }
        for partner_id in sorted(clan.partners):
            partner = self.clans.get(partner_id)
            if partner is None:
                continue
            partner_room = self.room(partner)
            for rid in sorted(wants):
                have = clan.stores.get(rid, 0)
                spare = partner.stores.get(rid, 0) - partner_room // 2
                given = min(spare, room // 4 - have)
                if given <= 0:
                    continue
                partner.stores[rid] -= given
                clan.stores[rid] = have + given
                self.flow(clan, rid, 2, given)
                self.flow(partner, rid, 3, given)
                world.count(f"trade.goods.{rid}", given)
                self.dirty_clans.add(partner.id)
        self.dirty_clans.add(clan.id)

    def clan_year(self, clan: Clan) -> None:
        world, p = self.world, self.p
        packs = world.packs
        adults = self.adults(clan)
        if not adults:
            return
        self.year_of_goods(clan)
        self.herd_year(clan)
        self.note_gifts(clan)
        self.fever(clan)
        self.worship(clan)
        self.follow(clan, adults)
        self.rule(clan, adults)

        for tech_id in sorted(packs.technologies):
            if tech_id in clan.techs:
                continue
            tech = packs.technologies[tech_id]
            if any(required not in clan.techs for required in tech.requires):
                continue
            if any(not self.nearby(clan, needed) for needed in tech.needs_nearby):
                continue
            factors = [
                (fact, tech.factors[fact])
                for fact in sorted(tech.factors)
                if self.clan_has_fact(clan, fact, adults)
            ]
            # More minds, more ideas: a large clan finds things sooner than a small one.
            factors.append(("many_minds", max(0.5, len(adults) / 12)))
            factors.append(("inventive_people", self.way(clan, "inventive")))
            if "inventor" in self.gifts.get(clan.id, ()):
                factors.append(("inventor_in_clan", 3.0))
            if world.roll(
                f"discover.{tech_id}", "group", clan.id, tech.base_chance_per_year, factors
            ):
                finder = max(adults, key=lambda a: (a.traits[1] + a.traits[3], -a.id))
                finder.discoveries += 1
                self.dirty_persons.add(finder.id)
                self.learn(clan, tech_id, finder.id, "invented")
                world.count(f"tech.{tech_id}.invented")
                world.emit(
                    "discovery",
                    data={
                        "tech": tech_id,
                        "name": finder.name,
                        "person": finder.id,
                        "clan": clan.name,
                        "clan_id": clan.id,
                    },
                )

        for other_id in sorted(self.clans):
            other = self.clans[other_id]
            if other.id == clan.id:
                continue
            if max(abs(other.y - clan.y), abs(other.x - clan.x)) > p.contact_radius:
                continue
            for tech_id in sorted(other.techs):
                tech_def = packs.technologies.get(tech_id)
                if tech_id in clan.techs or tech_def is None:
                    continue
                if any(required not in clan.techs for required in tech_def.requires):
                    continue
                taught = (
                    [("trade_partner", p.trade_learning_factor)]
                    if other.id in clan.partners
                    else []
                )
                if clan.realm and other.realm == clan.realm:
                    taught.append(("same_realm", p.trade_learning_factor))
                if world.roll(
                    f"learn.{tech_id}",
                    "group",
                    clan.id,
                    p.contact_learning_chance_per_year,
                    taught,
                ):
                    self.learn(clan, tech_id, 0, "learned")
                    world.count(f"tech.{tech_id}.learned")
                    world.emit(
                        "knowledge_shared",
                        data={
                            "tech": tech_id,
                            "clan": clan.name,
                            "clan_id": clan.id,
                            "teacher": other.name,
                            "teacher_id": other.id,
                        },
                    )

        self.trade(clan)
        self.raid(clan, adults)
        self.forget(clan, adults)
        self.kinship(clan)

        hungry = self.unmet_average(clan) >= 15
        if clan.settled:
            # A village of a land is not given up: the land's store sees it through.
            starving = self.unmet_average(clan) >= p.abandon_hunger_percent
            # A village is never moved or given up while people live in it. In
            # hard years some families leave to seek a living elsewhere instead.
            if (
                starving
                and self.land_of(clan) is None
                and len(adults) >= 4
                and world.roll("hunger_emigration", "group", clan.id, p.abandon_chance_per_year, [])
            ):
                world.count("settlements.emigrated")
                self.split(clan)
        elif world.tick - clan.arrived >= p.settle_years * DAYS_PER_YEAR and any(
            packs.technologies[t].effects.enables_settlement
            for t in sorted(clan.techs)
            if t in packs.technologies
        ):
            # Fields bind: who works the soil stays, hungry or not; others settle
            # only in good times.
            farms = any(
                packs.technologies[t].effects.harvest_percent.get("soil", 0) > 0
                for t in sorted(clan.techs)
                if t in packs.technologies
            )
            factors = [("works_the_soil", 3.0)] if farms else []
            factors.append(("rooted_people", self.way(clan, "rooted")))
            if clan.herd > 0 and not farms:
                factors.append(("herders", p.herders_settle_factor))  # they follow the grass
            if (farms or not hungry) and world.roll(
                "settle", "group", clan.id, p.settle_chance_per_year, factors
            ):
                self.settle(clan)

        if len(adults) >= self.effects(clan)[3]:
            factors = [("hungry", 2.0)] if hungry else []
            if world.roll("clan_split", "group", clan.id, p.clan_split_chance_per_year, factors):
                self.split(clan)
        elif len(adults) <= p.clan_merge_adults:
            hosts = sorted(
                (
                    self.clans[cid]
                    for cid in sorted(self.clans)
                    if cid != clan.id
                    and max(abs(self.clans[cid].y - clan.y), abs(self.clans[cid].x - clan.x)) <= 4
                ),
                # The last of a village join a village of the same land first.
                key=lambda host: (not (clan.realm and host.realm == clan.realm), host.id),
            )
            if hosts and world.roll("clan_merge", "group", clan.id, 0.5, []):
                host = hosts[0]
                for person_id in list(clan.members):
                    person = self.persons[person_id]
                    clan.members.remove(person_id)
                    host.members.append(person_id)
                    person.clan = host.id
                    self.dirty_persons.add(person_id)
                host.members.sort()
                host.food += clan.food
                host.herd += clan.herd
                for rid in sorted(clan.stores):
                    host.stores[rid] = host.stores.get(rid, 0) + clan.stores[rid]
                self.dirty_clans.add(host.id)
                self.dissolve(clan, "clan_merged", {"host": host.name, "host_id": host.id})

    def settle(self, clan: Clan) -> None:
        existing = [
            self.places[pid]
            for pid in sorted(self.places)
            if self.places[pid]["y"] == clan.y
            and self.places[pid]["x"] == clan.x
            and self.places[pid]["abandoned"] is not None
        ]
        if existing:
            # An abandoned place keeps its name, and whatever still stands there is used again.
            place = existing[0]
            place["abandoned"] = None
            place["group"] = clan.id
        else:
            name, meaning = self.place_name(clan)
            place = {
                "id": self.next_place,
                "y": clan.y,
                "x": clan.x,
                "name": name,
                "meaning": meaning,
                "founded": self.world.tick,
                "abandoned": None,
                "group": clan.id,
                "buildings": [],
            }
            self.next_place += 1
            self.places[place["id"]] = place
        clan.settled, clan.place = True, place["id"]
        self._effects.pop(clan.id, None)
        self.dirty_places.add(place["id"])
        self.dirty_clans.add(clan.id)
        self.world.count("settlements.founded")
        self.world.emit(
            "settlement_founded",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "place": place["name"],
                "place_id": place["id"],
                "resettled": bool(existing),
            },
        )

    # ---- building -------------------------------------------------------

    def wanted_building(self, clan: Clan, place: dict[str, Any]) -> str | None:
        """The most needed building the clan knows how to make, if any."""
        buildings = self.world.packs.buildings
        people = len(clan.members)
        standing: dict[str, int] = {}
        for building in place["buildings"]:
            if building["state"] == "standing":
                standing[building["type"]] = standing.get(building["type"], 0) + 1
        for kind in sorted(buildings, key=lambda k: (buildings[k].houses == 0, k)):
            definition = buildings[kind]
            if any(required not in clan.techs for required in definition.requires):
                continue
            if definition.houses > 0:
                needed = -(-people // definition.houses)
            else:
                needed = 1 + people // definition.per_people
            if standing.get(kind, 0) < needed:
                return kind
        return None

    def building_spot(self, place: dict[str, Any]) -> tuple[int, int]:
        taken = {(b["y"], b["x"]) for b in place["buildings"]}
        for reach in range(1, 5):
            for dy in range(-reach, reach + 1):
                for dx in range(-reach, reach + 1):
                    if max(abs(dy), abs(dx)) != reach:
                        continue
                    y, x = place["y"] + dy, place["x"] + dx
                    inside = 0 <= y < self.world.map.height and 0 <= x < self.world.map.width
                    if inside and self.campable[y, x] and (y, x) not in taken:
                        return y, x
        return place["y"], place["x"]

    def build(self, clan: Clan) -> None:
        world, p = self.world, self.p
        packs = world.packs
        if not packs.buildings:
            return
        place = self.places[clan.place]
        site = next((b for b in place["buildings"] if b["state"] == "site"), None)
        unmet_now = clan.unmet[-1] if clan.unmet else 0
        if site is None:
            kind = self.wanted_building(clan, place)
            if kind is None:
                return
            definition = packs.buildings[kind]
            for resource in sorted(definition.materials):
                if clan.stores.get(resource, 0) < definition.materials[resource]:
                    return  # not enough of it in store yet
            if not world.roll("build.start", "group", clan.id, p.build_start_chance_per_month, []):
                return
            for resource in sorted(definition.materials):
                needed = definition.materials[resource]
                clan.stores[resource] -= needed
                self.flow(clan, resource, 1, needed)
                world.count(f"materials.{resource}.used", needed)
            self.dirty_clans.add(clan.id)
            y, x = self.building_spot(place)
            place["buildings"].append(
                {
                    "id": self.next_building,
                    "type": kind,
                    "y": y,
                    "x": x,
                    "started": world.tick,
                    "finished": None,
                    "state": "site",
                    "progress": 0,
                }
            )
            self.next_building += 1
            self.dirty_places.add(place["id"])
            world.count(f"buildings.{kind}.started")
            world.emit(
                "construction_started",
                data={
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "place": place["name"],
                    "place_id": place["id"],
                    "building": kind,
                },
            )
            return
        effort = self._effort.get(clan.id, 0)
        if unmet_now >= 20 or effort <= 0:
            return  # hungry people do not build, and a site begun this month waits for hands
        site["progress"] += effort
        self.dirty_places.add(place["id"])
        if site["progress"] >= packs.buildings[site["type"]].work:
            site["state"], site["finished"] = "standing", world.tick
            self._effects.pop(clan.id, None)
            world.count(f"buildings.{site['type']}.finished")
            world.emit(
                "building_finished",
                data={
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "place": place["name"],
                    "place_id": place["id"],
                    "building": site["type"],
                },
            )

    def hold(self, clan: Clan) -> tuple[int, int]:
        """How hard a clan presses on the land around it, and how far."""
        p = self.p
        strength = len(self.adults(clan))
        if clan.settled:
            standing = sum(
                1 for b in self.places[clan.place]["buildings"] if b["state"] == "standing"
            )
            strength += 8 + 3 * standing
        strength = strength * (100 - min(60, self.unmet_average(clan))) // 100
        if strength <= 0:
            return 0, 0
        radius = (3 if clan.settled else 2) + strength // p.territory_strength_per_tile
        return strength, min(p.territory_max_radius, radius)

    def claim(self) -> None:
        """Once a year the land is shared out anew.

        A tile goes to the clan that presses hardest on it: strong clans reach
        further, pressure falls off with distance, and whoever holds a tile
        already has an edge, so borders move only when the balance really shifts.
        No dice: the outcome follows from where and how strong everybody is.
        """
        world, p = self.world, self.p
        shape = self.territory.shape
        best = np.zeros(shape, dtype=np.int64)
        owner = np.zeros(shape, dtype=np.int32)
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            strength, radius = self.hold(clan)
            if strength <= 0:
                continue
            area = self.window(clan.y, clan.x, radius)
            ys, xs = np.mgrid[area]
            distance = np.maximum(np.abs(ys - clan.y), np.abs(xs - clan.x))
            pressure = (strength * (radius + 1 - distance) * 100).astype(np.int64)
            held = self.territory[area] == clan.id
            pressure = np.where(
                held, pressure * (100 + p.territory_hold_bonus_percent) // 100, pressure
            )
            wins = pressure > best[area]
            best[area] = np.where(wins, pressure, best[area])
            owner[area] = np.where(wins, clan.id, owner[area])
        owner[world.map.water] = 0
        self.close_lands(owner)

        people_of = np.zeros(self.next_clan + 1, dtype=np.int32)
        for clan_id in sorted(self.clans):
            people_of[clan_id] = self.clans[clan_id].culture
        land_people = people_of[owner]
        self.close_enclaves(owner, land_people)

        # Land that passed from one people to another is news.
        before, after = self.land_people, land_people
        moved = (before != after) & (before != 0) & (after != 0)
        if moved.any():
            pairs, counts = np.unique(
                before[moved].astype(np.int64) * (self.next_culture + 1) + after[moved],
                return_counts=True,
            )
            for pair, count in zip(pairs.tolist(), counts.tolist(), strict=True):
                loser_id, winner_id = divmod(pair, self.next_culture + 1)
                world.count("territory.tiles_taken", count)
                if count < p.border_event_tiles:
                    continue
                loser, winner = self.cultures.get(loser_id), self.cultures.get(winner_id)
                if loser is None or winner is None:
                    continue
                world.emit(
                    "border_shift",
                    data={
                        "people": winner.name,
                        "people_id": winner.id,
                        "from": loser.name,
                        "from_id": loser.id,
                        "tiles": count,
                    },
                )
        self.territory = owner
        self.land_people = land_people

    def close_lands(self, owner: np.ndarray) -> None:
        """A land is one area, not a scatter of village grounds: narrow gaps
        between its villages' land and the open land it encloses become its own,
        each tile going to the nearest village. No dice."""
        height, width = owner.shape
        water = self.world.map.water
        realm_of = np.zeros(self.next_clan + 1, dtype=np.int32)
        villages: dict[int, list[Clan]] = {}
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            land = self.land_of(clan)
            if land is not None:
                realm_of[clan_id] = land.id
                villages.setdefault(land.id, []).append(clan)
        if not villages:
            return
        tile_land = realm_of[owner]
        free = (owner == 0) & ~water
        edge = np.zeros(owner.shape, dtype=bool)
        edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True

        def shifted(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
            """out[y, x] = mask[y + dy, x + dx], False beyond the map."""
            out = np.zeros_like(mask)
            out[max(0, -dy) : height - max(0, dy), max(0, -dx) : width - max(0, dx)] = mask[
                max(0, dy) : height - max(0, -dy), max(0, dx) : width - max(0, -dx)
            ]
            return out

        # Narrow gaps: open land with the same land on two opposite sides.
        filled = np.zeros(owner.shape, dtype=np.int32)  # land that takes the tile
        for land_id in sorted(villages):
            mine = tile_land == land_id
            gaps = np.zeros(owner.shape, dtype=bool)
            for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
                for step in (1, 2):
                    gaps |= shifted(mine, dy * step, dx * step) & shifted(
                        mine, -dy * step, -dx * step
                    )
            filled = np.where(free & gaps & (filled == 0), land_id, filled)
        # Open land enclosed by one land alone (and the sea) becomes the land's.
        flat_free = (free & (filled == 0)).ravel()
        flat_land = tile_land.ravel()
        flat_edge = edge.ravel()
        seen = np.zeros(height * width, dtype=bool)
        for start in np.flatnonzero(flat_free).tolist():
            if seen[start]:
                continue
            seen[start] = True
            component, stack = [], [start]
            bordering: set[int] = set()
            open_edge = False
            while stack:
                index = stack.pop()
                component.append(index)
                open_edge = open_edge or bool(flat_edge[index])
                y, x = divmod(index, width)
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if not (0 <= ny < height and 0 <= nx < width):
                        continue
                    other = ny * width + nx
                    if flat_free[other]:
                        if not seen[other]:
                            seen[other] = True
                            stack.append(other)
                    elif not water.flat[other]:
                        bordering.add(int(flat_land[other]))  # 0: a free clan's ground
            if open_edge or len(bordering) != 1 or 0 in bordering:
                continue
            land_id = bordering.pop()
            filled.flat[component] = land_id
        if not filled.any():
            return
        ys, xs = np.nonzero(filled)
        for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
            own = villages[int(filled[y, x])]
            nearest = min(own, key=lambda v: (max(abs(v.y - y), abs(v.x - x)), v.id))
            owner[y, x] = nearest.id
        self.world.count("territory.land_filled", len(ys))

    def close_enclaves(self, owner: np.ndarray, land_people: np.ndarray) -> None:
        """A people's land hangs together: no island of it inside another's.

        Land of a people that is cut off from every camp of that people goes to
        the people around it, so what lies inside a border belongs to it. Plain
        flood fill in a fixed order; no dice.
        """
        height, width = owner.shape
        camps: set[tuple[int, int]] = {(c.y, c.x) for c in self.clans.values()}
        seen = np.zeros(owner.shape, dtype=bool)
        flat_people = land_people.ravel()
        for start in np.flatnonzero(flat_people).tolist():
            people = int(flat_people[start])
            if seen.flat[start]:
                continue
            component: list[int] = []
            stack = [start]
            seen.flat[start] = True
            has_camp = False
            around: dict[int, int] = {}  # neighbouring people -> shared border
            around_clan: dict[int, int] = {}
            while stack:
                index = stack.pop()
                component.append(index)
                y, x = divmod(index, width)
                if (y, x) in camps and self.clans_at_people(y, x, people):
                    has_camp = True
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if not (0 <= ny < height and 0 <= nx < width):
                        continue
                    neighbour = ny * width + nx
                    other = int(flat_people[neighbour])
                    if other == people:
                        if not seen.flat[neighbour]:
                            seen.flat[neighbour] = True
                            stack.append(neighbour)
                    elif other != 0:
                        around[other] = around.get(other, 0) + 1
                        around_clan.setdefault(other, int(owner.flat[neighbour]))
            if has_camp or not around:
                continue
            # Surrounded: the people with the longest shared border takes it.
            taker = min(around, key=lambda other: (-around[other], other))
            for index in component:
                owner.flat[index] = around_clan[taker]
                land_people.flat[index] = taker
            self.world.count("territory.enclaves_closed")

    def clans_at_people(self, y: int, x: int, people: int) -> bool:
        return any(c.y == y and c.x == x and c.culture == people for c in self.clans.values())

    def watch_fixed_points(self) -> None:
        """Diagnostics only: built things must never move. Once a year compare
        places, buildings and settled clans with the year before and write any
        change of tile to the program log. Nothing here touches the world."""
        now: dict[str, tuple[int, int]] = {}
        for place_id, place in self.places.items():
            now[f"place:{place_id}"] = (place["y"], place["x"])
            for building in place["buildings"]:
                now[f"building:{building['id']}:{building['type']}"] = (
                    building["y"],
                    building["x"],
                )
        for clan in self.clans.values():
            if clan.settled:
                now[f"settled_clan:{clan.id}:place:{clan.place}"] = (clan.y, clan.x)
        before = self._fixed_points
        for key in sorted(now):
            if key in before and before[key] != now[key]:
                _watch_log.warning(
                    "fixed point moved",
                    extra={
                        "what": key,
                        "from": list(before[key]),
                        "to": list(now[key]),
                        "tick": self.world.tick,
                    },
                )
        self._fixed_points = now

    def new_year(self) -> None:
        """Footsteps fade, and what stands in abandoned places slowly falls apart."""
        self.watch_fixed_points()
        p = self.p
        self.steps = (
            self.steps.astype(np.int64) * (100 - p.steps_decay_percent_per_year) // 100
        ).astype(np.int32)
        self.claim()
        for place_id in sorted(self.places):
            place = self.places[place_id]
            if place["abandoned"] is None:
                continue
            # Ruins do not last for ever either: after a long time nothing is left to see.
            kept = []
            for building in place["buildings"]:
                gone = building["state"] == "ruin" and self.world.roll(
                    "ruin_vanishes", "place", place_id, 0.03, [], detail=True
                )
                if gone:
                    self.vanished.add(building["id"])
                else:
                    kept.append(building)
            if len(kept) != len(place["buildings"]):
                place["buildings"] = kept
                self.dirty_places.add(place_id)
            for building in place["buildings"]:
                if building["state"] == "ruin":
                    continue
                if self.world.roll("building_decay", "place", place_id, p.ruin_chance_per_year, []):
                    was_site = building["state"] == "site"
                    building["state"] = "ruin"
                    self.dirty_places.add(place_id)
                    self.world.count("buildings.ruined")
                    if not was_site:
                        self.world.emit(
                            "building_ruined",
                            data={
                                "place": place["name"],
                                "place_id": place_id,
                                "building": building["type"],
                            },
                        )

    def abandon_place(self, clan: Clan, quiet: bool = False) -> None:
        if not clan.settled:
            return
        place = self.places[clan.place]
        place["abandoned"] = self.world.tick
        self.dirty_places.add(place["id"])
        clan.settled, clan.place = False, 0
        self._effects.pop(clan.id, None)
        self.dirty_clans.add(clan.id)
        self.world.count("settlements.abandoned")
        if not quiet:
            self.world.emit(
                "settlement_abandoned",
                data={
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "place": place["name"],
                    "place_id": place["id"],
                },
            )

    def split(self, clan: Clan) -> None:
        families = sorted({self.persons[pid].family for pid in clan.members})
        leaving = set(families[1::2])
        if not leaving:
            return
        land = self.land_of(clan)
        # In a land, the young families found a new village near by; it keeps the
        # tongue of the land. Elsewhere a new clan goes off and soon talks its own way.
        site = self.best_site(clan, min_distance=2 if land is not None else 3)
        if site is None:
            return
        language = dict(clan.language) if land is not None else self.drift_language(clan.language)
        new = self.add_clan(site[1], site[2], clan.id, language, clan.culture)
        new.techs = dict(clan.techs)
        new.faith = clan.faith if land is not None else new.faith
        for tech_id in sorted(new.techs):
            self.new_discoveries.append((new.id, tech_id, self.world.tick, 0, "inherited"))
        realm = self.realms.get(clan.realm)
        if realm is not None and realm.ended is None and realm.seat in self.clans:
            seat = self.clans[realm.seat]
            reach = self.p.realm_reach * (3 if land is not None else 2)
            near = max(abs(new.y - seat.y), abs(new.x - seat.x)) <= reach
            room = 1 + len(self.realm_members(seat)) < self.p.realm_max_clans
            if near and room:
                new.realm = realm.id  # the daughter clan stays under the same rule
                self.world.count("realms.grew_by_split")
        movers = [pid for pid in clan.members if self.persons[pid].family in leaving]
        for person_id in movers:
            person = self.persons[person_id]
            clan.members.remove(person_id)
            new.members.append(person_id)
            person.clan = new.id
            if clan.leader == person_id:
                clan.leader = 0  # the clan chooses again at the turn of the year
            if person.partner and self.persons[person.partner].family not in leaving:
                self.persons[person.partner].partner = 0
                self.dirty_persons.add(person.partner)
                person.partner = 0
            self.dirty_persons.add(person_id)
        share = clan.food * len(movers) // max(1, len(movers) + len(clan.members))
        clan.food -= share
        new.food = share
        for rid in sorted(clan.stores):
            part = clan.stores[rid] * len(movers) // max(1, len(movers) + len(clan.members))
            clan.stores[rid] -= part
            new.stores[rid] = part
        new.unmet = list(clan.unmet)
        part = clan.herd * len(movers) // max(1, len(movers) + len(clan.members))
        clan.herd -= part
        new.herd = part
        self.walk(clan.y, clan.x, new.y, new.x, len(movers))
        self.dirty_clans.add(clan.id)
        if land is not None and new.realm == land.id:
            self.world.count("lands.villages_founded")
            self.world.emit(
                "village_founded",
                data={
                    "clan": clan.name,
                    "clan_id": clan.id,
                    "new_clan": new.name,
                    "new_clan_id": new.id,
                    "realm": land.name,
                    "realm_id": land.id,
                },
            )
            return
        self.world.count("clans.split")
        self.world.emit(
            "clan_split",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "new_clan": new.name,
                "new_clan_id": new.id,
            },
        )

    # ---- movement -------------------------------------------------------

    def best_site(self, clan: Clan, min_distance: int = 1) -> tuple[int, int, int] | None:
        """Best camp tile within reach: (score, y, x). The current tile is not a candidate."""
        world, p = self.world, self.p
        reach = p.move_radius
        # Without boats a clan keeps to its own land; with them it can cross to
        # other land as far as its boats carry, setting out from the shore.
        sea = self.sea_reach(clan) if self.clan_has_fact(clan, "coastal", []) else 0
        outer = self.window(clan.y, clan.x, max(reach, sea) + p.forage_radius)
        harvest_percent, _m, _s, _t = self.effects(clan)
        value = np.zeros(world.stocks[self.food_ids[0]][outer].shape, dtype=np.int64)
        for rid in self.food_ids:
            if harvest_percent[rid] > 0:
                value += (
                    world.stocks[rid][outer].astype(np.int64)
                    * harvest_percent[rid]
                    * world.packs.resources[rid].food_value
                )
        if clan.herd > 0:
            # Herders look for grass: what it gives through the animals.
            value += (
                world.stocks[p.herd_grazes][outer].astype(np.int64)
                * 100
                * p.herd_food_per_head_month
                // p.herd_graze_per_head_month
            )
        score = _box_sum(value, p.forage_radius)
        y_start, x_start = outer[0].start, outer[1].start
        shape = score.shape

        # Other camps close by make a site less attractive.
        camp_grid = np.zeros(shape, dtype=np.int64)
        for other_id in sorted(self.clans):
            other = self.clans[other_id]
            if other.id == clan.id:
                continue
            cy, cx = other.y - y_start, other.x - x_start
            if 0 <= cy < shape[0] and 0 <= cx < shape[1]:
                camp_grid[cy, cx] += 1
        crowd = np.minimum(_box_sum(camp_grid, 2 * p.forage_radius), 3)
        score = score // np.array([1, 3, 9, 27], dtype=np.int64)[crowd]
        # An abandoned place draws newcomers: its houses can be used again.
        for place_id in sorted(self.places):
            place = self.places[place_id]
            py, px = place["y"] - y_start, place["x"] - x_start
            if place["abandoned"] is not None and 0 <= py < shape[0] and 0 <= px < shape[1]:
                score[py, px] = score[py, px] * 3 // 2

        ys = np.arange(shape[0])[:, None] + y_start
        xs = np.arange(shape[1])[None, :] + x_start
        distance = np.maximum(np.abs(ys - clan.y), np.abs(xs - clan.x))
        score = score - score * distance * 3 // 100
        home = self.landmass[outer] == self.landmass[clan.y, clan.x]
        allowed = (
            (distance >= min_distance)
            & self.campable[outer]
            & ((home & (distance <= reach)) | (~home & (distance <= sea)))
        )
        if not bool(allowed.any()):
            return None
        score = np.where(allowed, score, -1)
        flat = int(np.argmax(score))  # first maximum: lowest y, then lowest x
        y, x = divmod(flat, shape[1])
        return (int(score[y, x]), y + y_start, x + x_start)

    def site_score(self, clan: Clan) -> int:
        world, p = self.world, self.p
        area = self.window(clan.y, clan.x, p.forage_radius)
        harvest_percent, _m, _s, _t = self.effects(clan)
        grass = 0
        if clan.herd > 0:
            grass = (
                int(world.stocks[p.herd_grazes][area].astype(np.int64).sum())
                * 100
                * p.herd_food_per_head_month
                // p.herd_graze_per_head_month
            )
        return grass + sum(
            int(world.stocks[rid][area].astype(np.int64).sum())
            * harvest_percent[rid]
            * world.packs.resources[rid].food_value
            for rid in self.food_ids
            if harvest_percent[rid] > 0
        )

    def walk(self, y0: int, x0: int, y1: int, x1: int, people: int) -> None:
        """Count footsteps on the tiles between two camps. Paths will grow from this."""
        distance = max(abs(y1 - y0), abs(x1 - x0))
        for step in range(1, distance + 1):
            y = y0 + (y1 - y0) * step // distance
            x = x0 + (x1 - x0) * step // distance
            if not self.world.map.water[y, x]:  # no footsteps on open water
                self.steps[y, x] += people

    def maybe_migrate(self, clan: Clan, month: int) -> None:
        world, p = self.world, self.p
        if clan.settled or self.land_of(clan) is not None:
            return  # settled people stay until hunger makes them give the place up; villages stay
        unmet_now = clan.unmet[-1] if clan.unmet else 0
        factors: list[tuple[str, float]] = []
        if unmet_now > 0:
            factors.append(("hunger", 1.0 + unmet_now / 5))
        if clan.settled:
            factors.append(("settled", 0.1))
        if month >= 9:
            factors.append(("winter", 0.5))
        factors.append(("rooted_people", 2.0 - self.way(clan, "rooted")))
        if clan.herd > 0:
            _area, grass = self.pasture(clan)
            if grass < clan.herd * p.herd_graze_per_head_month * 3:
                factors.append(("grass_eaten", 4.0))  # the herds need fresh pasture
        if not world.roll("migration", "group", clan.id, p.wander_chance_per_month, factors):
            return
        site = self.best_site(clan)
        if site is None:
            return
        if unmet_now == 0 and site[0] * 100 <= self.site_score(clan) * 115 and not clan.herd:
            return  # nowhere clearly better and nobody is hungry
        _score, y, x = site
        distance = max(abs(y - clan.y), abs(x - clan.x))
        if clan.settled:
            self.abandon_place(clan)
        self.walk(clan.y, clan.x, y, x, len(clan.members))
        for person_id in clan.members:
            self.persons[person_id].moved += distance
            self.dirty_persons.add(person_id)
        world.count("clans.migrations")
        world.count("clans.migration_distance", distance)
        world.emit(
            "migration",
            data={
                "clan": clan.name,
                "clan_id": clan.id,
                "from": [clan.y, clan.x],
                "to": [y, x],
                "distance": distance,
            },
        )
        crossed = int(self.landmass[y, x]) != int(self.landmass[clan.y, clan.x])
        clan.y, clan.x, clan.arrived = y, x, world.tick
        if crossed:
            world.count("seafaring.crossings")
        self.arrive(clan, crossed)
        # Work was given out for the old camp; at the new one it is given out next month.
        for person_id in clan.members:
            person = self.persons[person_id]
            if person.activity:
                person.activity, person.target_y, person.target_x = "", -1, -1
                self.dirty_persons.add(person_id)
        self.dirty_clans.add(clan.id)

    # ---- statistics and state ---------------------------------------------

    def year_metrics(self, rows: list[tuple[Any, ...]], tick: int) -> None:
        population = adults_total = age_sum = 0
        families: set[int] = set()
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            adults = len(self.adults(clan))
            population += len(clan.members)
            adults_total += adults
            for person_id in clan.members:
                person = self.persons[person_id]
                age_sum += self.age(person)
                families.add(person.family)
            rows.append((tick, "people.population", "group", clan.id, float(len(clan.members))))
            rows.append((tick, "people.adults", "group", clan.id, float(adults)))
            rows.append((tick, "food.stored", "group", clan.id, float(clan.food)))
            rows.append(
                (tick, "food.unmet_percent", "group", clan.id, float(self.unmet_average(clan)))
            )
            rows.append((tick, "tech.known", "group", clan.id, float(len(clan.techs))))
        by_culture: dict[int, int] = {}
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            by_culture[clan.culture] = by_culture.get(clan.culture, 0) + len(clan.members)
        for culture_id in sorted(by_culture):
            rows.append(
                (tick, "people.population", "culture", culture_id, float(by_culture[culture_id]))
            )
        rows.append((tick, "peoples.count", "world", 0, float(len(by_culture))))
        kept: dict[tuple[int, str], int] = {}
        for clan_id in sorted(self.clans):
            clan = self.clans[clan_id]
            for good, amount in [("food", clan.food), *sorted(clan.stores.items())]:
                kept[(clan.culture, good)] = kept.get((clan.culture, good), 0) + amount
                kept[(0, good)] = kept.get((0, good), 0) + amount
        for (culture_id, good), amount in sorted(kept.items()):
            scope = "world" if culture_id == 0 else "culture"
            rows.append((tick, f"stores.{good}", scope, culture_id, float(amount)))
        living_realms = {clan.realm for clan in self.clans.values() if clan.realm}
        rows.append((tick, "realms.count", "world", 0, float(len(living_realms))))
        rows.append(
            (
                tick,
                "wars.ongoing",
                "world",
                0,
                float(sum(1 for w in self.wars.values() if w.ended is None)),
            )
        )
        rows.append(
            (
                tick,
                "realms.clans",
                "world",
                0,
                float(sum(1 for c in self.clans.values() if c.realm)),
            )
        )
        links = sum(len(clan.partners) for clan in self.clans.values()) // 2
        rows.append((tick, "trade.partnerships", "world", 0, float(links)))
        held = np.bincount(self.land_people.ravel(), minlength=self.next_culture + 1)
        for culture_id in sorted(by_culture):
            rows.append(
                (tick, "territory.tiles", "culture", culture_id, float(int(held[culture_id])))
            )
        rows.append((tick, "territory.tiles", "world", 0, float(int((self.territory > 0).sum()))))
        rows.append((tick, "people.population", "world", 0, float(population)))
        rows.append((tick, "people.adults", "world", 0, float(adults_total)))
        rows.append((tick, "people.families", "world", 0, float(len(families))))
        rows.append((tick, "people.age_sum", "world", 0, float(age_sum)))
        rows.append((tick, "clans.count", "world", 0, float(len(self.clans))))
        rows.append(
            (
                tick,
                "settlements.count",
                "world",
                0,
                float(sum(c.settled for c in self.clans.values())),
            )
        )
        rows.append((tick, "tiles.walked", "world", 0, float(int((self.steps > 0).sum()))))
        trail = int((self.steps >= self.p.path_trail_steps).sum())
        road = int((self.steps >= self.p.path_road_steps).sum())
        rows.append((tick, "paths.trail_tiles", "world", 0, float(trail - road)))
        rows.append((tick, "paths.road_tiles", "world", 0, float(road)))
        standing = ruins = sites = 0
        for place_id in sorted(self.places):
            for building in self.places[place_id]["buildings"]:
                standing += building["state"] == "standing"
                ruins += building["state"] == "ruin"
                sites += building["state"] == "site"
        rows.append((tick, "buildings.standing", "world", 0, float(standing)))
        rows.append((tick, "buildings.ruins", "world", 0, float(ruins)))
        rows.append((tick, "buildings.sites", "world", 0, float(sites)))

    def clear_dirty(self) -> None:
        self.dirty_persons.clear()
        self.dirty_clans.clear()
        self.dirty_places.clear()
        self.dirty_cultures.clear()
        self.dirty_realms.clear()
        self.dirty_wars.clear()
        self.dirty_faiths.clear()
        self.new_discoveries.clear()
        self.forgotten.clear()
        self.new_links.clear()
        self.ended_links.clear()
        self.retired = {}
        self.dead = {}
        self.vanished = set()

    def dump_state(self) -> dict[str, Any]:
        return {
            "next_person": self.next_person,
            "next_clan": self.next_clan,
            "next_family": self.next_family,
            "next_place": self.next_place,
            "next_building": self.next_building,
            "next_culture": self.next_culture,
            "next_realm": self.next_realm,
            "next_war": self.next_war,
            "next_faith": self.next_faith,
            "faiths": [
                {
                    "id": f.id,
                    "name": f.name,
                    "aspect": f.aspect,
                    "founded": f.founded,
                    "origin": f.origin,
                    "people": f.people,
                    "ended": f.ended,
                }
                for f in (self.faiths[fid] for fid in sorted(self.faiths))
            ],
            "gifts": {str(k): sorted(self.gifts[k]) for k in sorted(self.gifts)},
            "landed": sorted(self.landed),
            "wars": [
                {
                    "id": w.id,
                    "attacker": w.attacker,
                    "defender": w.defender,
                    "started": w.started,
                    "ended": w.ended,
                    "outcome": w.outcome,
                    "battles": w.battles,
                    "fallen": w.fallen,
                    "winner": w.winner,
                    "field_y": w.field_y,
                    "field_x": w.field_x,
                    "last_battle": w.last_battle,
                    "last_fallen": w.last_fallen,
                }
                for w in (self.wars[wid] for wid in sorted(self.wars))
            ],
            "realms": [
                {
                    "id": r.id,
                    "name": r.name,
                    "founded": r.founded,
                    "seat": r.seat,
                    "ruler": r.ruler,
                    "people": r.people,
                    "ended": r.ended,
                    "land_since": r.land_since,
                }
                for r in (self.realms[rid] for rid in sorted(self.realms))
            ],
            "extinct": self.extinct,
            "cultures": [
                {
                    "id": k.id,
                    "name": k.name,
                    "parent": k.parent,
                    "founded": k.founded,
                    "origin": k.origin,
                    "language": k.language,
                    "words": dict(sorted(k.words.items())),
                    "ended": k.ended,
                    "ways": dict(sorted(k.ways.items())),
                }
                for k in (self.cultures[kid] for kid in sorted(self.cultures))
            ],
            "clans": [
                {
                    "id": c.id,
                    "name": c.name,
                    "y": c.y,
                    "x": c.x,
                    "founded": c.founded,
                    "parent": c.parent,
                    "month": c.month,
                    "language": c.language,
                    "culture": c.culture,
                    "leader": c.leader,
                    "realm": c.realm,
                    "sick_until": c.sick_until,
                    "faith": c.faith,
                    "herd": c.herd,
                    "immune_until": c.immune_until,
                    "sick_dead": c.sick_dead,
                    "partners": {str(k): c.partners[k] for k in sorted(c.partners)},
                    "unused": {k: c.unused[k] for k in sorted(c.unused)},
                    "stores": dict(sorted(c.stores.items())),
                    "flows": dict(sorted(c.flows.items())),
                    "last_flows": dict(sorted(c.last_flows.items())),
                    "techs": dict(sorted(c.techs.items())),
                    "food": c.food,
                    "unmet": c.unmet,
                    "arrived": c.arrived,
                    "settled": c.settled,
                    "place": c.place,
                    "famine": c.famine,
                }
                for c in (self.clans[cid] for cid in sorted(self.clans))
            ],
            "places": [self.places[pid] for pid in sorted(self.places)],
        }

    def load_state(
        self,
        state: dict[str, Any],
        persons: list[Person],
        steps: np.ndarray | None,
        territory: np.ndarray | None = None,
    ) -> None:
        self.next_person = state["next_person"]
        self.next_clan = state["next_clan"]
        self.next_family = state["next_family"]
        self.next_place = state["next_place"]
        self.next_building = state.get("next_building", 1)
        self.extinct = state["extinct"]
        self.clans = {}
        for raw in state["clans"]:
            self.clans[raw["id"]] = Clan(
                id=raw["id"],
                name=raw["name"],
                y=raw["y"],
                x=raw["x"],
                founded=raw["founded"],
                parent=raw["parent"],
                month=raw["month"],
                language=dict(raw["language"]),
                culture=raw.get("culture", 0),
                leader=raw.get("leader", 0),
                realm=raw.get("realm", 0),
                sick_until=raw.get("sick_until", 0),
                faith=raw.get("faith", 0),
                herd=raw.get("herd", 0),
                immune_until=raw.get("immune_until", 0),
                sick_dead=raw.get("sick_dead", 0),
                partners={int(k): v for k, v in raw.get("partners", {}).items()},
                unused=dict(raw.get("unused", {})),
                stores=dict(raw.get("stores", {})),
                flows={k: list(v) for k, v in raw.get("flows", {}).items()},
                last_flows={k: list(v) for k, v in raw.get("last_flows", {}).items()},
                techs=dict(raw["techs"]),
                food=raw["food"],
                unmet=list(raw["unmet"]),
                arrived=raw["arrived"],
                settled=raw["settled"],
                place=raw["place"],
                famine=raw["famine"],
            )
        self.next_realm = state.get("next_realm", 1)
        self.next_war = state.get("next_war", 1)
        self.next_faith = state.get("next_faith", 1)
        self.faiths = {raw["id"]: Faith(**raw) for raw in state.get("faiths", [])}
        self.wars = {raw["id"]: War(**raw) for raw in state.get("wars", [])}
        self.realms = {raw["id"]: Realm(**raw) for raw in state.get("realms", [])}
        self.next_culture = state.get("next_culture", 1)
        self.cultures = {
            raw["id"]: Culture(
                id=raw["id"],
                name=raw["name"],
                parent=raw["parent"],
                founded=raw["founded"],
                origin=raw["origin"],
                language=dict(raw["language"]),
                ways=dict(raw.get("ways", {})),
                words=dict(raw["words"]),
                ended=raw["ended"],
            )
            for raw in state.get("cultures", [])
        }
        self.places = {}
        for raw in state["places"]:
            place = dict(raw)
            place["buildings"] = [dict(b) for b in raw.get("buildings", [])]
            self.places[place["id"]] = place
        self.persons = {}
        self.by_month = {month: [] for month in range(12)}
        for person in sorted(persons, key=lambda item: item.id):
            self.persons[person.id] = person
            self.clans[person.clan].members.append(person.id)
            self.by_month[(person.born // DAYS_PER_MONTH) % 12].append(person.id)
        if steps is not None:
            self.steps = steps
        if territory is not None:
            self.territory = territory
            people_of = np.zeros(self.next_clan + 1, dtype=np.int32)
            for clan_id in sorted(self.clans):
                people_of[clan_id] = self.clans[clan_id].culture
            self.land_people = people_of[np.clip(territory, 0, self.next_clan)]
        self._effects = {}
        self._labour = {}
        # The gifts as last noted, so a resumed world rolls exactly as one that ran on.
        self.gifts = {int(k): set(v) for k, v in state.get("gifts", {}).items()}
        if "landed" in state:
            self.landed = set(state["landed"])
        else:  # worlds saved before seafaring: where clans camp now
            self.landed = {int(self.landmass[c.y, c.x]) for c in self.clans.values()} - {0}
        self.clear_dirty()
        if self.clans and not self.cultures:
            # A world from before peoples existed: everybody alive is one people,
            # named after the oldest clan. No dice, so loading stays repeatable.
            eldest = self.clans[min(self.clans)]
            culture = Culture(
                id=1,
                name=eldest.name + self.place_endings(eldest.language)[0],
                parent=0,
                founded=eldest.founded,
                origin=eldest.id,
                language=dict(eldest.language),
            )
            self.cultures[1] = culture
            self.next_culture = 2
            self.dirty_cultures.add(1)
            for clan in self.clans.values():
                clan.culture = 1
                self.dirty_clans.add(clan.id)

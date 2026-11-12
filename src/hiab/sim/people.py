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

from hiab.packs import BIOMES, LifeParams

if TYPE_CHECKING:
    from hiab.sim.engine import World

DAYS_PER_MONTH = 30
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
    members: list[int] = field(default_factory=list)
    techs: dict[str, int] = field(default_factory=dict)
    food: int = 0
    unmet: list[int] = field(default_factory=list)  # percent of need unmet, last 12 months
    arrived: int = 0
    settled: bool = False
    place: int = 0
    famine: bool = False
    dissolved: int | None = None


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
        self.dirty_persons: set[int] = set()
        self.dirty_clans: set[int] = set()
        self.dirty_places: set[int] = set()
        self.cultures: dict[int, Culture] = {}
        self.next_culture = 1
        self.dirty_cultures: set[int] = set()
        self.new_discoveries: list[tuple[int, str, int, int, str]] = []
        self.forgotten: list[tuple[int, str, int]] = []  # clan, technology, tick
        self.food_ids = world.packs.foods()
        self.campable = ~world.map.water & ~world.map.river
        self._effects: dict[int, tuple[dict[str, int], float, int, int]] = {}
        self.retired: dict[int, Clan] = {}  # clans dissolved since the last save
        self.dead: dict[int, Person] = {}  # people who died since the last save
        self.vanished: set[int] = set()  # ruins that disappeared since the last save
        self._effort: dict[int, int] = {}  # this month's building work per clan

    # ---- small helpers --------------------------------------------------

    def quiet(self, low: int, high: int) -> int:
        """Cosmetic draw (names, traits, days). Deterministic but not logged."""
        return int(self.world.streams.get("people").integers(low, high + 1))

    def age(self, person: Person) -> int:
        return (self.world.tick - person.born) // DAYS_PER_YEAR

    def adults(self, clan: Clan) -> list[Person]:
        return [
            self.persons[pid]
            for pid in clan.members
            if self.age(self.persons[pid]) >= self.p.adult_age
        ]

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
        return result

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
        self.next_culture += 1
        self.cultures[culture.id] = culture
        self.dirty_cultures.add(culture.id)
        clan.culture = culture.id
        self.dirty_clans.add(clan.id)
        return culture

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
        return clan

    def found(self) -> None:
        """Place the first families on a good spot."""
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
        order = np.argsort(-score, axis=None, kind="stable")[:20]
        pick = int(order[world.draw_int("start_site", 0, len(order) - 1)])
        y, x = divmod(pick, world.map.width)

        clan = self.add_clan(y, x, 0, self.new_language())
        self.add_culture(clan, 0)
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
        world.emit("humankind_begins", data={"clan": clan.name, "clan_id": clan.id, "y": y, "x": x})

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

    def forage(self, clan: Clan) -> None:
        world, p = self.world, self.p
        adults = len(self.adults(clan))
        children = len(clan.members) - adults
        need = (
            (adults * 100 + children * p.child_need_percent) * p.food_need_per_person_month // 100
        )
        if need <= 0:
            return
        harvest_percent, _mortality, storage_months, _together = self.effects(clan)
        capacity = need * storage_months
        _builders, foragers = self.crews(clan)
        # A strong forager brings home more than a weak one.
        strength = sum(50 + person.traits[0] for person in foragers)
        want = min(need + max(0, capacity - clan.food), strength * p.harvest_per_adult_month // 100)
        area = self.window(clan.y, clan.x, self.radius(clan))

        raws: dict[str, np.ndarray] = {}
        foods: dict[str, int] = {}
        for rid in self.food_ids:
            percent = harvest_percent[rid]
            if percent <= 0:
                continue
            raw = world.stocks[rid][area].astype(np.int64) * p.harvest_share_percent // 100
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
        eaten = min(clan.food, need)
        clan.food = min(clan.food - eaten, capacity)
        clan.unmet.append(100 - eaten * 100 // need)
        if len(clan.unmet) > 12:
            del clan.unmet[0]
        world.count("food.eaten", eaten)
        world.count("food.needed", need)

        starving = self.unmet_average(clan) >= 25
        if starving and not clan.famine:
            world.emit("famine", data={"clan": clan.name, "clan_id": clan.id})
        clan.famine = starving

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
        if world.roll(f"death.{band}", "person", person.id, min(base, 1.0), factors, detail=True):
            self.die(person, "hunger" if unmet >= 25 else band)
            return

        if age < p.adult_age:
            return
        if person.partner == 0:
            self.maybe_pair(person, clan)
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
        self.retired[clan.id] = clan
        del self.clans[clan.id]
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
            area = self.window(clan.y, clan.x, self.p.forage_radius)
            return bool((world.capacity[resource_id][area] > 0).any())
        if resource_id in world.map.deposit_ids:
            area = self.window(clan.y, clan.x, self.p.forage_radius + 2)
            return bool((world.map.deposit[area] == world.map.deposit_ids.index(resource_id)).any())
        return False

    def learn(self, clan: Clan, tech_id: str, discoverer: int, how: str) -> None:
        clan.techs[tech_id] = self.world.tick
        self._effects.pop(clan.id, None)
        self.dirty_clans.add(clan.id)
        self.new_discoveries.append((clan.id, tech_id, self.world.tick, discoverer, how))

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
        if (
            clan.id != culture.origin
            and sound_distance(clan.language, culture.language) >= p.people_sound_distance
        ):
            factors = [("no_kin_near", 3.0)] if not kin else []
            if clan.settled:
                factors.append(("settled", 1.5))
            if world.roll(
                "people_emerges", "group", clan.id, p.people_emerge_chance_per_year, factors
            ):
                new = self.add_culture(clan, culture.id)
                # Neighbours who by now speak more like the founders go with them.
                followers = 0
                for other in kin:
                    if sound_distance(other.language, new.language) < sound_distance(
                        other.language, culture.language
                    ):
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
        if not world.roll("people_joined", "group", clan.id, p.people_join_chance_per_year, []):
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
        for tech_id in sorted(clan.techs):
            tech = packs.technologies.get(tech_id)
            if tech is None or tech_id in needed:
                continue
            unused = any(not self.nearby(clan, resource) for resource in tech.needs_nearby)
            if not few and not unused:
                continue
            factors = [("few_keepers", 1.0)] if few else []
            if unused:
                factors.append(("out_of_use", 2.0 if few else 1.0))
            if not world.roll(
                f"forget.{tech_id}", "group", clan.id, p.knowledge_loss_chance_per_year, factors
            ):
                continue
            del clan.techs[tech_id]
            self._effects.pop(clan.id, None)
            self.dirty_clans.add(clan.id)
            self.forgotten.append((clan.id, tech_id, world.tick))
            world.count(f"tech.{tech_id}.lost")
            world.count("knowledge.lost")
            world.emit(
                "knowledge_lost",
                data={"tech": tech_id, "clan": clan.name, "clan_id": clan.id},
            )

    def clan_year(self, clan: Clan) -> None:
        world, p = self.world, self.p
        packs = world.packs
        adults = self.adults(clan)
        if not adults:
            return

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
                if world.roll(
                    f"learn.{tech_id}", "group", clan.id, p.contact_learning_chance_per_year, []
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

        self.forget(clan, adults)
        self.kinship(clan)

        hungry = self.unmet_average(clan) >= 15
        if clan.settled:
            starving = self.unmet_average(clan) >= p.abandon_hunger_percent
            if starving and world.roll(
                "abandon_settlement", "group", clan.id, p.abandon_chance_per_year, []
            ):
                self.abandon_place(clan)
        elif (
            not hungry
            and world.tick - clan.arrived >= p.settle_years * DAYS_PER_YEAR
            and any(
                packs.technologies[t].effects.enables_settlement
                for t in sorted(clan.techs)
                if t in packs.technologies
            )
            and world.roll("settle", "group", clan.id, p.settle_chance_per_year, [])
        ):
            self.settle(clan)

        if len(adults) >= self.effects(clan)[3]:
            factors = [("hungry", 2.0)] if hungry else []
            if world.roll("clan_split", "group", clan.id, p.clan_split_chance_per_year, factors):
                self.split(clan)
        elif len(adults) <= p.clan_merge_adults:
            hosts = [
                self.clans[cid]
                for cid in sorted(self.clans)
                if cid != clan.id
                and max(abs(self.clans[cid].y - clan.y), abs(self.clans[cid].x - clan.x)) <= 4
            ]
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
            area = self.window(place["y"], place["x"], self.radius(clan))
            for resource in sorted(definition.materials):
                if int(world.stocks[resource][area].sum()) < 2 * definition.materials[resource]:
                    return  # not enough material within reach
            if not world.roll("build.start", "group", clan.id, p.build_start_chance_per_month, []):
                return
            for resource in sorted(definition.materials):
                stock = world.stocks[resource][area].astype(np.int64)
                total = int(stock.sum())
                taken = stock * definition.materials[resource] // total
                world.stocks[resource][area] = (stock - taken).astype(np.int32)
                world.count(f"materials.{resource}.used", int(taken.sum()))
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

    def new_year(self) -> None:
        """Footsteps fade, and what stands in abandoned places slowly falls apart."""
        p = self.p
        self.steps = (
            self.steps.astype(np.int64) * (100 - p.steps_decay_percent_per_year) // 100
        ).astype(np.int32)
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
        site = self.best_site(clan, min_distance=3)
        if site is None:
            return
        new = self.add_clan(
            site[1], site[2], clan.id, self.drift_language(clan.language), clan.culture
        )
        new.techs = dict(clan.techs)
        for tech_id in sorted(new.techs):
            self.new_discoveries.append((new.id, tech_id, self.world.tick, 0, "inherited"))
        movers = [pid for pid in clan.members if self.persons[pid].family in leaving]
        for person_id in movers:
            person = self.persons[person_id]
            clan.members.remove(person_id)
            new.members.append(person_id)
            person.clan = new.id
            if person.partner and self.persons[person.partner].family not in leaving:
                self.persons[person.partner].partner = 0
                self.dirty_persons.add(person.partner)
                person.partner = 0
            self.dirty_persons.add(person_id)
        share = clan.food * len(movers) // max(1, len(movers) + len(clan.members))
        clan.food -= share
        new.food = share
        new.unmet = list(clan.unmet)
        self.walk(clan.y, clan.x, new.y, new.x, len(movers))
        self.dirty_clans.add(clan.id)
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
        outer = self.window(clan.y, clan.x, reach + p.forage_radius)  # judged as a wanderer
        harvest_percent, _m, _s, _t = self.effects(clan)
        value = np.zeros(world.stocks[self.food_ids[0]][outer].shape, dtype=np.int64)
        for rid in self.food_ids:
            if harvest_percent[rid] > 0:
                value += (
                    world.stocks[rid][outer].astype(np.int64)
                    * harvest_percent[rid]
                    * world.packs.resources[rid].food_value
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

        ys = np.arange(shape[0])[:, None] + y_start
        xs = np.arange(shape[1])[None, :] + x_start
        distance = np.maximum(np.abs(ys - clan.y), np.abs(xs - clan.x))
        score = score - score * distance * 3 // 100
        allowed = (distance >= min_distance) & (distance <= reach) & self.campable[outer]
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
        return sum(
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
            self.steps[y, x] += people

    def maybe_migrate(self, clan: Clan, month: int) -> None:
        world, p = self.world, self.p
        if clan.settled:
            return  # settled people stay until hunger makes them give the place up
        unmet_now = clan.unmet[-1] if clan.unmet else 0
        factors: list[tuple[str, float]] = []
        if unmet_now > 0:
            factors.append(("hunger", 1.0 + unmet_now / 5))
        if clan.settled:
            factors.append(("settled", 0.1))
        if month >= 9:
            factors.append(("winter", 0.5))
        if not world.roll("migration", "group", clan.id, p.wander_chance_per_month, factors):
            return
        site = self.best_site(clan)
        if site is None:
            return
        if unmet_now == 0 and site[0] * 100 <= self.site_score(clan) * 115:
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
        clan.y, clan.x, clan.arrived = y, x, world.tick
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
        self.new_discoveries.clear()
        self.forgotten.clear()
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
        self, state: dict[str, Any], persons: list[Person], steps: np.ndarray | None
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
                techs=dict(raw["techs"]),
                food=raw["food"],
                unmet=list(raw["unmet"]),
                arrived=raw["arrived"],
                settled=raw["settled"],
                place=raw["place"],
                famine=raw["famine"],
            )
        self.next_culture = state.get("next_culture", 1)
        self.cultures = {
            raw["id"]: Culture(
                id=raw["id"],
                name=raw["name"],
                parent=raw["parent"],
                founded=raw["founded"],
                origin=raw["origin"],
                language=dict(raw["language"]),
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
        self._effects = {}
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

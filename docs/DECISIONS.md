# Decisions and notes after the specification

## 2026-11-11: buildings and paths appear gradually

Owner request: people should slowly build buildings, and paths and roads should emerge over time.

Planned for stage 1 and 2, not part of stage 0:

- **Paths emerge from use.** Every tile counts how often it is walked on. Above a threshold a tile becomes a trodden path, which is cheaper to walk, so traffic concentrates and paths stabilise. Unused paths fade again.
- **Roads are built.** A settlement or state can upgrade a much-used path into a road, which needs a technology from the data pack, labour and materials, and upkeep.
- **Buildings take time.** A building is a construction site first, with progress that depends on available workers and materials. It can stay unfinished, decay without upkeep and become a ruin that stays on the map.
- **Data-driven.** Building types, costs, required technologies and path levels are defined in data packs.
- **Statistics.** Per tile: steps, path level, construction and decay events.

## Stage 0 implementation notes

- A year has 360 days, 12 months of 30 days, four seasons of three months.
- Stocks, elevation, temperature and moisture are integers, so results are identical on every platform.
- Regions are fixed 16 x 16 tile blocks for now. They are the scope of natural events until cultures and settlements exist.
- Biomes are part of the core for now, because world generation needs them. Resources, events and rules are pack data.
- The built-in packs live inside the Python package (`src/hiab/data/packs/`) so a `pipx` install has them.

## 2026-11-11: interface design

The owner left the design open. Direction chosen for the web view:

- **The page is the inside of the box.** The background is the sea the map floats in, so the map has no frame.
- **Signature element: the history band** under the top strip. It shows the population over the whole history of the world with a notch for every discovery. Everything else stays quiet.
- **Type:** Vollkorn for anything that is told (chronicle, names, headings), Barlow Semi Condensed for anything that is counted (numbers, labels, controls). Both are bundled, nothing is loaded from the internet.
- **Colour** comes from the map's own pigments: sea, chalk, ochre, clay. Ochre marks what matters, clay is reserved for the gravest events.
- **Structure:** three views (map, numbers, clans). On wide screens the chronicle is a ledger docked over the map, on phones a sheet that slides up from the bottom, with a tab bar in thumb reach.
- **Charts** are hand-drawn SVG with a crosshair readout, a legend for two series and a table view. The two series colours are checked as a pair for colour-vision separation and contrast against the panel; do not change one alone.
- Not done on purpose: card grids with shadows, uppercase labels, monospace data labels, decorative motion.

## 2026-11-12: activities per person

The owner wants a life simulation: people who visibly do things. Decision: the month stays the unit of the simulation, but inside it every adult gets one activity and one target tile. No extra dice: who does what follows from traits and yields, so the world log does not grow.

- `Person.activity` is a food resource id, `build:<building>`, `search`, or empty for children. `Person.work` counts months per kind of work over a life.
- With an open site and enough food, `builders_share_percent` of the adults build, most skilful first. Building progress is their skill, no longer the head count of all adults; building work in `buildings.yaml` was cut to a third to keep the pace.
- Foragers are split over the foods in proportion to what each yields this month; each crew walks to the richest tile of its food. Harvest capacity is the foragers' vigor.
- The map shows one figure per living person walking to that target. The steps on screen are display only and never stored.
- Not yet: daily routines, individual skills that grow with practice, tools carried by a person. Activities are the place to hang those on later.

## 2026-11-12: leaders and chiefdoms

- A clan's leader is chosen without dice: twice sociability plus vigor, craft and age (capped at 45), ties to the lowest id. Leadership is a fact of who is there, not luck; the dice decide what the leader achieves.
- A chiefdom is the first binding above the clan. It is named after the seat's place. Clans join one a year, so a realm grows over generations rather than at once.
- Rule is fragile at the start: succession is the moment clans may leave (`realm_break_on_succession`), and a seat left alone after a succession ends the chiefdom.
- Chiefdoms keep their clans inside their people (factor 0.2 on drifting apart). This is how large peoples arise, as the owner asked, instead of by raising `people_max_clans`.
- Realms and peoples are shown one at a time on the map, so realms reuse the twelve fixed colours, stepping five places per id so that neighbours founded close in time differ.
- Consolidation (owner's wish: many groups early, fewer and larger later, as in history) works through rule, not by lowering split chances: assimilation into the seat's people, daughter clans staying under the same rule, and weak chiefdoms submitting to larger ones at succession. Wars will add conquest.

## 2026-11-13: war

- Only chiefdoms make war; free clans are drawn in by joining, not by force. A war is one attacker against one defender, with one battle a year at the attacker's turn of the year.
- Battle odds are the plain strength ratio, logged as one roll; the defender's own ground counts 120 percent. Fighting strength is data (`war_percent` on technologies).
- Who falls is decided, not rolled: men of fighting age at the front, the weakest first. The number follows the size of each side.
- The seat falls last. A lost battle costs the clan nearest the winner; only a chiefdom reduced to its seat is conquered whole.

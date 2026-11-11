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

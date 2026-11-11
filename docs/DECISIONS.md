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

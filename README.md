# Humankind in a Box

**DE:** Eine selbst gehostete Idle-Zivilisation. Eine Welt lebt auf deinem Server von der Steinzeit an alleine weiter und schreibt jedes Mal eine andere Geschichte. Du schaust nur zu.

**EN:** A self-hosted idle civilization. A world lives on your server, starting in the Stone Age, and writes a different history every time. You just watch.

Inspired by [Letopis](https://github.com/leppermesiah/letopis).

## Status

Stage 0 (foundation). There are no people yet: the world has terrain, climate, seasons, renewable stocks and natural events. What exists is the deterministic core everything else builds on.

- One seed, one history: the same seed always produces the same world, on Linux, Windows and macOS.
- All content (resources, events, rules) lives in YAML data packs, not in code.
- Every dice roll is logged with its rule, factors, chance and result, and counted for statistics.

## Quick start

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run hiab simulate --years 500 --seed 42 --out a.sqlite
uv run hiab simulate --years 500 --seed 42 --out b.sqlite
uv run hiab verify a.sqlite b.sqlite        # both worlds are identical
uv run hiab events --db a.sqlite --lang en  # read the chronicle
uv run hiab run                             # run a world in real time, Ctrl+C saves and stops
```

## Commands

| Command | Purpose |
| --- | --- |
| `hiab run` | Run the world at its pace and keep saving it |
| `hiab new-world --seed N` | Archive the active world and start a new one |
| `hiab simulate --years N --seed S --out FILE` | Run as fast as possible into a database file; continues if the file has a world |
| `hiab verify A B` | Compare two database files table by table |
| `hiab events` | Print the chronicle in German or English |
| `hiab check-packs` | Load and validate the data packs |

## Configuration

Four layers, later wins: built-in defaults, `hiab.yaml` in the data folder, `HIAB_*` environment variables, command line options. See `src/hiab/config.py` for all settings.

Data packs: built-in packs live in `src/hiab/data/packs/`. A folder `packs/<name>/` in the data folder replaces a built-in pack of the same name, and `packs/local/overrides.yaml` overrides single values:

```yaml
rules.drought.base_chance_per_year: 0.08
```

## Development

```bash
uv run pytest            # all tests
uv run pytest -m "not slow"
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The specification is in `docs/`. Rules for contributors, human or AI, are in `CLAUDE.md`.

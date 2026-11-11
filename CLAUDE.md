# Humankind in a Box (HIAB)

Self-hosted idle civilization simulation. The server simulates, the browser shows. The owner speaks German; talk to him in German. Code, identifiers, pack keys, comments and commits are English. UI texts and templates exist in German and English.

The full specification is `docs/SPEC.md` (German). Follow-up decisions are in `docs/DECISIONS.md`, the current state in `docs/STATUS.md`. Where they contradict the specification, the newer documents win.

## Rules that must not be broken

1. **Solo first.** The world runs completely without input. No feature may require an intervention.
2. **Deterministic.** Same seed plus same logged changes gives identical database contents on every platform. In the simulation: no wall-clock time, no `hash()`, no iteration over unsorted dicts or sets, no threads, no floating point `sin`/`exp`/`pow`. Prefer integer arithmetic. Floats are fine for chances as long as they only see `+ - * /` and comparisons.
3. **Every dice roll goes through `World.roll` or `World.draw_int`.** They log the decision to `world_log` and count it in `metrics`. Never call a random generator directly from a subsystem. A new subsystem gets its own named stream in `RandomStreams`.
4. **Content is data.** The core knows no concrete resource, technology or event. Those live in data packs (`src/hiab/data/packs/`), validated on load with messages a user can act on.
5. **No LLM in the simulation.** An LLM may only narrate facts that already happened.
6. **Native and container equally.** Nothing Linux-only. Paths come from the configuration.
7. **Statistics and logging are core features.** New systems count what they do (`World.count`) and emit events (`World.emit`) from day one.
8. **German and English from the start.** Events are stored language-neutral and turned into text only for display.
9. **Nothing wall-clock in the database**, or `hiab verify` breaks.
10. **Secrets** (API token, LLM key) never appear in logs or output. Use `Settings.public_dict()`.

## Layout

- `src/hiab/config.py`: settings in four layers.
- `src/hiab/logging_setup.py`: program log (JSON lines). The world log is in the database.
- `src/hiab/packs.py`: pack schema, loading, overrides.
- `src/hiab/sim/`: `rng.py` (streams), `worldgen.py` (map), `engine.py` (World, tick loop, rolls).
- `src/hiab/db/store.py`: SQLite schema, migrations, save and load, table digests.
- `src/hiab/worker.py`: pacing against real time, `simulate` for fast runs.
- `src/hiab/cli.py`: the `hiab` command.

## Working here

- `uv sync`, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy`.
- Schema changes are new entries in `MIGRATIONS`, never edits of old ones once released. New tables that hold world content must be added to `CONTENT_TABLES`.
- Any change to the simulation must keep `tests/test_determinism.py` green, including save, load and continue.
- Open points (license, name checks) are the owner's to decide. Ask instead of deciding.

# Stand

## 2026-11-11

- Stufe 0 (Fundament) ist umgesetzt, siehe Pull Request 1.
- Noch offen: Lizenz-Entscheidung, Prüfung von PyPI-Name und Domain.
- Nächster Schritt: Stufe 1 aus dem Bauplan in `docs/SPEC.md`, Abschnitt 16.

## Was Stufe 0 enthält

- CLI `hiab`: `run`, `new-world`, `simulate`, `verify`, `events`, `check-packs`.
- Konfiguration in vier Ebenen, Programm-Log als JSON-Zeilen.
- Zufallsströme je Teilsystem, Weltgenerator rein mit Ganzzahlen.
- Datenpakete mit Schema-Prüfung und `packs/local/overrides.yaml`. Basispaket mit vier Beständen (Wild, Fisch, Holz, Boden), sechs Vorkommen und sechs Naturereignis-Regeln.
- Tick-Schleife: Klimadrift, saisonale Regeln je Region, Nachwachsen der Bestände.
- Jeder Wurf läuft über `World.roll` oder `World.draw_int`, wird in `world_log` protokolliert und in `metrics` gezählt.
- SQLite mit Migrationen, Speichern und Laden.
- Noch nicht enthalten: Menschen, API-Server, Frontend, Event-Kanal.

## Abweichungen von der Spezifikation

- Eingebaute Datenpakete liegen in `src/hiab/data/packs/` statt in `packs/` im Wurzelverzeichnis, damit eine pipx-Installation sie enthält.
- Biome sind vorerst Teil des Kerns, weil der Weltgenerator sie braucht.
- Regionen sind vorerst feste Blöcke von 16 x 16 Kacheln und dienen als Geltungsbereich der Naturereignisse, bis es Kulturen und Siedlungen gibt.
- Ein Jahr hat 360 Tage, zwölf Monate zu 30 Tagen.
- Regeln haben zusätzlich ein Feld `month` (Monat der Prüfung).

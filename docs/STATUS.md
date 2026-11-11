# Stand

## 2026-11-11

- Stufe 0 (Fundament) ist gemergt.
- Stufe 1a (Menschen) ist umgesetzt: Personen, Familien, Clans, Nahrungssuche, Hunger, Wanderung, Entdeckungen, Wissensweitergabe, Clan-Spaltung und -Verschmelzung, erste Siedlungen.
- Als Nächstes Stufe 1b: API-Server, Event-Kanal, Kartenansicht, Grundkacheln der Statistik, Docker-Image.
- Noch offen: Lizenz-Entscheidung, Prüfung von PyPI-Name und Domain, Test der Grafik-Prompts.

## Was es gibt

- CLI `hiab`: `run`, `new-world`, `simulate`, `verify`, `events`, `status`, `check-packs`.
- Konfiguration in vier Ebenen, Programm-Log als JSON-Zeilen.
- Zufallsströme je Teilsystem, Weltgenerator rein mit Ganzzahlen.
- Datenpakete mit Schema-Prüfung und `packs/local/overrides.yaml`. Das Basispaket enthält fünf Bestände (Wildpflanzen, Wild, Fisch, Holz, Boden), sechs Vorkommen, sechs Naturereignis-Regeln, zehn Entdeckungen und die Lebensparameter in `life.yaml`.
- Tick-Schleife: Klimadrift, saisonale Regeln je Region, Nachwachsen der Bestände, monatlicher Schritt der Gesellschaft.
- Jeder Wurf läuft über `World.roll` oder `World.draw_int`, wird in `world_log` protokolliert und in `metrics` gezählt.
- SQLite mit Migrationen, Speichern und Laden, inklusive Personen, Gruppen, Entdeckungen, Orten und Trittzählern je Kachel.

## Wie die Menschen funktionieren

- **Start:** Acht Familien lagern gemeinsam an einem guten Platz.
- **Nahrung:** Ein Clan sammelt jeden Monat im Umkreis seines Lagers. Wie viel er aus Pflanzen, Wild und Fisch herausholt, hängt von seinem Wissen ab. Was fehlt, wird als Hunger vermerkt.
- **Leben:** Einmal im Jahr, im Geburtsmonat, wird für jede Person gewürfelt: Tod (nach Alter, Hunger, Wissen, Konstitution), Paarbildung, Geburt. Kinder erben die Merkmale der Eltern mit kleiner Abweichung.
- **Wandern:** Hunger erhöht die Chance, weiterzuziehen. Gesucht wird der beste erreichbare Platz, andere Lager in der Nähe schrecken ab. Die begangenen Kacheln werden gezählt, daraus entstehen später Wege.
- **Wissen:** Entdeckungen entstehen aus Voraussetzungen, Umgebung und Lage des Clans. Benachbarte Clans lernen voneinander.
- **Clans:** Zu große Clans spalten sich entlang der Familien, winzige schließen sich Nachbarn an, leere sterben aus. Jede Abspaltung bekommt eine leicht veränderte Sprache für ihre Namen.
- **Siedlungen:** Wer feste Hütten kennt, lange genug satt an einem Ort bleibt, kann sesshaft werden. Hunger vertreibt wieder.

## Kalibrierung, Stand heute

Zehn Seeds über 400 Jahre auf einer Karte von 64 x 64 Kacheln: alle zehn Welten überleben, 570 bis 930 Menschen in 39 bis 65 Clans, zwei bis sechs von zehn Entdeckungen gemacht, rund 90 Prozent des Nahrungsbedarfs gedeckt. 500 Jahre rechnen in etwa 25 Sekunden.

## Bekannte Schwächen

- Siedlungen werden zu oft gegründet und wieder aufgegeben.
- Geburten, Tode und Wanderungen erzeugen sehr viele Ereignisse niedriger Wichtigkeit. Die Verdichtung alter Ereignisse fehlt noch.
- Wissensverlust gibt es noch nicht (Stufe 2).
- Familien sind bisher nur eine Haushaltsnummer an der Person, keine eigene Gruppe in der Datenbank.
- Ab einigen tausend Personen wird die Simulation langsam, das Zusammenfassen entfernter Gruppen fehlt noch.

## Abweichungen von der Spezifikation

- Eingebaute Datenpakete liegen in `src/hiab/data/packs/` statt in `packs/` im Wurzelverzeichnis, damit eine pipx-Installation sie enthält.
- Biome sind vorerst Teil des Kerns, weil der Weltgenerator sie braucht.
- Regionen sind vorerst feste Blöcke von 16 x 16 Kacheln und dienen als Geltungsbereich der Naturereignisse.
- Ein Jahr hat 360 Tage, zwölf Monate zu 30 Tagen.
- Regeln haben zusätzlich ein Feld `month` (Monat der Prüfung).
- Bestände wachsen logistisch nach: Ein gesunder Bestand erholt sich am schnellsten, ein erschöpfter nur langsam. Dadurch hat Übernutzung Folgen.
- Die Würfe pro Person und Jahr (Tod, Paarbildung, Geburt) werden immer gezählt, aber nur bei `HIAB_WORLD_LOG=full` einzeln protokolliert.

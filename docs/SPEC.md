# Humankind in a Box (HIAB) – Spezifikation

Stand: 2026-11-11. Konsolidierte Fassung des Konzeptdokuments, gedacht als Arbeitsgrundlage für die Umsetzung.
Vorbild: https://github.com/leppermesiah/letopis (Idle-Zivilisation, Server simuliert, Browser zeigt an).

Kurzform: HIAB. Repo: `fgrfn/humankind-in-a-box`. Python-Paket: `humankind-in-a-box`, CLI-Befehl: `hiab`. Umgebungsvariablen: `HIAB_*`.

Nachträge und Abweichungen stehen in `docs/DECISIONS.md` und `docs/STATUS.md`. Bei Widerspruch gelten diese, weil sie neuer sind.

## 1. Vision

Eine selbst gehostete Welt, die von der Steinzeit an alleine weiterlebt und jedes Mal eine andere Geschichte schreibt. Man schaut rein, liest nach, was passiert ist, und kann optional ganz leicht mitmischen.

## 2. Verbindliche Leitplanken

1. **Solo zuerst.** Die Welt läuft ohne jede Eingabe vollständig durch. Kein Feature darf einen Eingriff voraussetzen.
2. **Eingriffe sind optional**, standardmäßig aus, und nur ein Schubs, nie Steuerung.
3. **Emergent statt geskriptet.** Keine feste Epochen-Leiter. Regeln legen Bedingungen und Wahrscheinlichkeiten fest, der Seed würfelt, ob und wann etwas passiert.
4. **Deterministisch.** Gleicher Seed plus gleiche protokollierte Änderungen (Eingriffe, Paketversionen, Einstellungen) ergibt bit-identische Geschichte. Ein Zufallsgenerator pro Welt, kein Zugriff auf Systemzeit in der Simulation, keine Abhängigkeit von Dict-, Set- oder Thread-Reihenfolge.
5. **Kein LLM in der Simulation.** Das LLM erzählt nur. Seine Texte fließen nie in die Simulation zurück. Ohne Key greifen Textvorlagen.
6. **Inhalte sind Daten.** Der Kern kennt keine konkrete Technologie und keinen konkreten Rohstoff. Alles Inhaltliche liegt in Datenpaketen (YAML), erweiterbar und im Betrieb patchbar.
7. **Nativ und im Container gleichwertig.** Dasselbe Programm läuft auf Linux, Windows, macOS und als Docker-Image. Keine Linux-only-Abhängigkeiten, Pfade nur aus der Konfiguration.
8. **Statistik und Logging sind Kernfunktion ab Stufe 0**, so detailliert wie möglich.
9. **Zweisprachig von Anfang an:** Deutsch und Englisch. Ereignisse werden sprachneutral gespeichert und erst bei der Anzeige zu Text.
10. **Eine HTTP-API** als einzige Schnittstelle, auch fürs eigene Frontend. Kein MQTT.
11. **Keine externe Datenbank, kein Pflicht-Cloud-Dienst.**

## 3. Getroffene Entscheidungen

| Thema | Entscheidung |
| --- | --- |
| Name | Humankind in a Box, HIAB |
| Setting | Reale Menschheitsgeschichte als Vorbild (echte Tiere, Rohstoffe, Erfindungen). Kulturen, Sprachen, Namen entstehen in jeder Welt neu. |
| Blickwinkel | Isometrisch wie Letopis |
| Raster | Quadrate, als Rauten 2:1 gezeichnet |
| Laufzeit | Standardtempo rund drei Monate echte Zeit bis zur Gegenwart, danach offen weiter in eine selbst entwickelte Zukunft |
| LLM | Drei Adapter: lokal (Ollama bzw. OpenAI-kompatible Adresse), OpenAI, Claude. Jeweils per API-Key. Lokal ist Standard. |
| Eingriffe | Optional, standardmäßig aus |
| Betrieb | Python-Paket und Docker-Image |
| Sprachen | DE und EN |

Offen: Prüfen, ob PyPI-Name und Domain frei sind. Lizenz: Vorschlag MIT, Repo zunächst privat.

Konvention für die Umsetzung: Code, Bezeichner, Schlüssel in Datenpaketen, Commits und Code-Kommentare auf Englisch. Oberfläche und Textvorlagen DE und EN.

## 4. Stack und Architektur

| Baustein | Wahl | Grund |
| --- | --- | --- |
| Simulation | Python 3.13, NumPy für Kachel-Raster | Schnell genug für Tages-Ticks, gut testbar |
| API | FastAPI, Uvicorn | OpenAPI automatisch, WebSocket und SSE eingebaut |
| Datenbank | SQLite im WAL-Modus | Eine Datei, ein Schreiber (Worker), viele Leser (API) |
| Frontend | React, TypeScript, Vite | Fertig gebaut im Python-Paket enthalten |
| Karte | PixiJS (WebGL) | Tausende Sprites flüssig |
| Start | Ein Befehl `hiab run` startet Worker und API | Kein Supervisor, kein Compose nötig |

Ein Programm, zwei Prozesse:

- **Simulations-Worker:** Tick-Schleife, hält den Weltzustand im Speicher, ist der einzige Schreiber der Datenbank, führt optional den Chronist-Job aus (einziger Baustein, der nach außen ruft).
- **API-Server:** REST, WebSocket, SSE, liefert das Frontend aus, liest aus SQLite.
- **Event-Kanal** zwischen beiden über eine lokale Socket-Verbindung (plattformneutral), für Live-Ereignisse und Kartendeltas. Eine langsame Anfrage darf nie den Tick bremsen.

Außerhalb: Browser (React, PixiJS), beliebige API-Konsumenten (z. B. Home Assistant per REST-Sensor, Skripte), Webhook-Ziele, optional ein LLM-Anbieter.

**Persistenz.** Ereignisse laufend, voller Zustand alle paar Minuten und beim Herunterfahren. Ein Absturz kostet höchstens diese Minuten.

**Snapshots und Zeitreise.** Zu festen Weltzeiten (Startwert alle 25 Weltjahre) kompletter Zustand komprimiert als Snapshot. Zurückspulen lädt den nächstfrüheren Snapshot lesend; Zwischenzeitpunkte lassen sich dank Determinismus nachrechnen.

**Forks.** Ein Fork kopiert einen Snapshot in eine neue Welt mit eigenem Zufallsstrom. Mehrere Welten nebeneinander möglich, Standard ist eine aktive Welt.

**Startwege.**

| Weg | Start | Daten |
| --- | --- | --- |
| Nativ | `pipx install humankind-in-a-box`, dann `hiab run` | Standardordner des Betriebssystems oder `--data` |
| Dienst unter Linux | Mitgelieferte systemd-Unit | `/var/lib/hiab` |
| Docker | `docker run -p 2222:2222 -v hiab:/data ghcr.io/fgrfn/humankind-in-a-box` | Volume `/data` |

Tests laufen in CI auf Linux, Windows und macOS. Später zusätzlich ein Unraid-Template.

## 5. Simulationskern

- **Tick:** ein Tick ist ein Welttag. Ticks pro echter Minute regelt ein Tempo-Profil (frühe Zeit schnell, später langsamer). Nach einem Neustart wird standardmäßig nicht nachgerechnet (umschaltbar).
- **Welt:** Quadratraster, per Noise erzeugt: Höhe, Wasser, Flüsse, Klimazonen, Biome, Rohstoffvorkommen. Jahreszeiten und langsame Klimaschwankungen über Jahrhunderte.
- **Ökologie:** Jede Kachel hat Bestände (Wild, Fisch, Holz, Bodenfruchtbarkeit). Übernutzung senkt sie, Ruhe lässt sie nachwachsen. Daraus entstehen Hunger, Umzug und Konflikte.
- **Menschen:** Jede Person einzeln: Name, Eltern, Merkmale (vererbt mit kleiner Mutation), Fähigkeiten, Beziehungen, Zugehörigkeit. Ab einigen tausend Personen werden entfernte Gruppen zusammengefasst gerechnet, beobachtete Personen bleiben einzeln.
- **Gruppenentscheidungen:** einfache Bedürfnis-Gewichtung (Nahrung, Sicherheit, Platz, Neugier), keine Skripte.
- **Technologien:** Graph aus Entdeckungen mit Voraussetzungen. Einflussgrößen: Umgebung (Boote nur mit Wasser und Holz), Bedarf (Druck erhöht die Chance), Wissen (bestehende Entdeckungen, begabte Personen), Kontakt (Wissen wandert über Handel, Heirat, Abspaltung). Wissen kann verloren gehen, wenn es niemand mehr ausübt.
- **Epochen** sind nur ein abgeleitetes Etikett aus dem Wissensstand einer Kultur.

## 6. Gesellschaftsstufen

Jede Stufe hat Bedingungen und eine jährliche Chance. Jede Stufe kann wieder zerfallen.

| Stufe | Wird möglich, wenn | Neu auf dieser Stufe | Zerfällt durch |
| --- | --- | --- | --- |
| 1 Person und Familie | Start der Welt | Bedürfnisse, Paarbindung, Kinder, Vererbung, Lernen von den Eltern | Tod, Hunger |
| 2 Clan | Mehrere verwandte Familien teilen ein Lager | Gemeinsame Jagd, Wandern, geteiltes Wissen, Totem | Streit, Übergröße (Spaltung), Aussterben |
| 3 Siedlung | Nahrung reicht am Ort ganzjährig (Fischgrund, Ackerbau, Vorratshaltung) | Vorräte, Berufe, Bauten, Besitz | Erschöpfter Boden, Seuche, Überfall |
| 4 Volk | Mehrere Siedlungen gleicher Herkunft bleiben in Kontakt | Gemeinsame Kultur und Sprache, Feste, Heiratsnetz, Tauschhandel | Entfernung und Zeit: Sprache driftet, Volk teilt sich |
| 5 Herrschaft | Überschuss, einige hundert Einwohner, Bedrohung oder Verteilungsstreit | Anführer, Abgaben, Krieger, Recht, Nachfolge | Nachfolgestreit, Hungeraufstand, Niederlage |
| 6 Staat | Eine Herrschaft bindet mehrere Siedlungen und kann sie verwalten (Schrift oder Vergleichbares) | Grenzen, Steuern, Straßen, Heer, Regierungsform | Bürgerkrieg, Abspaltung, Eroberung, leere Kassen |
| 7 Reich | Ein Staat beherrscht fremde Völker oder ferne Gebiete, Fernreise möglich | Kolonien, Vasallen, Fernhandel, Leitkultur | Überdehnung, Unabhängigkeit, Zerfall |
| 8 Weltordnung | Mehrere Reiche dauerhaft über Kontinente in Kontakt | Bündnissysteme, Weltmärkte, Verträge, später Raumfahrt | Große Kriege, Kollaps |

**Regelformat (Beispiel, Zahlen sind Startwerte):**

```yaml
transition: settlement_to_rule
requires:
  population_min: 300
  stock_months_min: 6
base_chance_per_year: 0.01
factors:
  neighbour_threat: 3.0
  famine_year: 2.0
  outstanding_person_present: 2.0
  culture_value_equality_high: 0.5
result:
  rule_form: weighted_by_culture_values   # council of elders, chief, priest
```

Bedrohte Siedlung im Hungerjahr: 6 Prozent pro Jahr. Friedliche Kultur mit starkem Gleichheitsideal: 0,5 Prozent. Manche Welten bekommen nie einen Staat.

**Beziehungen zwischen Gruppen.** Jedes Paar benachbarter Gruppen hat einen Beziehungswert aus Verwandtschaft, Handel, Glaube, alten Kränkungen und Konkurrenz um dieselben Vorkommen.

- Handel entsteht, wenn zwei Gruppen Unterschiedliches besitzen und ein Weg existiert. Routen bringen Wohlstand, Wissen und Krankheiten.
- Bündnis und Heirat heben den Wert, vererben aber Ansprüche und damit spätere Nachfolgestreite.
- Konflikt: Auslöser Knappheit, Grenzstreit, Raub, Nachfolge, Glaube. Eskalation Überfall, Fehde, Krieg.
- Kriegsausgang gewürfelt aus Zahl, Ausrüstung, Gelände, Führung, Versorgung. Folgen: Gebietswechsel, Tribut, Vertreibung, Verschmelzung, Unabhängigkeit.
- Darstellung: Ereignisse, Frontverläufe und Zahlen, keine drastischen Bilder.

**Auf jeder Stufe wirksam:** Krankheiten (Dichte, Tierhaltung, Handelswege, Immunität), Katastrophen (Dürre, Flut, Vulkan, Kältephase), Glaube (Ausbreitung, Spaltung, Legitimation), Migration, Wissensverlust, herausragende Personen.

**Kalibrierung.** Ein Testlauf rechnet hundert Seeds im Schnelldurchlauf und zählt, wie viele Welten welche Stufe erreichen. Ziel: die meisten bilden Völker, viele Staaten, einige Reiche, ein paar scheitern.

## 7. Datenpakete und offene Zukunft

- **Inhalt eines Pakets:** Rohstoffe, Technologien (Voraussetzungen, Auslöser, Effekte), Gebäude, Berufe, Tiere und Pflanzen, Ereignistypen, Übergangsregeln, Textvorlagen DE/EN, Sprite-Zuordnung.
- **Generisch:** Ein Rohstoff ist eine Liste von Eigenschaften (Vorkommen, erneuerbar, Lagerfähigkeit, Verwendungen). Feuerstein passt ins selbe Schema wie Helium-3.
- **Schema-Prüfung** beim Laden, verständliche Fehlermeldungen im Programm-Log.
- **Patchen im Betrieb:** Neue Paketversion wird ab dem aktuellen Tick aktiv. Die Welt speichert, ab wann welche Version galt.
- **Lokale Overrides:** `packs/local/overrides.yaml` überschreibt einzelne Werte, ohne das Paket anzufassen.
- **Basispaket:** Steinzeit bis Gegenwart.
- **Zukunft in drei Schichten:** (1) nahe Zukunft als handgeschriebenes Paket (Fusion, Orbitalstationen, Rohstoffabbau im All); (2) ferne Zukunft erzeugt: ist der Graph ausgeschöpft, erzeugt die Welt neue Technologien und Rohstoffe aus Regelvorlagen (bestehendes Wissen plus ungedeckter Bedarf plus verfügbare Vorkommen), Namen aus Vorlagen oder optional vom LLM; (3) jede erzeugte Technologie wird einmalig in der Welt gespeichert und gehört fest zu ihr, damit alles reproduzierbar bleibt.
- **Weitere Welten** (Mond, Planeten) sind weitere Karten mit eigenem Rohstoffpaket, verbunden über Reisewege.

## 8. Kultur, Sprache, Chronik

- Kultur ist ein Datensatz pro Gruppe, wird bei Spaltung kopiert und driftet danach.
- **Sprache:** Lautvorrat und Silbenregeln je Kultur. Namen und Ortsnamen werden daraus erzeugt. Nach Spaltungen verschieben sich Laute.
- **Ortsnamen aus Ereignissen**, in der Sprache der Kultur plus Bedeutung als Übersetzung.
- **Glaube und Bräuche:** kleine Wertesets, die Entscheidungen leicht gewichten.
- **Mythen:** herausragende Personen und Katastrophen werden zu Sagen.
- **Chronik:** jedes Ereignis strukturiert (Typ, Tick, Ort, Beteiligte, Wichtigkeit, Daten). Ansichten: Live-Ticker, „Während du weg warst“, Chronik je Person, Gruppe, Ort.

### LLM-Chronist (optional)

Ein Hintergrund-Job bündelt wichtige Ereignisse eines Zeitraums und lässt Text schreiben: Sagen, Nachrufe, Generationen-Zusammenfassung, Wochenzeitung. Auswahl über `HIAB_LLM_PROVIDER`. Tagesbudget in Tokens. Jede Geschichte in beiden Sprachen. Nach der Antwort prüft der Worker, ob alle genannten Namen in den Fakten vorkommen; wenn nicht, Text verwerfen und Vorlage nehmen.

Prompt (fest):

```text
You are the chronicler of a simulated world. You receive a JSON object with:
  "kind"      what to write: saga | obituary | chronicle | newspaper
  "language"  de or en
  "voice"     the culture telling the story: values, faith, taboos, known_concepts
  "facts"     a list of events with id, year, season, place, people, traits, causes

Rules:
1. Use only the facts given. Never invent people, places, deaths, battles, discoveries,
   dates or causes that are not in the facts.
2. You may add atmosphere: weather that fits the given season, how people might have
   told the story, feelings that fit the listed traits.
3. Keep every name exactly as written. Do not translate names. If a meaning is provided,
   you may mention it once.
4. Write from the point of view and beliefs of the culture in "voice". Events marked as
   interventions appear as omens or fate, never as a player or an outside hand.
5. Use no words or ideas the culture does not know. Check "known_concepts".
6. State war and death plainly, without graphic detail.
7. Length: saga 120 to 200 words, obituary 60 to 100 words, chronicle 1 to 2 sentences,
   newspaper one headline and 3 short items.
8. If the facts are too thin for the requested kind, write a shorter text instead of
   filling gaps.
9. Write in the requested language. Answer with JSON only:
   {"title": "...", "text": "...", "used_event_ids": [...]}
```

## 9. Optionale Eingriffe

Standard `HIAB_INTERVENTIONS=off`. Eingeschaltet: „Gunst“, Startwert ein Punkt pro echtem Tag, maximal drei auf Vorrat, unbenutzte verfällt.

| Eingriff | Wirkung | Kosten |
| --- | --- | --- |
| Regen oder Dürre | Verschiebt die Fruchtbarkeit einer Region für eine Saison | 1 |
| Traum | Erhöht bei einer Person kurzzeitig Neugier oder Mut | 1 |
| Wanderer | Schickt eine fremde Person mit einer zufälligen Fertigkeit vorbei | 2 |
| Omen | Macht einen Ort für eine Kultur heilig oder gemieden | 2 |
| Fund | Legt ein Rohstoffvorkommen in Reichweite frei | 3 |

Regeln: Ein Eingriff ändert nur Wahrscheinlichkeiten oder Startbedingungen, nie direkt ein Ergebnis. Niemand kann getötet, keine Entdeckung erzwungen werden. Jeder Eingriff steht mit Tick in der Chronik und im Protokoll, damit Nachspielen stimmt.

## 10. Konfiguration

Vier Ebenen, die spätere überschreibt die frühere: eingebaute Standardwerte, `hiab.yaml` im Datenordner, Umgebungsvariablen `HIAB_*`, Startparameter. Laufzeit-Einstellungen zusätzlich über Oberfläche und API.

| Bereich | Einstellungen | Änderbar |
| --- | --- | --- |
| System | Port (Standard 2222), Bind-Adresse, Datenordner, Zeitzone, Standardsprache, API-Token, Lesen ohne Token im LAN | Nur beim Start |
| Logging | Log-Stufe je Baustein, Dateirotation, Tiefe des Welt-Logs, Aufbewahrung in Weltjahren | Im Betrieb |
| Neue Welt | Seed, Kartengröße, Landanteil, Klima, Zahl der Startfamilien, Datenpakete und Versionen | Nur beim Anlegen |
| Laufende Welt | Tempo-Profil, Pause, Snapshot-Abstand, Nachrechnen nach Ausfall, Verhalten bei Aussterben (archivieren und neu starten oder anhalten) | Im Betrieb |
| Eingriffe | An/aus, Gunst pro Tag, Vorratsgrenze, erlaubte Arten | Im Betrieb |
| Erzählung | Anbieter, Adresse, Key, Modell, Tagesbudget, Textarten, Sprachen | Im Betrieb |
| Benachrichtigungen | Webhook-Ziele, Filter | Im Betrieb |
| Statistik | Messabstand, Aufbewahrung der Detailzähler, Export | Im Betrieb |
| Regeln | `packs/local/overrides.yaml` | Im Betrieb, ab aktuellem Tick |
| Anzeige | Sprache, Design, Kachel-Anordnung, Wandtablet-Modus | Je Browser |

Bekannte Variablen: `HIAB_PORT`, `HIAB_DATA`, `HIAB_SEED`, `HIAB_PACE`, `HIAB_INTERVENTIONS`, `HIAB_API_TOKEN`, `HIAB_LOG_LEVEL`, `HIAB_WORLD_LOG`, `HIAB_LLM_PROVIDER`, `HIAB_LLM_BASE_URL`, `HIAB_LLM_KEY`, `HIAB_LLM_MODEL`, `TZ`.

Änderungen an einer laufenden Welt werden mit Tick protokolliert. Token und Keys nur per Datei oder Variable setzbar, nie über Oberfläche oder API auslesbar, nie im Log.

## 11. Logging

Zwei getrennte Protokolle, beide mit Welt-ID und Tick.

**Programm-Log.** Strukturierte JSON-Zeilen auf stdout, zusätzlich rotierende Datei unter `<data>/logs`. Stufen DEBUG bis ERROR, je Baustein (worker, api, chronicler, packs). Inhalt: Start/Stopp, Paketversionen und Prüffehler, Dauer von Speichern und Snapshots, Warnung bei langsamen Ticks, API-Fehler, Webhook-Zustellungen, LLM-Aufrufe mit Tokens und Dauer. Zugriff: `GET /health`, `GET /system/logs` (Token), Systemseite in der Oberfläche.

**Welt-Log.**

| Ebene | Inhalt | Aufbewahrung |
| --- | --- | --- |
| Chronik | Wichtige Ereignisse | Dauerhaft, Tabelle `events` |
| Entscheidungen | Jede gewürfelte Regel mit Regelname, Faktoren, Chance und Wurf | Ringspeicher `world_log`, Standard die letzten 50 Weltjahre |
| Vollprotokoll | Jede Handlung jeder Person | Nur zur Fehlersuche, nur für abonnierte Personen oder Gruppen |

`HIAB_WORLD_LOG` = `chronicle` | `decisions` (Standard) | `full`.

Daraus entsteht in der Oberfläche der Knopf **„Warum ist das passiert?“** an jedem Ereignis: Regel, Faktoren, Chance, Wurf.

## 12. Datenmodell

Alles hängt an `world_id`.

| Tabelle | Inhalt | Wichtigste Felder |
| --- | --- | --- |
| `worlds` | Welt oder Fork | seed, parent_world, fork_tick, tick, status |
| `tiles` | Karte | x, y, elevation, biome, water, stocks (game, fish, wood, soil), resource |
| `persons` | Jede Person | name, born, died, mother, father, group, traits, skills |
| `groups` | Familie bis Reich | type, parent_group, culture, place, founded, dissolved |
| `cultures` | Sprache, Glaube, Bräuche | parent_culture, sound_rules, values |
| `discoveries` | Wer weiß was seit wann | culture, technology, tick, discoverer, lost_tick |
| `places` | Benannte Orte | tile, name, meaning, cause_event |
| `events` | Chronik-Rohdaten | tick, type, place, participants, importance, data (JSON) |
| `world_log` | Entscheidungen mit Würfen | tick, rule, factors, chance, roll, outcome |
| `metrics` | Zeitreihen | tick, key, scope_type, scope_id, value |
| `stories` | Erzählte Texte | period, kind, language, text, source (template oder llm), event_ids |
| `interventions` | Eingriffe | tick, kind, target, cost |
| `settings_log` | Laufzeit-Änderungen | tick, key, old, new |
| `pack_versions` | Welche Paketversion ab wann | tick, pack, version |
| `snapshots` | Komprimierter Vollzustand | tick, blob |
| `follows` | Abonnierte Personen und Blutlinien | target_type, target_id |

Ereignisse niedriger Wichtigkeit werden nach einigen Generationen zu Zählwerten verdichtet.

## 13. API

Basis `/api/v1`, OpenAPI unter `/api/docs`.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/health` | Überwachung |
| GET | `/worlds`, `/worlds/{id}` | Welten, Stand, Seed, Tempo |
| GET | `/worlds/{id}/stats` | Flache Kennzahlen (für REST-Sensoren direkt lesbar) |
| GET | `/worlds/{id}/metrics?keys=&from=&to=&step=` | Zeitreihen, Schnitte nach Kultur, Siedlung, Person |
| GET | `/worlds/{id}/map` | Kacheln und Sichtbereich, optional `?tick=` |
| GET | `/worlds/{id}/events` | Chronik, filterbar |
| GET | `/worlds/{id}/events/{eid}/why` | Regel, Faktoren, Chance, Wurf |
| GET | `/worlds/{id}/away?since=` | „Während du weg warst“ |
| GET | `/persons/{id}`, `/groups/{id}`, `/cultures/{id}` | Detail samt Stammbaum |
| GET | `/worlds/{id}/stories` | Sagen, Nachrufe, Zeitung |
| POST | `/worlds`, `/worlds/{id}/fork` | Neue Welt, Fork ab Snapshot |
| POST | `/worlds/{id}/interventions` | Eingriff (nur wenn aktiviert) |
| GET, PATCH | `/settings` | Laufzeit-Einstellungen |
| PUT, DELETE | `/follows/{type}/{id}` | Abonnieren |
| GET, POST, DELETE | `/webhooks` | Ausgehende Benachrichtigungen |
| GET | `/system/logs` | Programm-Log |
| WS | `/ws` | Live-Ereignisse und Kartendeltas |
| GET | `/events/stream` | Dasselbe als SSE |

Auth: Lesen im LAN standardmäßig offen (abschaltbar). Alles Schreibende und `/system/*` verlangt `Authorization: Bearer <HIAB_API_TOKEN>`. Webhooks: POST mit JSON, gefiltert nach Ereignistyp, Mindestwichtigkeit, abonnierten Personen.

## 14. Statistik

Seite `/stats`, modernes Kachel-Layout, dunkles Design, jede Kachel klickbar bis zur Detailansicht.

- **Kacheln** (Wert, Veränderung seit letztem Besuch, Mini-Verlauf): Weltjahr, Laufzeit, Ticks pro Minute; Lebende, Geborene, Gestorbene, Generationen; Kulturen, Sprachen, Siedlungen, größte Siedlung; Entdeckungen gesamt, zuletzt entdeckt, verlorenes Wissen; Lebenserwartung, Kinder pro Familie, ältester Mensch.
- **Verläufe:** Bevölkerung gestapelt nach Kultur; Stammbaum der Kulturen und Sprachen; Entdeckungen als Zeitstrahl je Kultur; Geburten und Tode pro Jahrzehnt, Todesursachen; Karten-Heatmaps (Dichte, Übernutzung, Wanderwege); Bestände gegen Bevölkerung.
- **Rekorde und Kurioses:** längstes Leben, kinderreichste Person, älteste Blutlinie, am weitesten gewanderter Clan, häufigste Namen, seltenste Merkmale, „Heute vor 100 Jahren“, Vorfahren-Quote, Vergleich mit Forks und archivierten Welten.
- **Technik-Kacheln:** Tick-Dauer, Datenbankgröße, Ereignisse pro Tag, Token-Verbrauch, Seed, Version.

**Detailtiefe (Kernanforderung).** Die Simulation zählt selbst:

- Jeder Ereignistyp, jede Regel und jeder Rohstoff aus einem Datenpaket bekommt automatisch Zähler, ohne Zusatzcode.
- Jede Zahl in vier Schnitten: Welt, Kultur, Siedlung, Person, jeweils Summe und Verlauf.
- Pro Person: Strecke, Jagden und Erfolgsquote, Kinder, Enkel, Wohnorte, Fähigkeiten, miterlebte Ereignisse, lebende Nachfahren.
- Pro Kachel: wie oft betreten, bejagt, bebaut, umkämpft, Geburten und Tode dort.
- Pro Regel: wie oft geprüft, wie oft eingetreten, durchschnittliche Chance.
- Kleinkram: häufigster Geburtsmonat, längste Fehde, kältester Winter, meistbegangener Pfad, beliebtester Name je Jahrhundert.

**Statistik-Explorer:** Kennzahl frei wählen, nach Kultur, Ort, Zeitraum schneiden, als Linie, Balken, Tabelle oder Heatmap, Export CSV und JSON. Dieselbe Abfrage über die API.

## 15. Grafik

Alle Sprites einschließlich Gelände werden per Bildgenerator entworfen (so macht es Letopis mit 44 Bögen aus ChatGPT, siehe https://github.com/leppermesiah/letopis/blob/main/CREDITS.md) und per Skript in ein Atlas überführt. Übergänge, Schnee, Nebel, Nacht, Feuerschein zeichnet der Renderer, Wasser als Shader. UI und Icons als SVG. Für das MVP farbige Platzhalter-Sprites aus Code.

**Stil.** Isometrisch 2:1. Kachel 64 × 32 Pixel, Figuren etwa 24 Pixel hoch, Gebäude ein bis zwei Kacheln breit. Feste Palette mit 32 Farben, weiche Erdtöne, kein Schwarz als Kontur. Gebäude hängen an Technologien, nicht an Epochen.

**Pipeline (Python, Pillow), umgesetzt in `tools/build_atlas.py`:**

1. Bogen mit Stil-Prompt erzeugen, immer zusammen mit einem schon freigegebenen Bogen als Referenzbild. Rohbögen nach `art/sheets/`, Namen der Bilder je Bogen in `art/manifest.yaml`.
2. Das Skript findet die Bilder selbst (transparenter Hintergrund), misst bei jedem die Bodenraute aus und skaliert mit Flächenmittel auf die Zielgröße.
3. Geländekacheln: nur das Innere der Oberseite wird auf eine exakte Raute von 64 × 32 gezogen, Kontur und Erdrand fallen weg. So schließen Kacheln nahtlos an.
4. Objekte: Kontur und Erdrand des Bodenstücks fallen weg, der blanke Boden blendet zum Rand hin aus, was darauf steht, bleibt. Figuren (`kind: figure`) verlieren ihren Boden ganz, damit sie auf jeder Kachel stehen können.
5. Atlas-PNG plus JSON nach `frontend/public/sprites/`, beides committen (der Build braucht dann kein Python-Bildwerkzeug).

`uv run python tools/build_atlas.py`, danach das Frontend neu bauen.

**Erprobt (sieben Bögen, November 2026):** Acht Bilder je Bogen in zwei Reihen zu vier funktionieren zuverlässig, sechzehn nicht. Transparenter Hintergrund funktioniert und ist besser als Magenta. Der Generator hält kein exaktes Pixelraster ein, deshalb misst das Skript und verlässt sich auf keine festen Zellgrößen. Objekte kommen immer auf einem Bodenstück, das ist in Ordnung, das Skript entfernt es.

**Stil-Prompt (immer voranstellen, einen freigegebenen Bogen als Referenzbild anhängen):**

```text
Pixel art sprite sheet for an isometric colony simulation game, in exactly the style of the attached reference sheet.
Style: clean 16-bit era pixel art, isometric 2:1 dimetric view, flat even lighting from the top left,
no gradients, no anti-aliasing, crisp hard pixel edges, large readable pixels.
Palette: warm earthy tones (moss green, clay, ochre, slate, off-white), dark brown outlines instead of black.
Layout: exactly 8 pictures in 2 rows of 4, evenly spaced, generous empty space between them,
one subject per cell, centred, nothing touching or overlapping a neighbour.
Every subject stands on a small isometric diamond of ground (2:1 ratio) with a thin earth edge below,
the same size as in the reference sheet.
Background: fully transparent, nothing else in the background, no shadows outside the ground diamond.
No text, no labels, no numbers, no frame, no watermark, no UI.
Keep scale, proportions and line weight identical across all cells and identical to the reference.
```

**Bogen-Prompts (jeweils anhängen):**

```text
BUILDINGS 1, stone age, each on a bare trodden-earth ground diamond, each at most as wide as its diamond:
1 campfire ringed with stones, burning. 2 hide tent. 3 round hut with thatched roof and a dark doorway.
4 wooden drying rack with strips of meat and fish. 5 storage pit covered with branches and hides.
6 small clay kiln with a little smoke. 7 construction site: wooden posts, a pile of logs, no roof yet.
8 ruin: collapsed hut, a few rotten posts, overgrown.

PEOPLE 1, stone age, tiny figures about a quarter as tall as an oak tree in the reference, simple readable silhouettes,
each standing on a grass ground diamond: 1 woman in hides. 2 man in hides. 3 child. 4 elder with staff.
5 hunter with spear. 6 gatherer with basket. 7 fisher with a fish on a line. 8 group of three people walking with bundles.

PEOPLE 2, late stone age to bronze age, tiny figures exactly as tall as the figures in the reference,
simple readable silhouettes, each standing on a grass ground diamond, all facing right:
1 warrior in hides with a long spear held ready. 2 warrior with a round wooden shield and a club.
3 archer drawing a bow. 4 bronze age warrior with a bronze helmet, a short sword and a shield.
5 chieftain with a feather headdress, a fur cloak and a decorated staff.
6 fallen warrior lying on his back on the ground, spear beside him, no blood.
7 farmer with a hoe over the shoulder. 8 trader carrying a large bundle on his back and a walking stick.

BUILDINGS 2, late stone age to bronze age, each on a bare trodden-earth ground diamond,
each at most as wide as its diamond, same scale as the huts in the reference:
1 granary: small round clay storehouse raised on wooden stilts, thatched cone roof.
2 well: round stone well with a wooden frame, rope and bucket.
3 chieftain's longhouse: long timber hall with a high thatched roof and carved gable posts, one and a half times as wide as a hut.
4 palisade section: a short straight row of sharpened upright logs.
5 burial mound: low grassy mound with a single standing stone on top.
6 war banner: tall wooden pole with a plain cloth banner and a bundle of feathers, planted in the ground.
7 bronze smithy: small open workshop with a clay furnace glowing orange, an anvil stone and a bellows.
8 crop field: small fenced patch of ripe golden grain in rows.

ANIMALS 1, wild animals of the stone age, each on a grass ground diamond, each in side view facing right,
sized relative to the people in the reference (a deer about as tall as a person, a mammoth twice as tall),
simple readable silhouettes, each at most as wide as its diamond:
1 red deer stag with antlers. 2 wild boar. 3 grey wolf. 4 brown bear on all fours.
5 woolly mammoth. 6 aurochs, dark wild bull with long curved horns. 7 wild horse, stocky and dun-coloured.
8 a small flock of three wild geese on the ground.
(names: deer, boar, wolf, bear, mammoth, aurochs, wild_horse, geese)

ANIMALS 2, tame animals and herding of the late stone age to bronze age, each on a grass ground diamond,
each in side view facing right, sized relative to the people in the reference, simple readable silhouettes,
each at most as wide as its diamond:
1 three sheep standing together, woolly and off-white. 2 two goats, brown and white.
3 a cow, brown with short horns. 4 a dog, lean, sandy coloured, standing alert.
5 a tame horse with a simple rope halter. 6 a herder with a long crook stick and a cloak, walking.
7 a raider on horseback with a spear. 8 a small round pen of woven wattle fence, empty inside.
(names: sheep, goats, cow, dog, tame_horse, herder, raider, pen)
```

## 16. Bauplan

| Stufe | Inhalt | Fertig, wenn |
| --- | --- | --- |
| 0 Fundament | Repo-Gerüst, Paketierung mit `hiab`-Befehl, Konfigurations-Ebenen, Programm-Log, Tick-Schleife, Seed und Zufallsstrom, Weltgenerator, Paket-Schema mit Prüfung, SQLite, Speichern und Laden, Zähler-Grundgerüst (`metrics`), Entscheidungs-Log (`world_log`), Determinismus-Test, CI auf drei Betriebssystemen | Zwei Läufe über 500 Weltjahre mit gleichem Seed liefern identische Datenbanken, auf allen drei Betriebssystemen |
| 1 MVP | Personen, Familien, Clans, Ökologie, erste zehn Entdeckungen, Siedlungen (Gesellschaftsstufen 1 bis 3), Ereignis-Chronik mit Vorlagen DE/EN, Karte mit Platzhalter-Grafik, API lesend, WebSocket, Grundkacheln der Statistik, Docker-Image | Welt läuft eine Woche ohne Eingriff und ohne Aussterben in neun von zehn Seeds |
| 2 Tiefe | Völker, voller Entdeckungsgraph, Wissensverlust, Handel, Kulturen mit Sprache und Ortsnamen, „Während du weg warst“, Statistik-Verläufe | Zwei Seeds führen sichtbar zu unterschiedlichen Kulturen |
| 2b Macht | Herrschaft, Staat, Reich, Weltordnung, Konflikte und Kriege, Krankheiten, Katastrophen, Kalibrierung über hundert Seeds | Verteilung der erreichten Stufen entspricht dem Kalibrierziel |
| 3 Erzählen | LLM-Chronist mit drei Adaptern, Personen abonnieren, Webhooks, Rekorde, „Warum ist das passiert?“ | Wochenzeitung erscheint automatisch, mit und ohne Key |
| 4 Zeit | Snapshots, Zeitleiste, Forks, mehrere Welten, Welten-Vergleich | Fork ab Jahr X läuft neben dem Original |
| 5 Einfluss | Gunst und Eingriffe, Einstellungen in der Oberfläche | Eingriff erscheint in der Chronik und ist reproduzierbar |
| 6 Grafik und Feinschliff | Sprite-Pipeline und finales Atlas, Jahreszeiten, Statistik-Explorer, Wandtablet-Modus, Unraid-Template | Öffentlicher Release |
| Später | Nahe und erzeugte Zukunft, Raumfahrt und weitere Welten, echtes Wetter als Einfluss, Austausch zwischen Instanzen | Offen |

Die Sprite-Pipeline kann ab Stufe 1 parallel entstehen, blockiert aber nichts.

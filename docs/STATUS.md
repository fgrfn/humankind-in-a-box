# Stand

## 2026-11-11

- Stufe 0 (Fundament) ist gemergt.
- Stufe 1a (Menschen) ist umgesetzt: Personen, Familien, Clans, Nahrungssuche, Hunger, Wanderung, Entdeckungen, Wissensweitergabe, Clan-Spaltung und -Verschmelzung, erste Siedlungen.
- Stufe 1b (API, Kartenansicht, erste Statistik, Docker-Image) ist umgesetzt. Damit ist Stufe 1 bis auf die Feinabstimmung abgeschlossen.
- Stufe 2a (Wege und Gebäude) ist umgesetzt: Trittzähler verblassen, aus viel begangenen Kacheln werden Pfade und Wege. Sesshafte Clans bauen nach und nach (Baustelle, fertiges Gebäude, Ruine), Gebäude wirken auf Sterblichkeit und Vorrat. Alte Alltagsereignisse werden ausgedünnt (`HIAB_EVENT_DETAIL_YEARS`, Vorgabe 100).
- Die Karte zeigt echte Grafik aus fünf erzeugten Bögen, zugeschnitten mit `tools/build_atlas.py`: 16 Geländekacheln, 8 Naturobjekte, 8 Gebäudebilder (Feuer, Zelt, Hütte, Trockengestell, Vorratsgrube, Töpferofen, Baustelle, Ruine) und 8 Figuren. Wandernde Clans erscheinen als Zelt. Jede Figur auf der Karte ist ein lebender Mensch: Sie läuft vom Lager dorthin, wo sie laut Simulation diesen Monat arbeitet, und zurück. Antippen zeigt, wer das ist, was er tut und womit sein Leben verging. Der einzelne Schritt ist Anzeige, Tätigkeit und Ziel kommen aus der Simulation.
- Tätigkeiten pro Person: Jeder Erwachsene hat jeden Monat eine Arbeit (ein Nahrungsmittel beschaffen, bauen, Nahrung suchen) und ein Ziel. Bei offener Baustelle baut etwa ein Viertel der Erwachsenen, die Geschicktesten zuerst; die anderen teilen sich nach Ertrag auf die Nahrungsquellen auf. Kraft bestimmt, wie viel ein Sammler heimbringt, Geschick den Baufortschritt. Jede Gruppe läuft zu ihrem eigenen Ziel, daraus entstehen die Pfade. Gezählt wird je Person (Lebensmonate je Tätigkeit) und je Welt (`work.*`).
- Stufe 2, Teil Wissen: 35 Entdeckungen von der Steinzeit bis zum Eisen (Ackerbau, Viehhaltung, Pflug, Bewässerung, Speicher, Kupfer, Bronze, Eisen, Mauerwerk, Segeln und mehr). Ackerbau macht den Boden zur Nahrungsquelle, der bei Übernutzung nachlässt. Entdeckungen können Gruppen größer zusammenhalten (`group_adults`), so entstehen Dörfer statt immer neuer Kleinclans. Wissen geht verloren, wenn zu wenige Erwachsene übrig sind oder das Nötige (Lehm, Erz, Fisch) nicht mehr in der Nähe ist; verloren geht nur, worauf nichts anderes aufbaut. Verlorenes bleibt in der Datenbank verzeichnet.
- Stufe 2, Teil Völker: Jeder Clan gehört zu einem Volk. Die Sprache eines Clans verschiebt sich bei jeder Spaltung um einen Laut; wer sich weit genug von der Sprache seines Volkes entfernt hat, kann ein eigenes Volk gründen, und Nachbarn, die inzwischen ähnlicher sprechen, gehen mit. Ein Clan allein unter Fremden kann sich deren Volk anschließen. Ein Volk ohne Clans erlischt. Orte heißen nach dem, was dort ist (Fluss, Wald, Feuerstein), im Wort des Volkes plus dessen Endung; die Bedeutung wird mit angezeigt. Bevölkerung wird je Volk gezählt.
- Gebiete: Jedes Jahr wird das Land neu verteilt. Eine Kachel gehört dem Clan, der am stärksten auf sie drückt: Erwachsene, Sesshaftigkeit und Gebäude machen stark, Hunger schwächt, mit der Entfernung nimmt der Druck ab, und wer eine Kachel schon hält, hat einen Vorteil. Ohne Würfel, also folgt jede Grenze aus der Lage. Das Gebiet eines Volkes ist das Land seiner Clans. Fremde ernten auf gehaltenem Land nur die Hälfte. Größere Verschiebungen zwischen Völkern stehen in der Chronik. Die Karte zeigt Gebiete in der Farbe des Volkes mit Grenzlinien, abschaltbar.
- Handel: Nachbarn, die einander etwas zu bieten haben, können Tauschpartner werden (gewürfelt, häufiger im selben Volk, zwischen Sesshaften und wenn einer ein Vorkommen hat, das dem anderen fehlt). Partner gelten füreinander als Zugang zu Vorkommen, helfen einander im Hungermonat mit Überschuss, lernen leichter voneinander und treten Pfade zwischeneinander aus. Partnerschaften enden, wenn die beiden zu weit auseinanderziehen. Die Karte zeigt sie als gestrichelte Linie.
- „Während du weg warst“: Der Browser merkt sich je Welt das zuletzt gesehene Jahr und zeigt beim Wiederkommen nach mindestens fünf Weltjahren eine Zusammenfassung (`/since`).
- Damit ist Stufe 2 inhaltlich fertig.
- Lager: Jeder Clan hält neben Nahrung auch Güter (Holz, Feuerstein, Lehm, Salz, Erze; was lagerbar ist, steht im Datenpaket). Ist niemand hungrig, holt ein Teil der Erwachsenen, was am meisten fehlt, solange Platz ist. Platz richtet sich nach der Zahl der Erwachsenen und nach Lagergebäuden. Gebaut wird aus dem Lager, nicht mehr direkt aus dem Land. Handwerk verbraucht jährlich etwas, und Tauschpartner geben ab, wovon sie reichlich haben. Je Clan wird gebucht, was im Jahr dazukam, verbraucht, erhalten und abgegeben wurde; je Volk und Welt gibt es Summen und Verläufe (`stores.*`).
- Zeitregler: Anhalten, 1×, 5×, 25×, so schnell wie möglich und „10 Jahre vor“ (danach zurück auf normal). Die API schreibt den Wunsch in `control.json` im Datenordner, der Worker liest ihn zweimal pro Sekunde und meldet in `pace.json`, wie schnell er wirklich ist. Die Datenbank bleibt dabei unberührt. Mit gesetztem API-Token wird er dafür verlangt.
- Karte: Ein Tipp auf ein Lager oder einen Menschen öffnet ein Feld neben der Karte (Handy: unten), die Karte bleibt sichtbar. Während eine andere Ansicht offen ist, hält die Karte an und behält ihre Größe; vorher konnte der Wechsel zurück zur Karte die Seite einfrieren lassen.
- Startvölker: Eine Welt beginnt mit mehreren Völkern (`start_peoples`, Vorgabe 4) an weit auseinanderliegenden guten Orten, jedes mit eigener Sprache und `start_families` Familien.
- Stammbaum: Vorfahren bis drei Generationen hinauf, Nachkommen bis drei hinunter (`/persons/{id}/tree`), aus der Personenkarte erreichbar; jede Person darin ist antippbar.
- Volksgröße: Hat ein Volk mehr als `people_max_clans` (Vorgabe 10) Clans, lösen sich die Clans am Rand leichter und gründen eigene Völker; Nachbarn auf derselben Seite gehen mit. Ein Volk aus nur einem Clan schließt sich leichter Nachbarn an. Große Völker sollen später nur durch Bindendes (Herrschaft, Glaube) entstehen, das kommt mit Stufe 2b. Seed 7 nach 400 Jahren: 92 Völker, die meisten mit ein bis drei Clans, das größte mit 30.
- Zeitregler: Beim Ändern der Geschwindigkeit speichert der Worker sofort, und die Seite fragt beim Vorspulen jede Sekunde nach, damit Jahr und Karte gleich nachziehen.
- Volksfarben: Die ersten zwölf Völker haben feste, gut unterscheidbare Farben, weitere werden über den goldenen Schnitt verteilt.
- Offen aus den Wünschen des Besitzers: später eine größere Karte.
- Früher geplant: Handel und „Während du weg warst“. Bräuche und Glaube eines Volkes folgen mit Stufe 2b. Der Entdeckungsgraph endet vorerst beim Eisen; spätere Zeitalter kommen mit Stufe 2b, weil sie Staaten und Handel brauchen.
- Noch offen: Lizenz-Entscheidung, Prüfung von PyPI-Name und Domain, Bogen für Tiere.

## Was es gibt

- CLI `hiab`: `run`, `serve`, `new-world`, `simulate`, `verify`, `events`, `status`, `check-packs`.
- HTTP-API unter `/api/v1` (nur lesend): Welt, flache Kennzahlen, Karte, Ebenen, Clans, Personen, Chronik in Deutsch und Englisch, „Warum ist das passiert?“, Zeitreihen, Live-Ereignisse als Server-Sent Events. Doku unter `/api/docs`.
- Weboberfläche: isometrische Karte mit Gelände- und Natur-Sprites, Lager, Siedlungen, Gebäude, Baustellen und Ruinen, Pfade und Wege aus den Trittzählern, Chronik mit Live-Nachlauf, Statistik-Kacheln mit Verlauf, Clan-Ansicht, Sprachumschaltung.
- `hiab run` startet Simulation und Webserver als zwei Prozesse. Dockerfile vorhanden.
- Konfiguration in vier Ebenen, Programm-Log als JSON-Zeilen.
- Zufallsströme je Teilsystem, Weltgenerator rein mit Ganzzahlen.
- Datenpakete mit Schema-Prüfung und `packs/local/overrides.yaml`. Das Basispaket enthält fünf Bestände (Wildpflanzen, Wild, Fisch, Holz, Boden), sechs Vorkommen, sechs Naturereignis-Regeln, 35 Entdeckungen, sieben Gebäude und die Lebensparameter in `life.yaml`.
- Tick-Schleife: Klimadrift, saisonale Regeln je Region, Nachwachsen der Bestände, monatlicher Schritt der Gesellschaft.
- Jeder Wurf läuft über `World.roll` oder `World.draw_int`, wird in `world_log` protokolliert und in `metrics` gezählt.
- SQLite mit Migrationen, Speichern und Laden, inklusive Personen, Gruppen, Entdeckungen, Orten, Gebäuden und Trittzählern je Kachel.

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

- Die Vorgabe für die Karte ist jetzt 128 x 128 Kacheln (vorher 64 x 64). Seed 5 über 400 Jahre: rund 3.300 Menschen in 220 Clans, 29 Sekunden Rechenzeit. Die Kalibrierung unten stammt noch von der kleinen Karte. Bestehende Welten behalten ihre Größe.

- Siedlungen halten ohne Ackerbau im Schnitt nur etwa eine Generation, dann treibt der Hunger die Leute weiter. Das ist für Jäger und Sammler plausibel, sorgt aber für viele Ruinen. Dauerhafte Orte kommen mit dem Ackerbau.
- Objekte auf der Karte (Bäume, Felsen) sind reine Anzeige aus Biom und Koordinate, sie hängen noch nicht am Holzbestand der Kachel.
- Wissensverlust gibt es noch nicht (Stufe 2).
- Familien sind bisher nur eine Haushaltsnummer an der Person, keine eigene Gruppe in der Datenbank.
- Ab einigen tausend Personen wird die Simulation langsam, das Zusammenfassen entfernter Gruppen fehlt noch.

## Abweichungen von der Spezifikation

- Es gibt noch keinen Event-Kanal zwischen Worker und API. Der Worker speichert alle 15 Sekunden, die API liest die Datenbank. Die Anzeige hängt der Simulation also bis zu 15 Sekunden nach.
- Live-Ereignisse gibt es als Server-Sent Events, WebSocket fehlt noch.
- Die API hat noch keine schreibenden Endpunkte und keine Token-Prüfung.
- Der gebaute Frontend-Stand liegt im Repo unter `src/hiab/web/`.

- Eingebaute Datenpakete liegen in `src/hiab/data/packs/` statt in `packs/` im Wurzelverzeichnis, damit eine pipx-Installation sie enthält.
- Biome sind vorerst Teil des Kerns, weil der Weltgenerator sie braucht.
- Regionen sind vorerst feste Blöcke von 16 x 16 Kacheln und dienen als Geltungsbereich der Naturereignisse.
- Ein Jahr hat 360 Tage, zwölf Monate zu 30 Tagen.
- Regeln haben zusätzlich ein Feld `month` (Monat der Prüfung).
- Bestände wachsen logistisch nach: Ein gesunder Bestand erholt sich am schnellsten, ein erschöpfter nur langsam. Dadurch hat Übernutzung Folgen.
- Die Würfe pro Person und Jahr (Tod, Paarbildung, Geburt) werden immer gezählt, aber nur bei `HIAB_WORLD_LOG=full` einzeln protokolliert.

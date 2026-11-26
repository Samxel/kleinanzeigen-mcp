<h1 align="center">kleinanzeigen-mcp</h1>

<p align="center"><sub>Aus derselben Reihe: <a href="https://github.com/Samxel/geizhals-mcp">geizhals-mcp</a> · <a href="https://github.com/Samxel/willhaben-mcp">willhaben-mcp</a> · <a href="https://github.com/Samxel/rabatt-mcp">rabatt-mcp</a></sub></p>

Ein MCP-Server, mit dem eine KI Anzeigen auf
[Kleinanzeigen](https://www.kleinanzeigen.de) durchsuchen und Details zu
Anzeigen und Verkäufern abrufen kann. Er nutzt die API der
Kleinanzeigen-Android-App (`api.kleinanzeigen.de` / `gateway.kleinanzeigen.de`)
und gibt der KI die wichtigen Felder zurück.

<p align="center">
  <a href="https://www.kleinanzeigen.de/"><img alt="Listings" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.listings&label=Listings&color=green&suffix=%20live&cacheSeconds=3600"></a>
  <a href="https://themen.kleinanzeigen.de/ueber-uns/"><img alt="Monthly visitors" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.visitors&label=Visitors&color=ff7300&suffix=%20%2Fmonth&cacheSeconds=3600"></a>
  <a href="https://themen.kleinanzeigen.de/ueber-uns/"><img alt="Commercial users" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.commercial_users&label=Commercial%20users&color=1e6fff&cacheSeconds=3600"></a>
</p>

<p align="center">
  <a href="#highlights">Highlights</a> ·
  <a href="#einrichtung">Einrichtung</a> ·
  <a href="#in-claude-einbinden-und-andere-mcp-clients">In Claude einbinden</a> ·
  <a href="#selbst-starten">Starten</a> ·
  <a href="#tools">Tools</a> ·
  <a href="#haftungsausschluss">Haftungsausschluss</a> ·
  <a href="#lizenz">Lizenz</a>
</p>

<p align="center"><sub><a href="README.md">Read this in English</a></sub></p>

## Highlights

- **Anzeigen auch optisch prüfen**  
  Lädt die echten Fotos einer Anzeige herunter, damit eine KI mit Bildverständnis **Zustand, Gebrauchsspuren, Schäden, Vollständigkeit und andere Details** selbst sieht, statt sich nur auf die Beschreibung des Verkäufers zu verlassen. Standardmäßig klein, auf Wunsch scharf genug, um ein Etikett zu lesen.

- **Filter, die die API nicht hat**  
  `title_only`, `require` und `exclude` werden hier auf dem Server angewendet und blättern automatisch weiter. So bekommt eine KI **so viele echte Treffer, wie sie angefragt hat**, statt immer wieder neu zu suchen, um Zubehör und falsche Varianten loszuwerden.

- **Vom Fund bis zur genauen Prüfung**  
  Passende Anzeigen finden und dann **vollständige Beschreibungen, einzeln aufgeführte Merkmale, Standorte, die Bewertung des Verkäufers und alle Fotos** für eine genauere Analyse abrufen, für eine Anzeige oder bis zu zehn auf einmal.

## Einrichtung

Drei Wege, einer reicht. Bei keinem muss etwas im Hintergrund laufen: Der
Client startet den Server, wenn er ihn braucht.

**Claude Desktop, ohne Terminal.** `kleinanzeigen-mcp.mcpb` aus dem
[neuesten Release](https://github.com/Samxel/kleinanzeigen-mcp/releases/latest)
herunterladen und doppelklicken. Claude Desktop zeigt einen
Installationsdialog und richtet die Abhängigkeiten selbst ein. Fertig, den Rest
dieses Abschnitts kannst du überspringen.

**Mit [uv](https://docs.astral.sh/uv/), ohne Klonen.** Ein Befehl startet die
aktuelle Version direkt von GitHub:

```bash
uvx --from git+https://github.com/Samxel/kleinanzeigen-mcp kleinanzeigen-mcp --stdio
```

**Aus einem Klon.** Braucht Python 3.10+.

```bash
git clone https://github.com/Samxel/kleinanzeigen-mcp
cd kleinanzeigen-mcp
pip install -r requirements.txt
python main.py --stdio
```

`uv run main.py --stdio` geht auch ohne `pip install`: `main.py` bringt die
Liste seiner Abhängigkeiten selbst mit.

## In Claude einbinden (und andere MCP-Clients)

### Claude Code

Ein Befehl, keine Konfigurationsdatei:

```bash
claude mcp add kleinanzeigen -- uvx --from git+https://github.com/Samxel/kleinanzeigen-mcp kleinanzeigen-mcp --stdio
```

Aus einem Klon zeigst du stattdessen auf `main.py`:

```bash
claude mcp add kleinanzeigen -- python /pfad/zu/kleinanzeigen-mcp/main.py --stdio
```

Mit `--scope user` steht der Server in jedem Projekt zur Verfügung, nicht nur
im aktuellen. `claude mcp list` zeigt, ob die Verbindung steht, `claude mcp
remove kleinanzeigen` entfernt ihn wieder.

### Claude Desktop

Am einfachsten ist die `.mcpb` aus der [Einrichtung](#einrichtung). Ohne sie
öffnest du **Settings > Developer > Edit Config**, trägst `kleinanzeigen` in
`claude_desktop_config.json` ein und startest Claude Desktop neu:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Samxel/kleinanzeigen-mcp", "kleinanzeigen-mcp", "--stdio"]
    }
  }
}
```

Aus einem Klon nimmst du `"command": "python"` und `"args":
["C:\\pfad\\zu\\kleinanzeigen-mcp\\main.py", "--stdio"]` (der volle Pfad zu
`main.py`, unter macOS/Linux mit normalen Schrägstrichen).

Eigene Connectors (**Settings > Connectors**) verbinden sich aus der Cloud von
Anthropic und erreichen deshalb keinen Server, der nur auf deinem Rechner
läuft. Willst du die Tools auch in claude.ai und den Mobil-Apps nutzen, machst
du den HTTP-Server (siehe [Selbst starten](#selbst-starten)) über cloudflared,
ngrok oder einen Rechner mit öffentlichem Hostnamen erreichbar und trägst die
HTTPS-URL unter **Settings > Connectors > Add custom connector** ein. Dann kann
aber jeder, der die URL kennt, den Server nutzen, also stell eine
Authentifizierung davor.

Alle Tools sind als rein lesend markiert. Clients, die das beachten, fragen
deshalb nicht vor jedem Aufruf nach. In Claude Desktop kannst du außerdem unter
**Settings > Connectors > kleinanzeigen** das Dropdown rechts bei den Tools auf
**Always allow** stellen.

### Cursor, Codex, VS Code und andere Clients mit JSON-Konfiguration

Derselbe Eintrag wie bei Claude Desktop, in der MCP-Konfiguration des Clients:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Samxel/kleinanzeigen-mcp", "kleinanzeigen-mcp", "--stdio"]
    }
  }
}
```

Clients, die sich stattdessen mit einer URL verbinden, bekommen `"type":
"http"` und `"url": "http://127.0.0.1:8020/mcp"`, mit dem Server wie unten
gestartet.

## Selbst starten

Ohne `--stdio` startet der Server über Streamable HTTP und zeigt an, wo er
lauscht:

```bash
python main.py
```

```
Starting kleinanzeigen-mcp server on http://127.0.0.1:8020/mcp
```

Diese URL trägst du im Client ein, zum Beispiel mit `claude mcp add
--transport http kleinanzeigen http://127.0.0.1:8020/mcp`. Host, Port und Pfad
stehen oben in `kleinanzeigen/server.py`; der Port unterscheidet sich von
geizhals-mcp (8000) und willhaben-mcp (8010), damit alle drei nebeneinander
laufen können. Mit pip oder uv installiert, machen der Befehl
`kleinanzeigen-mcp` und `python -m kleinanzeigen` dasselbe wie
`python main.py`.

## Tools

Ergebnisse kommen als kompaktes JSON, Felder ohne Wert fallen weg.
Suchtreffer haben keinen eigenen Link: Die Anzeigenseite ist
`https://www.kleinanzeigen.de/s-anzeige/{id}`. Das steht einmal in den
Server-Anweisungen, statt in jedem Treffer wiederholt zu werden.

<details>
<summary><code>search_kleinanzeigen(query, ...)</code>: Anzeigen nach Suchbegriff und/oder Kategorie durchsuchen</summary>

Suche per Freitext und/oder Kategorie (ID oder Name; ein Name wird so
erkannt, wie ein Modell ihn schreibt: „Handys“ findet „Handy & Telefon“,
„Laptop“ findet „Laptops & Notebooks“, und gibt es den Namen nicht, kommen die
ähnlichsten Kategorien als Vorschlag). Filter für kategoriespezifische
Merkmale, Ort mit Umkreis oder Postleitzahl, Preisspanne, Angebot/Gesuch,
privat/gewerblich, Versand und „Direkt kaufen“, dazu Sortierung und Blättern
(`rows` höchstens 30).

Filter, die hier über die Antwort von Kleinanzeigen laufen und weiterblättern,
bis `rows` Treffer gefunden oder 250 Anzeigen durchgesehen sind:
- `title_only`: Jedes Wort aus `query` muss im Titel stehen
- `require`: Begriffe, die in Titel oder Beschreibung vorkommen müssen
  („128gb“ findet auch „128 GB“). Hierher gehören Spezifikationen: Verkäufer
  schreiben dieselbe Speichergröße auf verschiedene Arten und lassen sie oft
  ganz aus dem Titel weg.
- `exclude`: Anzeigen verwerfen, deren Titel diese Wörter enthält („kabel“
  erwischt „Ladekabel“, „pro“ verschont „Prozessor“)

Bezahlte „TOP“-Platzierungen bleiben draußen, außer mit
`include_top_ads=True`. Sie stehen über jeder Sortierung und sind meist
Reparaturdienste und Aufkäufer („Ankauf“), nicht der gesuchte Artikel. Jeder
Treffer sagt, ob er versendet wird (`ships`) und wie viele Fotos er hat
(`image_count`). `total`, `next_offset` und `has_more` sagen, wo es
weitergeht; `next_offset` zeigt genau auf die Anzeige, bei der eine gefilterte
Suche aufgehört hat, zwischen zwei Seiten geht also kein Treffer verloren.

</details>

<details>
<summary><code>get_ad_detail(ad_id | ids)</code>: eine Anzeige, oder bis zu zehn, vollständig abrufen</summary>

Alles zu einer Anzeige: die volle Beschreibung, Merkmale unter der
Bezeichnung, die auch die Anzeigenseite zeigt („Zustand“, „Speicher“, …),
Kategorie, Ort, Versandoptionen, die Bewertung des Verkäufers und wie viele
Fotos sie hat. Statt `ad_id` gehen auch bis zu 10 `ids`, um mehrere in einem
Aufruf zu vergleichen; sie kommen als `{count, ads, failed}` zurück, und eine
Anzeige, die nicht mehr existiert, landet in `failed`, statt den Rest scheitern
zu lassen.

</details>

<details>
<summary><code>get_ad_images(ad_id, max_images=4, detail="low")</code>: die Fotos einer Anzeige ansehen</summary>

Lädt die Fotos einer Anzeige auf dem Server herunter (höchstens 10) und gibt
sie als echte Bilder zurück, damit ein Client mit Bildverständnis die Fotos
sieht statt nur URLs. `detail="low"` (300×400, rund 160 Tokens pro Foto)
reicht für Zustand und Vollständigkeit; `detail="high"` (720×960, rund 900
Tokens) liest Kleingedrucktes wie ein Etikett, eine Seriennummer oder einen
Bildschirm.

</details>

<details>
<summary><code>get_seller_info(seller_id)</code>: sehen, wer verkauft</summary>

Name, privat oder gewerblich, Mitglied seit, Zahl der Anzeigen, Follower,
Antwortzeit und der Bewertungswert von Kleinanzeigen. Der Profilteil steckt
hinter einem Betrugsschutz, der nach IP-Bereichen filtert, und kann von VPN-
oder Rechenzentrumsadressen aus scheitern; `partial` sagt das dann, und die Bewertung
kommt trotzdem zurück.

</details>

<details>
<summary><code>search_locations(query, limit=10)</code>: eine Orts-ID finden</summary>

Sucht Orts-IDs für den Filter `location_id` nach dem Namensanfang: Bundesländer,
Städte und Stadtteile (höchstens 50 pro Aufruf; `count` sagt, wie viele
passten). Für eine Postleitzahl gibst du der Suche stattdessen `zip_code` mit.

</details>

<details>
<summary><code>get_category_filters(category, key)</code>: die Merkmalfilter einer Kategorie auflisten</summary>

Die Merkmalfilter, die das Argument `attributes` der Suche für eine Kategorie
annimmt, direkt aus dem Suchschema von Kleinanzeigen, mit den `values` jedes
Filters als Zuordnung von Wert zu Bezeichnung (`{"bmw": "BMW"}`). Sie grenzen
viel besser ein als zusätzliche Wörter in `query`: In „PC-Zubehör & Software“
schneiden sie eine Suche direkt auf `grafikkarten` oder `mainboards` zu. Eine
Kategorie mit langen Wertelisten (Autos listen jede Marke) lässt sich mit
`key` auf einen Filter beschränken, per Schlüssel oder Bezeichnung
(`"autos.marke"` oder `"Marke"`).

</details>

<details>
<summary><code>list_categories(query, limit=40)</code>: Kategorie-IDs nachschlagen</summary>

Durchsucht den Kategoriebaum nach den IDs, die die Suche braucht, jeweils mit
Pfad (höchstens 100 pro Aufruf). Der Baum (159 Kategorien) liegt dem Server in
`kleinanzeigen/data/categories.json` bei, das kostet also keine Anfrage. Er
endet recht weit oben: Feinere Einteilungen wie „Grafikkarten“ sind
Merkmalfilter.

</details>

## Haftungsausschluss

Das ist ein unabhängiges, inoffizielles Projekt ohne Verbindung zu
Kleinanzeigen oder Adevinta; beide unterstützen oder empfehlen es nicht.
„Kleinanzeigen“ und alle zugehörigen Marken gehören ihren jeweiligen Inhabern.

Es nutzt eine inoffizielle Schnittstelle der Kleinanzeigen-App, die sich
jederzeit ändern oder wegfallen kann. Du bist dafür verantwortlich, wie du es
nutzt: Halte dich an die Nutzungsbedingungen von Kleinanzeigen und an geltendes
Recht, überlaste die Server nicht und sammle keine personenbezogenen Daten aus
Anzeigen.

Falls du Rechteinhaber bist und Bedenken zu diesem Repository hast, eröffne
bitte ein Issue, ich melde mich umgehend.

## Lizenz

[`MIT LICENSE`](LICENSE). Ohne Gewähr.

<p align="center"><sub><a href="README.md">Read this in English</a></sub></p>

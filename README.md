<h1 align="center">kleinanzeigen-mcp</h1>

An MCP server that lets an AI search [Kleinanzeigen](https://www.kleinanzeigen.de)
listings and pull ad and seller details. It wraps the Kleinanzeigen Android
app's API (`api.kleinanzeigen.de` / `gateway.kleinanzeigen.de`) and returns the
important fields to the AI.

<p align="center">
  <a href="https://www.kleinanzeigen.de/"><img alt="Listings" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.listings&label=Listings&color=green&suffix=%20live&cacheSeconds=3600"></a>
  <a href="https://themen.kleinanzeigen.de/ueber-uns/"><img alt="Monthly visitors" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.visitors&label=Visitors&color=ff7300&suffix=%20%2Fmonth&cacheSeconds=3600"></a>
  <a href="https://themen.kleinanzeigen.de/ueber-uns/"><img alt="Commercial users" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fkleinanzeigen-mcp%2Fcoverage%2Fcoverage.json&query=%24.commercial_users&label=Commercial%20users&color=1e6fff&cacheSeconds=3600"></a>
</p>

## Highlights

- **Visual Listing Analysis**  
  Downloads and analyzes the actual ad photos, allowing vision-capable AI to inspect an item's **condition, wear, damage, completeness, and other visual details** instead of relying only on the seller's description.

- **Filters the API doesn't have**  
  `title_only`, `require` and `exclude` are applied server-side here and page on automatically, so an AI gets **the number of real matches it asked for** instead of re-searching to work around accessories and wrong variants.

- **From discovery to full inspection**  
  Find relevant ads, then retrieve **complete descriptions, itemised attributes, locations, seller reputation and all photos** for a deeper analysis.

## Tools

Results come as compact JSON, and fields without a value are left out.

<details>
<summary><code>search_kleinanzeigen(query, ...)</code>: search listings by keyword and/or category</summary>

Search by free-text keyword and/or category (id or name; a name matches the
way a model writes it, so "Handys" finds "Handy & Telefon" and "Laptop" finds
"Laptops & Notebooks", and a miss suggests the closest categories). Filters for
category-specific attributes, location/radius or postcode, price range,
offer/wanted, private/commercial, shipping and "Direkt kaufen", plus sorting
and paging (`rows` up to 30).

Client-side filters, applied here over what Kleinanzeigen returns, paging on
until `rows` matches turn up or 250 ads were scanned:
- `title_only`: every word of `query` must be in the title
- `require`: terms that must appear in title or description ("128gb" matches
  "128 GB" too). This is where specs belong: sellers write the same storage
  size several ways and often leave it out of the title.
- `exclude`: drop ads whose title carries these ("kabel" catches "Ladekabel",
  "pro" spares "Prozessor")

Paid "TOP" placements are left out unless `include_top_ads=True`. They sit
above any sort order and are mostly repair shops and buyers ("Ankauf"), not
the item. Each hit has a short `url`, whether it `ships`, and `image_count`.
`total`, `next_page` and `has_more` say where to continue.

</details>

<details>
<summary><code>get_ad_detail(ad_id)</code>: get one ad in full</summary>

Everything about one ad: full description, attributes by the label the ad page
shows ("Zustand", "Speicher", ...), category, location, shipping options, the
seller's rating and how many photos it has.

</details>

<details>
<summary><code>get_ad_images(ad_id, max_images=4)</code>: look at an ad's photos</summary>

Download an ad's photos server-side (at most 10) and return them as real image
content, so a vision-capable client sees the pictures instead of just URLs.

</details>

<details>
<summary><code>get_seller_info(seller_id)</code>: see who is selling</summary>

Name, private vs commercial, member-since date, ad counts, followers, reply
speed and Kleinanzeigen's reputation score. The profile half is guarded by
IP-range anti-fraud and can fail from VPN or datacenter addresses; `partial`
then says so and the reputation still comes back.

</details>

<details>
<summary><code>search_locations(query)</code>: find a location id</summary>

Look up location ids for the `location_id` filter by name prefix: states,
cities and districts. For a postcode, pass `zip_code` to the search instead.

</details>

<details>
<summary><code>get_category_filters(category)</code>: list a category's attribute filters</summary>

The attribute filters the search's `attributes` argument takes for one
category, straight from Kleinanzeigen's own search-options schema. They narrow
far better than extra words in `query`: in "PC-Zubehör & Software" they cut a
search down to `grafikkarten` or `mainboards` outright.

</details>

<details>
<summary><code>list_categories(query)</code>: look up category ids</summary>

Browse the category tree for the ids the search takes. The tree (159
categories) ships with the server in `data/categories.json`, so this costs no
request. It stops fairly high up: finer cuts like "Grafikkarten" are attribute
filters.

</details>

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

With [uv](https://docs.astral.sh/uv/) you can skip this step: `main.py`
declares its own dependencies, so `uv run main.py` installs them on the fly.

## Run

```bash
python main.py
```

The server starts over streamable HTTP and prints where it's listening:

```
Starting kleinanzeigen-mcp server on http://127.0.0.1:8020/mcp
```

Point your MCP client at that URL. Host, port and path live at the top of
`main.py`; the port differs from geizhals-mcp (8000) and willhaben-mcp (8010),
so all three can run side by side.

For clients that start the server themselves, `python main.py --stdio` speaks
MCP over stdin/stdout instead. Nothing has to run in the background then.

## Add it to Claude (and other MCP clients)

Clients that start their own servers use the stdio mode. Clients that connect
to a URL need `python main.py` running and take the URL it printed on startup.

### Claude Code

One command, no config file. Claude Code starts the server itself:

```bash
claude mcp add kleinanzeigen -- python /path/to/kleinanzeigen-mcp/main.py --stdio
```

Or connect to a server you already started with `python main.py`:

```bash
claude mcp add --transport http kleinanzeigen http://127.0.0.1:8020/mcp
```

Add `--scope user` to have it in every project instead of only the current one.
`claude mcp list` shows whether the connection came up, `claude mcp remove
kleinanzeigen` takes it out again.

### Cursor, Codex, VS Code and other JSON-config clients

Same URL, in the client's MCP config:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "type": "http",
      "url": "http://127.0.0.1:8020/mcp"
    }
  }
}
```

### Claude Desktop

Custom connectors (**Settings > Connectors**) connect from Anthropic's cloud,
so they cannot reach a server running only on your own machine. Two ways
around it:

**Let Claude Desktop start it over stdio.** Open **Settings > Developer > Edit
Config**, add the `kleinanzeigen` entry to `claude_desktop_config.json` and
restart Claude Desktop:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "python",
      "args": ["C:\\path\\to\\kleinanzeigen-mcp\\main.py", "--stdio"]
    }
  }
}
```

Use the full path to `main.py` (forward slashes on macOS/Linux). With uv
installed, `"command": "uv"` and `"args": ["run",
"/path/to/kleinanzeigen-mcp/main.py", "--stdio"]` also takes care of the
dependencies.

**Or expose the server** (cloudflared, ngrok, or run it on a box with a public
hostname) and add that HTTPS URL under **Settings > Connectors > Add custom
connector**. That way the tools also work in claude.ai and the mobile apps.
Anyone who finds the URL can use the server too, though, so put
authentication in front of it.

Every tool is marked read-only, so clients that honour that hint won't ask
before each call. In Claude Desktop you can also open **Settings > Connectors >
kleinanzeigen** and set the tools' dropdown on the right to **Always allow**.

## Notes

- Search quirks worth knowing: `total` is capped at 10000 by Kleinanzeigen (so
  that value means "at least"), and a missing `price_amount` means "zu
  verschenken" or "VB", see `price_type`.
- `main.py` holds the MCP tools; the `kleinanzeigen/` package holds the API
  access and credential (`api.py`), title matching, the category tree and the
  result summaries.
- Results go out as compact JSON with empty fields left out, and what all tools
  share is said once in the server instructions instead of in every tool
  description. Both keep what the model has to read small.
- `data/categories.json` is a flattened snapshot of Kleinanzeigen's category
  tree (title, id, children), built by `scripts/build_categories.py` from the
  live `api/categories.json` (which ships the tree wrapped in JAXB envelopes
  and a single "Alle Kategorien" pseudo-root). Re-run it if Kleinanzeigen
  changes their categories.
- The badges read `coverage.json` from the `coverage` branch.
  `scripts/update_coverage.py` refreshes it from Kleinanzeigen's public "Über
  uns" page, and a daily GitHub Action commits any change there, so the counts
  don't add a commit to `master` every day.
- API details are documented in [`search_api.md`](search_api.md).
- This uses Kleinanzeigen's internal mobile API, not an official one. Be nice to it.

## Tests

```bash
pip install pytest
pytest
```

The suite runs offline against a fake Kleinanzeigen and goes through a real
MCP client, stdio transport included. `KLEINANZEIGEN_LIVE=1 pytest` adds smoke
tests against the live API. CI runs the offline suite on every push and the
live tests once a day, which is what notices Kleinanzeigen changing its app API
or retiring the client credential.

## Disclaimer

This is an independent, unofficial project and is not affiliated with, endorsed
by, or connected to Kleinanzeigen or Adevinta. "Kleinanzeigen" and all related
trademarks belong to their respective owners.

It's published for educational and research purposes only. It talks to
Kleinanzeigen's internal API, which is not meant for public use and may break
or change at any time. You are responsible for how you use it: respect
Kleinanzeigen's Terms of Service, robots rules and applicable law, and don't
hammer their servers.

## License

[`MIT LICENSE`](LICENSE). Provided "as is", without warranty.

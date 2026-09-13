<h1 align="center">kleinanzeigen-mcp</h1>

An MCP server that lets an AI search [Kleinanzeigen](https://www.kleinanzeigen.de)
listings and pull ad and seller details. It wraps the Kleinanzeigen Android
app's API (`api.kleinanzeigen.de` / `gateway.kleinanzeigen.de`) and returns the
important fields to the AI.

## Highlights

- **Visual Listing Analysis**  
  Downloads and analyzes the actual ad photos, allowing vision-capable AI to inspect an item's **condition, wear, damage, completeness, and other visual details** instead of relying only on the seller's description.

- **Filters the API doesn't have**  
  `title_only`, `require` and `exclude` are applied server-side here and page on automatically, so an AI gets **the number of real matches it asked for** instead of re-searching to work around accessories and wrong variants.

- **From discovery to full inspection**  
  Find relevant ads, then retrieve **complete descriptions, itemised attributes, precise locations, seller reputation and all photos** for a deeper analysis.

## Tools

**`search_kleinanzeigen(query, ...)`**

Search listings by free-text keyword and/or category (id **or** name). Filters
for category-specific attributes, location/radius or postcode, price range,
offer/wanted, private/commercial, shipping and "Direkt kaufen", plus sorting
and paging.

Client-side filters, applied here over what Kleinanzeigen returns:
- `title_only`: every word of `query` must be in the title
- `require`: terms that must appear in title or description ("128gb" matches
  "128 GB" too)
- `exclude`: drop ads whose title carries these ("kabel" catches "Ladekabel",
  "pro" spares "Prozessor")

Returns a trimmed list of hits plus `total` / `next_page` / `has_more`.

**`get_ad_detail(ad_id)`**

Everything about one ad: full description, precise location, category,
attributes, shipping options, all images and the seller's rating.

**`get_ad_images(ad_id, max_images=4)`**

Download an ad's photos server-side and return them as real image content
(base64), so a vision-capable client sees the pictures instead of just URLs.

**`get_seller_info(seller_id)`**

Who is selling: name, private vs commercial, member-since date, ad counts,
followers, badges and Kleinanzeigen's reputation score.

**`search_locations(query)`**

Look up location/region ids for `search_kleinanzeigen`'s `location_id` filter
by name prefix.

**`get_category_filters(category_id)`**

List the category-specific attribute filters `search_kleinanzeigen`'s
`attributes` argument takes for one category, straight from Kleinanzeigen's
own search-options schema.

**`list_categories(query)`**

Browse Kleinanzeigen's category tree to find the category ids
`search_kleinanzeigen` takes. The full tree ships with the server in
`data/categories.json`.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The server starts over streamable HTTP and prints where it's listening:

```
Starting kleinanzeigen-mcp server on http://127.0.0.1:8000/mcp
```

Point your MCP client at that URL. Host, port and path live at the top of
`main.py`.

## Add it to Claude (and other MCP clients)

The server speaks streamable HTTP, so most clients only need the URL it printed
on startup.

### Claude Code

One command, no config file:

```bash
claude mcp add --transport http kleinanzeigen http://127.0.0.1:8000/mcp
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
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### Claude Desktop

Custom connectors (**Settings > Connectors**) are dialled from Anthropic's
cloud, so they cannot reach a server bound to your own machine. Two ways
around it:

**Bridge over stdio** with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
(needs [Node.js](https://nodejs.org)). Open **Settings > Developer > Edit
Config**, add the `kleinanzeigen` entry to `claude_desktop_config.json` and
restart Claude Desktop:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote", "http://127.0.0.1:8000/mcp"]
    }
  }
}
```

On macOS/Linux drop the Windows wrapper: `"command": "npx"` with
`"args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp"]`.

**Or expose the server** (cloudflared, ngrok, or run it on a box with a public
hostname) and add that HTTPS URL under **Settings > Connectors > Add custom
connector**. That route also makes the tools available in claude.ai and the
mobile apps, not just the desktop client but the API it talks to is then
reachable by whoever finds the URL, so put auth in front of it.

To stop confirming every call, open **Settings > Connectors > kleinanzeigen**
and set the tools' dropdown on the right to **Always allow**.

## Notes
- Search quirks worth knowing: `total` is capped at 10000 by Kleinanzeigen (so
  that value means "at least"), ads flagged `is_top_ad` are paid placements
  pinned above the sort order (`include_top_ads=False` for an honest price
  ranking), and a `null` price means "zu verschenken" or "VB" -- see
  `price_type`.
- `data/categories.json` is a flattened snapshot of Kleinanzeigen's category
  tree (title, id, children), built by `scripts/build_categories.py` from the
  live `api/categories.json` (which ships the tree wrapped in JAXB envelopes
  and a single "Alle Kategorien" pseudo-root). Re-run it if Kleinanzeigen
  changes their categories.
- API details are documented in [`search_api.md`](search_api.md).
- This uses Kleinanzeigen's internal mobile API, not an official one. Be nice to it.

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

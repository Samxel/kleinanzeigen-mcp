# Kleinanzeigen API

The Kleinanzeigen Android app talks to a REST-ish JSON API split across a few
hosts. Responses from `api.kleinanzeigen.de` are JAXB-serialized XML turned
into JSON (see [Response shape](#response-shape) below).
`gateway.kleinanzeigen.de` (newer services) mostly returns plain JSON.

## Hosts

| Host | Purpose |
|---|---|
| `api.kleinanzeigen.de` | Search, ads, categories, seller profile, locations -- the classic REST API |
| `gateway.kleinanzeigen.de` | Newer services: seller reputation, homepage feed, consent, experiments, recommendation search |
| `img.kleinanzeigen.de` | Image CDN |
| `autocomplete.kleinanzeigen.de` | Algolia-backed search-suggestion typeahead |

`api.kleinanzeigen.de` and `gateway.kleinanzeigen.de` share a TLS cert
(SAN covers both) but are otherwise separate services.

## Headers

| Header | Value |
|---|---|
| `authorization` | `Basic YW5kcm9pZDpUYVI2MHBFdHRZ` (static, decodes to `android:TaR60pEttY`) |
| `x-ebayk-app` | App installation id, see [Auth](#auth) |
| `x-ebayk-userid-token` | Empty when logged out |
| `user-agent` | `Kleinanzeigen/2026.37.1 (Android 14; ...)` |
| `x-ecg-user-agent` | `ebayk-android-app-2026.37.1` |
| `x-ecg-user-version` | App version, e.g. `2026.37.1` |

## Auth

`api.kleinanzeigen.de` needs a **static** Basic-auth credential baked into the
app plus a **free-form client id** (`x-ebayk-app`): a UUIDv4 immediately
followed by the epoch-millis timestamp of when it was generated, no separator
(e.g. `7243bedb-2427-4f72-bf89-567ecb1c74661789285561410`). Across several
captured app launches this id was different every time and a brand-new,
never-before-seen value was accepted immediately -- there's no visible
registration call, so it looks like the server does not validate it, just logs
it. `main.py` generates one per process.

## Confirmed endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `api.kleinanzeigen.de/api/ads.json` | The real search. See [Search](#search) |
| `GET` | `api.kleinanzeigen.de/api/ads/{id}.json` | Full ad detail. See [Ad detail](#ad-detail) |
| `GET` | `api.kleinanzeigen.de/api/ads/similar/{id}.json` | Similar ads, same shape as search results (captured, not wrapped in a tool) |
| `GET` | `api.kleinanzeigen.de/api/ads/seller-other-ads/{id}.json` | Other ads from the same seller (captured, not wrapped in a tool) |
| `GET` | `api.kleinanzeigen.de/api/users/public/{id}/profile.json` | Seller profile, plain JSON. See [Seller info](#seller-info). The one endpoint with IP-range anti-fraud (see below) |
| `GET` | `gateway.kleinanzeigen.de/user-reputation-service/public/users/{id}/reputation-summary` | Seller reputation score, plain JSON |
| `GET` | `api.kleinanzeigen.de/api/categories.json` | Full category tree, JAXB-nested; flattened by `scripts/build_categories.py` |
| `GET` | `api.kleinanzeigen.de/api/ads/search-metadata/{categoryId}.json` | The server's own search-param schema, global params plus this category's `attr[]` filters. See [Category filters](#category-filters) |
| `GET` | `api.kleinanzeigen.de/api/locations.json?depth=1&q=<prefix>` | Location/region typeahead, returns ids for `locationId` |
| `POST` | `autocomplete.kleinanzeigen.de/1/indexes/ebayk_prod_suggest/query` | Algolia search-suggestion typeahead (captured, auth not yet inspected) |
| `GET` | `api.kleinanzeigen.de/api/v2/counters/ads/watchlist?adIds=<id>` | Whether an ad is on the current (anonymous) watchlist -- only the read side was captured, no add/remove call |
| `GET` | `img.kleinanzeigen.de/api/v1/prod-ads/images/{hash}?rule=$_N.AUTO` | Image CDN; `N` selects size (`0`=thumbnail, `1`=large, `2`=teaser, `59`=extraLarge, `57`=XXL) |

## Search

```
GET api.kleinanzeigen.de/api/ads.json
    ?q=<text>                        free-text query
    &categoryId=<id>                 numeric category id
    &attr[<key>]=<value>              category-specific attribute filter, e.g. attr[pc_zubehoer_software.art]=grafikkarten
    &locationId=<id>                 from locations.json
    &zipcode=<plz>                    German postcode, alternative to locationId
    &distance=<km>&distanceUnit=KM   radius around locationId/zipcode
    &minPrice=<n>&maxPrice=<n>&priceCurrency=EUR
    &adType=OFFERED|WANTED
    &posterType=PRIVATE|COMMERCIAL
    &page=0&size=30                  paging
    &sortType=RECOMMENDED            or DATE_DESCENDING / PRICE_ASCENDING / PRICE_DESCENDING / DISTANCE_ASCENDING
    &pictureRequired=false&buyNowOnly=false&shippable=false
    &includeTopAds=true
    &limitTotalResultCount=true
```

All of the above (including the full `sortType`/`adType`/`posterType` enums)
come straight from the server's own `ads-search-options` schema (see
[Category filters](#category-filters)), not guesses.

Two behaviours worth knowing, both confirmed live:

- `limitTotalResultCount=true` caps `paging.numFound` at **10000**, so a broad
  query reports exactly 10000 rather than a real count. Narrow queries report
  the true number.
- `includeTopAds=true` pins paid "TOP" placements at the head of the result
  **regardless of `sortType`**, so a price sort does not start at the cheapest
  ad until you pass `includeTopAds=false`.

Response: `{searchOptions, "{...}ads": {value: {ad: [...], paging: {numFound, ...}, ...}}}`.
Each `ad` has `id` (bare string), `title`/`description` (`{value: ...}`,
HTML with `<br />` line breaks and entities), `price.amount`/`price.currency-iso-code`,
`ad-address`, `category.id`, `user-id`, `store-title`, `seller-account-type`,
`features-active` (look for `name: "TOPAD"`), `pictures.picture[].link[]`
(pick `rel: "large"`), and a `link[]` array (`rel: "self-public-website"` is
the human-facing URL). See `_summarize_ad_hit` in `main.py`.

## Ad detail

```
GET api.kleinanzeigen.de/api/ads/{id}.json
```

Response: `{"{...}ad": {value: {...}}}` -- a single ad in the same shape as a
search hit but far richer: full `description`, precise `ad-address`
(street/state/zip/**latitude**/**longitude**/radius), `ad-type`
(OFFERED/WANTED), `ad-status`, `attributes.attribute[]` (name + localized
value per attribute), `shipping-options.shipping-option[].id`, `buy-now`,
`user-rating`, and `locations.location[]` (the resolved location tree entry
for the ad's postcode). See `_summarize_ad_detail` in `main.py`.

## Seller info

Two calls, both plain JSON (no JAXB wrapping):

```
GET api.kleinanzeigen.de/api/users/public/{sellerId}/profile.json
GET gateway.kleinanzeigen.de/user-reputation-service/public/users/{sellerId}/reputation-summary
```

Profile: `id`, `userSince`, `contactName`, `posterType`, `counters`
(`historicalAds`, `onlineAds`, `followers`), `replyIndicators.replySpeed`,
`userBadges.badges[]`, `userRatings.averageRating`. Reputation:
`total`/`manual`/`automatic`, each `{averageRating, starRating, ratingReviewCount}`.

**IP-range anti-fraud.** The profile endpoint (and only that one -- search, ad
detail, categories, locations, search-metadata and the reputation service all
stay 200) answers `403` with an HTML page reading "IP-Bereich vorübergehend
gesperrt" from VPN and datacenter ranges. The body blames the range rather than
the caller ("kann auch durch andere Personen erfolgt sein"), so it is not a
rate limit you can wait out -- it needs a different connection.
`get_seller_info` still returns the reputation half when this happens.

## Category filters

```
GET api.kleinanzeigen.de/api/ads/search-metadata/{categoryId}.json
```

Response: `{"{...}ads-search-options": {value: {...}}}` -- the server's own
documentation of every `ads.json` search param (global ones like `sortType`,
`adType`, `posterType`, `distanceUnit` with their full `supported-value[]`
enums, plus this category's `attributes.attribute[]` with category-specific
`name` (the `attr[]` key) and `supported-value[]` (the `attr[]` values). This
is what `search_kleinanzeigen`'s enums and `get_category_filters` are built
from -- query it again for a category rather than guessing new attribute
keys/values.

## Response shape

Every scalar field on `api.kleinanzeigen.de` comes wrapped as `{"value": ...}`
(a JAXB/XML-to-JSON artifact), and some are wrapped twice (e.g.
`price["currency-iso-code"] = {"value": {"value": "EUR", "localized-label": "€"}}`).
Top-level collections are keyed by their XML namespace URI, e.g.
`"{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ads"`. `main.py`'s `_v`
and `_ns` helpers unwrap both. `gateway.kleinanzeigen.de` and the seller
profile/reputation endpoints are plain JSON with no such wrapping.

## Categories

`categories.json` returns a deeply nested tree under the same JAXB envelope: a
single "Alle Kategorien" pseudo-root whose `category[]` children are the real
top-level categories. Each node has a bare `id` (numeric, what `categoryId`
takes), `id-name.value` (a slug), `localized-name.value` (display name) and a
`category` array of children. `scripts/build_categories.py` fetches this fresh
and flattens it (dropping the pseudo-root) into `data/categories.json`.

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
import httpx
import asyncio
import functools
import html
import json
import re
import unicodedata
import uuid
import time
from pathlib import Path
from typing import Optional, Union, Literal
import logging

BASE_URL = "https://api.kleinanzeigen.de/api"
GATEWAY_URL = "https://gateway.kleinanzeigen.de"

KA_CLIENT = "Kleinanzeigen/2026.37.1 (Android 14; google sdk_gphone64_x86_64)"
KA_ECG_USER_AGENT = "ebayk-android-app-2026.37.1"
KA_ECG_USER_VERSION = "2026.37.1"

# --- Request authentication ------------------------------------------------
# Every request carries a static HTTP Basic credential baked into the app
# (reverse-engineered from the APK, not user-specific). Decodes to
# "android:TaR60pEttY".
KA_BASIC_AUTH = "Basic YW5kcm9pZDpUYVI2MHBFdHRZ"

# `x-ebayk-app` identifies the app installation: a UUIDv4 immediately followed
# by the epoch-millis timestamp of when it was generated, no separator (e.g.
# "7243bedb-2427-4f72-bf89-567ecb1c74661789285561410"). Captured traffic shows
# a fresh, never-before-seen value accepted immediately with no separate
# registration call, so it looks like a free-form client-generated id the
# server does not validate -- generated once per process and reused here.
_installation_id = f"{uuid.uuid4()}{int(time.time() * 1000)}"

HOST = "127.0.0.1"
PORT = 8000
MCP_PATH = "/mcp"

MAX_RETRIES = 2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

MAX_ROWS = 30
# How deep a client-side filter (title_only/require/exclude) may page before
# giving up, so a term that matches nothing can't walk the whole catalogue.
FILTER_MAX_SCAN = 250

mcp = MCPServer("kleinanzeigen-mcp")
client = httpx.AsyncClient(http2=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Confirmed against the server's own ads-search-options schema
# (api/ads/search-metadata/{categoryId}.json) rather than guessed.
Sort = Literal["RECOMMENDED", "DATE_DESCENDING", "PRICE_ASCENDING", "PRICE_DESCENDING", "DISTANCE_ASCENDING"]
AdType = Literal["OFFERED", "WANTED"]
PosterType = Literal["PRIVATE", "COMMERCIAL"]


def _upstream_message(status: int, what: str, body: str = "") -> str:
    """Phrase an HTTP failure in terms the caller can act on, without the
    internal url and MDN link httpx puts in its own message."""
    if status == 404:
        return f"no {what} found -- wrong id, or the ad has been taken down"
    if status == 400:
        return f"Kleinanzeigen rejected the {what} request (400); check the arguments you passed"
    if status in (401, 403):
        # a blocked IP range and a stale credential both come back as 403, but
        # only the block says so in the body -- they need opposite fixes
        if "gesperrt" in body or "blocked" in body.lower():
            return (f"Kleinanzeigen blocked this IP range on the {what} request ({status}). Their "
                    f"anti-fraud rejects whole ranges (VPN and datacenter IPs in particular), so "
                    f"this usually needs a different connection, not a retry. Search and ad "
                    f"lookups are unaffected -- only the seller profile enforces it.")
        return (f"Kleinanzeigen refused the {what} request ({status}) -- the client credential "
                f"in main.py (KA_BASIC_AUTH) may be outdated")
    if status == 429:
        return f"Kleinanzeigen rate-limited the {what} request (429) -- slow down and retry later"
    return f"Kleinanzeigen failed on the {what} request (HTTP {status})"


def _tool_errors(what: str):
    """Return failures as ``{"error": ...}`` rather than raising, so every tool
    fails the same readable way and the caller sees *why* -- an MCP client turns
    a raised exception into a bare "Error executing tool". ``what`` names the
    thing being fetched, for the message."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ValueError as exc:  # our own argument validation
                return {"error": str(exc)}
            except httpx.HTTPStatusError as exc:
                return {"error": _upstream_message(exc.response.status_code, what, exc.response.text)}
            except httpx.HTTPError as exc:
                return {"error": f"could not reach Kleinanzeigen for the {what} request "
                                 f"({type(exc).__name__})"}
        return wrapper
    return decorator


def _rows(rows: int) -> int:
    """Validate a page size rather than quietly clamping 0 up to 1."""
    rows = int(rows)
    if rows < 1:
        raise ValueError(f"rows must be at least 1 (got {rows}).")
    return min(rows, MAX_ROWS)


def _check_range(name: str, low, high) -> None:
    """Reject an inverted range instead of letting Kleinanzeigen drop the filter
    and quietly answer with everything."""
    if low is not None and high is not None and low > high:
        raise ValueError(
            f"min_{name} ({low}) is above max_{name} ({high}) -- an inverted range is "
            f"ignored by Kleinanzeigen and would silently return unfiltered results. Swap them."
        )


def _pagination(total, page: int, seen: int, returned: int) -> dict:
    """Where the caller stands in the result set, so paging can be stopped on a
    signal instead of on a repeated page. ``seen`` counts the ads consumed from
    the catalogue so far (which post-filtering can push past ``returned``)."""
    total = int(total) if str(total or "").isdigit() else None
    more = not (total is not None and seen >= total)
    return {
        "total": total,
        "rows_returned": returned,
        "next_page": page + 1 if more else None,
        "has_more": more,
    }


def _auth_headers(*, user_token: str = "") -> dict:
    """Headers the app sends on every api.kleinanzeigen.de / gateway.kleinanzeigen.de
    call. `user_token` is left empty when not logged in."""
    return {
        "authorization": KA_BASIC_AUTH,
        "x-ebayk-app": _installation_id,
        "x-ebayk-userid-token": user_token,
        "user-agent": KA_CLIENT,
        "x-ecg-user-agent": KA_ECG_USER_AGENT,
        "x-ecg-user-version": KA_ECG_USER_VERSION,
        "accept-encoding": "gzip",
    }


async def _get(endpoint: str, params: Optional[dict] = None) -> dict:
    """GET an api.kleinanzeigen.de endpoint. See `_request`."""
    return await _request(f"{BASE_URL}/{endpoint}", params)


async def _get_gateway(endpoint: str, params: Optional[dict] = None) -> dict:
    """GET a gateway.kleinanzeigen.de endpoint (newer services: seller
    reputation, homepage feed, ...). See `_request`."""
    return await _request(f"{GATEWAY_URL}/{endpoint}", params)


async def _request(url: str, params: Optional[dict] = None) -> dict:
    """GET a kleinanzeigen.de URL, retrying transient failures (timeouts,
    429, 5xx) with exponential backoff. Other 4xx errors fail immediately."""
    headers = _auth_headers()
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                raise
        else:
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                response.raise_for_status()
                return response.json()
        delay = 0.5 * (2 ** attempt)
        logger.warning("Request to '%s' failed (attempt %d/%d), retrying in %.1fs",
                        url, attempt + 1, MAX_RETRIES + 1, delay)
        await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# JAXB unwrapping
# ---------------------------------------------------------------------------
# Kleinanzeigen's JSON is JAXB-serialized XML (com.ebay.ecg.api.spec...), so
# scalar fields don't come as plain values -- they're wrapped as {"value": ...},
# and top-level collections are keyed by their XML namespace URI. `_v` unwraps
# the former; `_ns` picks out the latter regardless of the exact namespace string.
def _v(node, default=None):
    return node.get("value", default) if isinstance(node, dict) else default


def _ns(container: dict, local_name: str) -> dict:
    for key, val in container.items():
        if key.endswith(f"}}{local_name}") or key == local_name:
            return _v(val, {})
    return {}


_CONTENT_TYPE_FORMAT = {
    "image/webp": "webp",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
}


def _image_urls(pictures: dict) -> list[str]:
    urls = []
    for pic in (pictures or {}).get("picture", []):
        for link in pic.get("link", []):
            if link.get("rel") == "large":
                urls.append(link["href"])
                break
    return urls


# ---------------------------------------------------------------------------
# Categories (shipped tree, built by scripts/build_categories.py)
# ---------------------------------------------------------------------------
def _fold(s: str) -> str:
    """Lowercase and strip accents, so "Grün" and "gruen" compare equal."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def _norm(s: str) -> str:
    """Normalise a label for lookup: lowercase, strip accents, drop all spaces."""
    return "".join(_fold(s).split())


def _load_categories() -> list[dict]:
    path = Path(__file__).parent / "data" / "categories.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.getLogger(__name__).warning("categories.json not found -- list_categories disabled")
        return []


_CATEGORIES = _load_categories()


def _walk_categories(nodes, trail, out):
    for nd in nodes:
        label = nd.get("title") or ""
        path = trail + [label]
        out.append((nd, " / ".join(path)))
        _walk_categories(nd.get("childs", []), path, out)


# ---------------------------------------------------------------------------
# Text matching (client-side title/require/exclude filters)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Ads fuse series and model number ("RTX4070"); split those so a keyword written
# with a space still matches, and the other way round.
_FUSED_RE = re.compile(r"^([a-z]{2,4})(\d{3,5})$")
# A number and its unit: sellers write the same storage size as "128GB",
# "128 GB", "128gb" or "256Gb", so a term given in one of those has to match all.
_NUM_UNIT_RE = re.compile(r"^(\d+)\s*([a-z]+)$")


def _tokens(text: str) -> set:
    """Comparable word tokens of a title or keyword. Fused model codes are
    replaced by their parts on both sides, so "RTX4070" and "RTX 4070" match
    each other whichever one the keyword uses."""
    out = set()
    for token in _TOKEN_RE.findall(_fold(text or "")):
        fused = _FUSED_RE.match(token)
        out.update(fused.groups() if fused else [token])
    return out


def _term_forms(term: str) -> list[set]:
    """The token sets a filter term may appear as. Everything is one form,
    except a number with a unit, which is also accepted split in two -- that way
    a term matches whichever way the seller spelled it."""
    folded = _fold(term).strip()
    match = _NUM_UNIT_RE.match(folded)
    if not match:
        return [_tokens(folded)]
    number, unit = match.groups()
    return [{f"{number}{unit}"}, {number, unit}]


def _has_term(tokens: set, forms: list[set]) -> bool:
    """Whether a title (or ad text) carries a filter term. A word matches in
    full, or as the tail of a German compound ("kabel" catches "Ladekabel"), but
    never one that merely starts with it -- otherwise "pro" would throw away
    every "Prozessor" and be useless for separating an iPhone 13 from a 13 Pro."""
    return any(all(any(token == word or token.endswith(word) for token in tokens)
                   for word in form)
               for form in forms)


def _resolve_category(category: Union[int, str]) -> int:
    """Resolve a category given as id or name to its numeric id, so the caller
    can pass "PC-Zubehör & Software" instead of looking up 225 first."""
    text = str(category).strip()
    if text.isdigit():
        return int(text)
    flat: list = []
    _walk_categories(_CATEGORIES, [], flat)
    wanted = _norm(text)

    exact = [(n, p) for n, p in flat if _norm(n.get("title") or "") == wanted]
    if exact:
        # a name can repeat deeper in the tree ("Elektronik" is also a
        # Dienstleistungen child); the shallower one is what was meant
        depth = min(p.count("/") for _, p in exact)
        top = [(n, p) for n, p in exact if p.count("/") == depth]
        if len(top) == 1:
            return top[0][0]["id"]
        paths = ", ".join(p for _, p in top)
        raise ValueError(f"Category name {text!r} is ambiguous ({paths}). Pass the id instead.")

    partial = [(n, p) for n, p in flat if wanted in _norm(p)]
    if len(partial) == 1:
        return partial[0][0]["id"]
    if partial:
        raise ValueError(f"Category {text!r} is ambiguous. Closest matches: "
                         f"{', '.join(p for _, p in partial[:8])}. Pass the id instead.")
    raise ValueError(f"Unknown category {text!r}. Use list_categories to find one -- and note "
                     f"the tree stops fairly high up, so a finer cut like 'Grafikkarten' is an "
                     f"attribute value (get_category_filters), not a category.")


def _clean_description(value: Optional[str]) -> str:
    """Ad descriptions come as HTML (``<br />`` line breaks, entities);
    render them as plain, readable text."""
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _ad_link(ad: dict, rel: str) -> Optional[str]:
    return next((l["href"] for l in ad.get("link", []) if l.get("rel") == rel), None)


def _summarize_ad_hit(ad: dict) -> dict:
    price = ad.get("price") or {}
    address = ad.get("ad-address") or {}
    features = (ad.get("features-active") or {}).get("feature-active", [])
    return {
        "id": ad.get("id"),
        "title": html.unescape(_v(ad.get("title")) or ""),
        "description": _clean_description(_v(ad.get("description"))),
        "price_amount": _v(price.get("amount")),
        "price_currency": _v(_v(price.get("currency-iso-code"))),
        "price_type": _v(price.get("price-type")),
        "location": _v(address.get("state")),
        "zip_code": _v(address.get("zip-code")),
        "category_id": (ad.get("category") or {}).get("id"),
        "seller_id": _v(ad.get("user-id")),
        "store_title": _v(ad.get("store-title")),
        "seller_account_type": _v(ad.get("seller-account-type")),
        "is_top_ad": any(f.get("name") == "TOPAD" for f in features),
        "start_date": _v(ad.get("start-date-time")),
        # one preview url only -- the full set is in get_ad_detail, and the
        # pictures themselves in get_ad_images
        "image_url": (_image_urls(ad.get("pictures")) or [None])[0],
        "image_count": len((ad.get("pictures") or {}).get("picture", [])),
        "url": _ad_link(ad, "self-public-website"),
    }


def _summarize_attributes(attributes: dict) -> dict:
    """Flatten an ad's `attributes.attribute[]` list into {name: label}, e.g.
    {"pc_zubehoer_software.condition": "Neu"}."""
    out = {}
    for attr in (attributes or {}).get("attribute", []):
        values = attr.get("value") or []
        label = ", ".join(v.get("localized-label", v.get("value", "")) for v in values)
        out[attr.get("name")] = label
    return out


def _summarize_ad_detail(ad: dict) -> dict:
    price = ad.get("price") or {}
    address = ad.get("ad-address") or {}
    category = ad.get("category") or {}
    return {
        "id": ad.get("id"),
        "title": html.unescape(_v(ad.get("title")) or ""),
        "description": _clean_description(_v(ad.get("description"))),
        "ad_type": _v(ad.get("ad-type")),
        "ad_status": _v(ad.get("ad-status")),
        "price_amount": _v(price.get("amount")),
        "price_currency": _v(_v(price.get("currency-iso-code"))),
        "price_type": _v(price.get("price-type")),
        "location": _v(address.get("state")),
        "zip_code": _v(address.get("zip-code")),
        "latitude": _v(address.get("latitude")),
        "longitude": _v(address.get("longitude")),
        "category_id": category.get("id"),
        "category_name": _v(category.get("localized-name")),
        "seller_id": _v(ad.get("user-id")),
        "seller_name": _v(ad.get("contact-name")),
        "seller_account_type": _v(ad.get("seller-account-type")),
        "seller_rating": _v((ad.get("user-rating") or {}).get("averageRating")),
        "attributes": _summarize_attributes(ad.get("attributes")),
        "shipping_options": [o["id"] for o in (ad.get("shipping-options") or {}).get("shipping-option", [])],
        "buy_now": (ad.get("buy-now") or {}).get("selected") == "true",
        "start_date": _v(ad.get("start-date-time")),
        "images": _image_urls(ad.get("pictures")),
        "url": _ad_link(ad, "self-public-website"),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
@_tool_errors("search")
async def search_kleinanzeigen(
    query: Optional[str] = None,
    *,
    category: Optional[Union[int, str]] = None,
    attributes: Optional[dict[str, Union[str, list[str]]]] = None,
    location_id: Optional[int] = None,
    zip_code: Optional[str] = None,
    distance_km: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    price_currency: str = "EUR",
    ad_type: Optional[AdType] = None,
    poster_type: Optional[PosterType] = None,
    sort: Sort = "RECOMMENDED",
    title_only: bool = False,
    require: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    rows: int = 5,
    page: int = 0,
    picture_required: bool = False,
    buy_now_only: bool = False,
    shippable: bool = False,
    include_top_ads: bool = True,
) -> dict:
    """Search Kleinanzeigen listings. At least one of ``query`` or ``category``
    is required.

    Scope to a ``category`` when you can: a bare ``query`` matches the **whole
    ad text**, so it drags in accessories, bundles and spare parts, and with
    ``sort="PRICE_ASCENDING"`` that junk takes the top spots.

    **Put the model in ``query`` and every spec in ``require``.** Sellers write
    a storage size as "128GB", "128 GB" or "256Gb" and many leave it out of the
    title, so ``query="iPhone 13 128 GB", title_only=True`` finds almost nothing
    while ``query="iPhone 13", require=["128gb"]`` finds what you meant.

    Three filters, all applied here over what Kleinanzeigen returns:

    - ``title_only=True`` -- every word of ``query`` must be in the **title**.
      A glued-together model code matches either way round ("RTX4070" finds
      "RTX 4070"), but a unit is not normalized: "128GB" does **not** find
      "128 GB". Identity only.
    - ``require`` -- all of these must appear in the **title or description**,
      e.g. ``["128gb"]``. A number with its unit matches however it is spelled.
      Capacity, RAM, colour, model year belong here.
    - ``exclude`` -- drop ads whose **title** carries any of these, e.g.
      ``["pro", "max"]``. Matches a whole word or a German compound tail
      ("kabel" catches "Ladekabel"), never a mere prefix, so "pro" spares
      "Prozessor". Model words are safe to exclude; **ordinary nouns are not**
      ("akku", "display" appear in real listings you wanted).

    Returns ``{total, rows_returned, next_page, has_more, results}``, plus
    ``scanned`` when a client-side filter ran. ``results`` are trimmed ads
    (id, title, ~250-char description, price, location, seller, one
    ``image_url``); ``get_ad_detail`` has the full text and every attribute,
    ``get_ad_images`` the pictures themselves. ``total`` is capped at 10000 by
    Kleinanzeigen, so that value means "at least", not a real count.

    Ads with ``is_top_ad`` are paid placements pinned above the sort order --
    when you sort by price, set ``include_top_ads=False`` or the first rows
    won't be the cheapest. A ``price_amount`` of ``null`` is normal: it means
    "zu verschenken" or "VB" (see ``price_type``), and those sort first
    ascending.

    Args:
        query: Free-text search term, e.g. "fahrrad" or "rtx 5080".
        category: Category id (int) or name ("PC-Zubehör & Software");
            ``list_categories`` finds it. Includes subcategories.
        attributes: Category-specific filters, e.g.
            {"pc_zubehoer_software.art": "grafikkarten"} -- narrows far better
            than words in ``query``. ``get_category_filters(category)`` lists
            the valid keys and values; one marked ``multi_select`` also takes a
            list, e.g. {"...art": ["grafikkarten", "mainboards"]}.
        location_id: Restrict to a location/region, from ``search_locations``.
        zip_code: Restrict to a German postcode instead of ``location_id``.
        distance_km: Radius around ``location_id``/``zip_code`` in kilometres.
        min_price / max_price: Price range.
        price_currency: Currency for the price range. Default "EUR".
        ad_type: "OFFERED" ("Ich biete") or "WANTED" ("Ich suche").
        poster_type: "PRIVATE" or "COMMERCIAL".
        sort: "RECOMMENDED" (default), "DATE_DESCENDING" (newest),
            "PRICE_ASCENDING", "PRICE_DESCENDING" or "DISTANCE_ASCENDING"
            (needs ``location_id``/``zip_code``).
        rows: Max results to return. Default 5; raise it when you actually need
            more, since each ad costs a few hundred tokens.
        page: Zero-based page index; pass back ``next_page`` to continue.
        picture_required: Only ads that have at least one picture.
        buy_now_only: Only ads with "Direkt kaufen" enabled.
        shippable: Only ads that offer shipping.
        include_top_ads: Keep paid "TOP" placements in the results. Default
            True (what the app does); set False for an honest price ranking.
    """
    if not query and category is None:
        raise ValueError("Provide 'query' and/or 'category'.")
    _check_range("price", min_price, max_price)
    rows = _rows(rows)

    wanted = _tokens(query) if (title_only and query) else set()
    required = [_term_forms(t) for t in (require or []) if str(t).strip()]
    excluded = [_term_forms(t) for t in (exclude or []) if str(t).strip()]
    post_filtered = bool(wanted or required or excluded)

    params: list[tuple[str, str]] = [
        ("sortType", sort),
        ("pictureRequired", str(picture_required).lower()),
        ("buyNowOnly", str(buy_now_only).lower()),
        ("shippable", str(shippable).lower()),
        ("includeTopAds", str(include_top_ads).lower()),
        ("limitTotalResultCount", "true"),
    ]
    if query:
        params.append(("q", query))
    if category is not None:
        params.append(("categoryId", str(_resolve_category(category))))
    if location_id is not None:
        params.append(("locationId", str(location_id)))
    if zip_code is not None:
        params.append(("zipcode", zip_code))
    if distance_km is not None:
        params.append(("distance", str(distance_km)))
        params.append(("distanceUnit", "KM"))
    if min_price is not None:
        params.append(("minPrice", str(min_price)))
    if max_price is not None:
        params.append(("maxPrice", str(max_price)))
    if min_price is not None or max_price is not None:
        params.append(("priceCurrency", price_currency))
    if ad_type is not None:
        params.append(("adType", ad_type))
    if poster_type is not None:
        params.append(("posterType", poster_type))
    for key, value in (attributes or {}).items():
        joined = ",".join(value) if isinstance(value, list) else value
        params.append((f"attr[{key}]", joined))

    def keep(hit: dict) -> bool:
        tokens = _tokens(hit["title"])
        if wanted and not wanted <= tokens:
            return False
        if any(_has_term(tokens, forms) for forms in excluded):
            return False
        if required:
            # a spec is written wherever the seller felt like it, so look at the
            # whole ad rather than demanding it in the title
            text = tokens | _tokens(hit["description"])
            if not all(_has_term(text, forms) for forms in required):
                return False
        return True

    # A client-side filter has to page deeper than the caller asked for, so it
    # pulls full pages and keeps going until `rows` survivors are found.
    page_size = MAX_ROWS if post_filtered else rows
    results: list = []
    cursor, total, scanned = page, None, 0
    while True:
        page_params = params + [("page", str(cursor)), ("size", str(page_size))]
        payload = _ns(await _get("ads.json", params=page_params), "ads")
        ads = payload.get("ad", [])
        total = (payload.get("paging") or {}).get("numFound", total)
        for ad in ads:
            scanned += 1
            hit = _summarize_ad_hit(ad)
            if keep(hit):
                results.append(hit)
                if len(results) >= rows:
                    break
        if not post_filtered or len(results) >= rows or not ads or scanned >= FILTER_MAX_SCAN:
            break
        cursor += 1

    consumed = page * page_size + scanned
    result = {**_pagination(total, cursor, consumed, len(results)), "results": results}
    if post_filtered:
        result["scanned"] = scanned
    return result


@mcp.tool()
@_tool_errors("ad")
async def get_ad_detail(ad_id: int) -> dict:
    """Everything about one ad: the full description, itemised attributes
    ("Zustand", "Versand", ...), precise location with coordinates, shipping
    options and image urls. Run it on an ``id`` from a search hit whenever the
    trimmed search summary isn't enough to answer.

    To actually look at the photos use ``get_ad_images``; for the seller's
    profile and reputation ``get_seller_info`` with the result's ``seller_id``.

    Args:
        ad_id: The Kleinanzeigen ad id.
    """
    data = await _get(f"ads/{ad_id}.json")
    return _summarize_ad_detail(_ns(data, "ad"))


@mcp.tool(structured_output=False)
async def get_ad_images(ad_id: int, max_images: int = 4) -> list:
    """Fetch an ad's photos and return them as images you can actually look at.

    Downloads up to ``max_images`` photos from Kleinanzeigen's CDN server-side
    and returns them as image content blocks (base64), so a vision-capable
    client sees the real pictures instead of just URLs. Call it with an id from
    a search hit.

    Reach for this whenever the pictures carry information you can't take on
    trust from the text: the description is the seller's claim, the photos are
    the evidence. Typical cases are judging the real condition (wear,
    scratches, damage, completeness), reading details that only appear in an
    image (a screenshot of specs, a label, a model or serial number, a display),
    or confirming the item matches the description. As a rule of thumb, if your
    answer depends on what the thing actually looks like, look at it.

    Args:
        ad_id: The Kleinanzeigen ad id.
        max_images: How many photos to fetch, 1-10. Default 4.
    """
    max_images = max(1, min(int(max_images), 10))
    try:
        data = await _get(f"ads/{ad_id}.json")
    except httpx.HTTPStatusError as exc:
        return [_upstream_message(exc.response.status_code, "ad", exc.response.text)]
    except httpx.HTTPError as exc:
        return [f"could not reach Kleinanzeigen for ad {ad_id} ({type(exc).__name__})"]

    ad = _ns(data, "ad")
    urls = _image_urls(ad.get("pictures"))[:max_images]
    if not urls:
        return [f"No images found for ad {ad_id}."]

    async def fetch(url: str):
        try:
            response = await client.get(url, headers={"user-agent": KA_CLIENT})
            response.raise_for_status()
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            return Image(data=response.content, format=_CONTENT_TYPE_FORMAT.get(ctype, "jpeg"))
        except Exception as exc:  # a single broken image shouldn't fail the tool
            logger.warning("image download failed (%s): %s", url, exc)
            return None

    fetched = await asyncio.gather(*(fetch(u) for u in urls))
    pictures = [img for img in fetched if img is not None]
    title = html.unescape(_v(ad.get("title")) or "") or f"ad {ad_id}"
    return [f'{len(pictures)} image(s) for "{title}" (ad {ad_id}):', *pictures]


@mcp.tool()
@_tool_errors("seller")
async def get_seller_info(seller_id: int) -> dict:
    """Who is selling: name, private vs commercial, member-since date, how
    many ads they have run, followers, typical reply speed and Kleinanzeigen's
    reputation score. Use it for the trust or plausibility check an ad itself
    doesn't answer -- a one-day-old account dumping twenty phones reads very
    differently from a five-year member with one listing.

    The profile half is the one endpoint Kleinanzeigen guards with IP-range
    anti-fraud, so from a VPN or datacenter address it can 403 while everything
    else works. That is reported in ``partial`` rather than failing the call.

    Args:
        seller_id: The seller's user id, from a search hit's or ad detail's
            ``seller_id``.
    """
    # two independent services -- report whichever half answers instead of
    # losing a usable trust check to the other one's failure
    async def half(coro, name):
        try:
            return await coro, None
        except httpx.HTTPStatusError as exc:
            return {}, f"{name}: {_upstream_message(exc.response.status_code, name, exc.response.text)}"
        except httpx.HTTPError as exc:
            return {}, f"{name}: could not reach Kleinanzeigen ({type(exc).__name__})"

    profile, profile_error = await half(
        _get(f"users/public/{seller_id}/profile.json"), "profile")
    reputation, reputation_error = await half(
        _get_gateway(f"user-reputation-service/public/users/{seller_id}/reputation-summary"),
        "reputation")
    if profile_error and reputation_error:
        return {"error": f"{profile_error}; {reputation_error}"}
    counters = profile.get("counters") or {}
    result = {
        "id": profile.get("id") or seller_id,
        "name": profile.get("contactName"),
        "account_type": profile.get("posterType"),
        "member_since": profile.get("userSince"),
        "reply_speed": (profile.get("replyIndicators") or {}).get("replySpeed"),
        "active_ads": counters.get("onlineAds"),
        "total_ads": counters.get("historicalAds"),
        "followers": counters.get("followers"),
        "average_rating": (profile.get("userRatings") or {}).get("averageRating"),
        "reputation_score": (reputation.get("total") or {}).get("averageRating"),
        "reputation_review_count": (reputation.get("total") or {}).get("ratingReviewCount"),
    }
    partial = [e for e in (profile_error, reputation_error) if e]
    if partial:
        result["partial"] = "; ".join(partial)
    return result


@mcp.tool()
@_tool_errors("location")
async def search_locations(query: str) -> list[dict]:
    """Look up location ids for ``search_kleinanzeigen``'s ``location_id``,
    by name prefix (as the app's location picker does). Covers federal states,
    cities and districts. Returns ``[{id, name, region, latitude, longitude,
    radius_km}]``.

    Pair the id with ``distance_km`` to search a radius. For a plain postcode
    search you don't need this -- pass ``zip_code`` to the search directly.

    Args:
        query: Name prefix to search, e.g. "berl" for "Berlin".
    """
    data = await _get("locations.json", params={"depth": 1, "q": query})
    payload = _ns(data, "locations")
    locations = payload.get("location", [])
    out = []
    for loc in locations:
        regions = (loc.get("regions") or {}).get("region") or []
        out.append({
            "id": loc.get("id"),
            "name": _v(loc.get("localized-name")),
            "region": _v(regions[0].get("localized-name")) if regions else None,
            "latitude": _v(loc.get("latitude")),
            "longitude": _v(loc.get("longitude")),
            "radius_km": _v(loc.get("radius")),
        })
    return out


@mcp.tool()
@_tool_errors("category filter")
async def get_category_filters(category: Union[int, str]) -> list[dict]:
    """The attribute filters a category supports, for
    ``search_kleinanzeigen(attributes=...)``. These narrow a search far better
    than extra words in ``query`` -- e.g. in "PC-Zubehör & Software" they cut
    it down to ``grafikkarten`` or ``mainboards`` outright.

    Read straight from Kleinanzeigen's own search-options schema, so the keys
    and values are exact rather than guessed. Returns
    ``[{key, label, type, multi_select, values}]``; ``values`` is
    ``[{value, label}, ...]`` for enum attributes and empty for free-form ones.
    An attribute with ``multi_select`` accepts a list of values at once.

    Args:
        category: Category id (int) or name, same as ``search_kleinanzeigen``.
    """
    data = await _get(f"ads/search-metadata/{_resolve_category(category)}.json")
    payload = _ns(data, "ads-search-options")
    attributes = (payload.get("attributes") or {}).get("attribute", [])
    return [
        {
            "key": attr.get("name"),
            "label": attr.get("localized-label"),
            "type": attr.get("type"),
            "multi_select": attr.get("search-multi-select") == "true",
            "values": [{"value": v.get("value"), "label": v.get("localized-label")}
                       for v in attr.get("supported-value", [])],
        }
        for attr in attributes
    ]


@mcp.tool()
async def list_categories(query: Optional[str] = None, limit: int = 40) -> dict:
    """Browse the category tree to find the ``category`` that
    ``search_kleinanzeigen`` and ``get_category_filters`` take. Scoping a
    search to a category is the single best way to stop a keyword dragging in
    accessories and spare parts.

    Returns ``{count, categories: [{id, title, path}]}``, where ``path`` shows
    where a category sits in the tree ("Elektronik / PC-Zubehör & Software").
    The whole tree (159 categories) ships with the server, so this costs no
    request. Note the tree stops at that level -- finer cuts like "Grafikkarten"
    are attribute filters, from ``get_category_filters``.

    Args:
        query: Case/accent-insensitive substring matched against the whole
            path, e.g. "pc-zubehör" or "elektronik". Omit to list everything,
            up to ``limit``.
        limit: Max number of categories to return. Default 40.
    """
    flat: list = []
    _walk_categories(_CATEGORIES, [], flat)
    q = _norm(query) if query else None
    rows = [{"id": node.get("id"), "title": node.get("title"), "path": path}
            for node, path in flat if not q or q in _norm(path)]
    return {"count": len(rows), "categories": rows[:limit]}


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}{MCP_PATH}"
    logger.info("Starting kleinanzeigen-mcp server on %s", url)
    mcp.run("streamable-http", host=HOST, port=PORT, streamable_http_path=MCP_PATH)

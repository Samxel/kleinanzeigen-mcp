from mcp.server import MCPServer
from mcp.server.mcpserver import Image
import httpx
import asyncio
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

mcp = MCPServer("kleinanzeigen-mcp")
client = httpx.AsyncClient(http2=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Confirmed against the server's own ads-search-options schema
# (api/ads/search-metadata/{categoryId}.json) rather than guessed.
Sort = Literal["RECOMMENDED", "DATE_DESCENDING", "PRICE_ASCENDING", "PRICE_DESCENDING", "DISTANCE_ASCENDING"]
AdType = Literal["OFFERED", "WANTED"]
PosterType = Literal["PRIVATE", "COMMERCIAL"]


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
        "images": _image_urls(ad.get("pictures")),
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
async def search_kleinanzeigen(
    query: Optional[str] = None,
    *,
    category_id: Optional[int] = None,
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
    rows: int = 30,
    page: int = 0,
    picture_required: bool = False,
    buy_now_only: bool = False,
    shippable: bool = False,
) -> dict:
    """Search Kleinanzeigen listings by free-text keyword and/or category --
    this is the endpoint the app's search screen itself uses, separate from the
    Akamai-gated homepage recommendation carousel. Pass at least one of
    ``query`` or ``category_id``.

    Returns ``{total, results: [...]}``. ``results`` are summarized ads (id,
    title, price, location, seller, top-ad flag, images, public listing url)
    -- the numeric ``id`` is what ``get_ad_detail`` takes.

    Args:
        query: Free-text search term, e.g. "fahrrad" or "rtx 5080".
        category_id: Restrict to a numeric category id, from
            ``list_categories`` or a prior result's ``category_id``.
        attributes: Category-specific attribute filters, e.g.
            {"pc_zubehoer_software.art": "grafikkarten"}. An attribute marked
            ``multi_select`` in ``get_category_filters`` also takes a list.
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
        rows: Max results to return (page size). Default 30.
        page: Zero-based page index.
        picture_required: Only ads that have at least one picture.
        buy_now_only: Only ads with "Direkt kaufen" enabled.
        shippable: Only ads that offer shipping.
    """
    params: list[tuple[str, str]] = [
        ("page", str(page)), ("size", str(rows)), ("sortType", sort),
        ("pictureRequired", str(picture_required).lower()),
        ("buyNowOnly", str(buy_now_only).lower()),
        ("shippable", str(shippable).lower()),
        ("includeTopAds", "true"), ("limitTotalResultCount", "true"),
    ]
    if query:
        params.append(("q", query))
    if category_id is not None:
        params.append(("categoryId", str(category_id)))
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

    payload = _ns(await _get("ads.json", params=params), "ads")
    return {
        "total": (payload.get("paging") or {}).get("numFound"),
        "results": [_summarize_ad_hit(ad) for ad in payload.get("ad", [])],
    }


@mcp.tool()
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
        return [f"could not fetch ad {ad_id} (HTTP {exc.response.status_code})"]
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
async def get_seller_info(seller_id: int) -> dict:
    """Who is selling: name, private vs commercial, member-since date, how
    many ads they have run, followers, typical reply speed and Kleinanzeigen's
    reputation score. Use it for the trust or plausibility check an ad itself
    doesn't answer -- a one-day-old account dumping twenty phones reads very
    differently from a five-year member with one listing.

    Args:
        seller_id: The seller's user id, from a search hit's or ad detail's
            ``seller_id``.
    """
    profile = await _get(f"users/public/{seller_id}/profile.json")
    reputation = await _get_gateway(
        f"user-reputation-service/public/users/{seller_id}/reputation-summary")
    counters = profile.get("counters") or {}
    result = {
        "id": profile.get("id"),
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
    return result


@mcp.tool()
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
async def get_category_filters(category_id: int) -> list[dict]:
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
    data = await _get(f"ads/search-metadata/{category_id}.json")
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

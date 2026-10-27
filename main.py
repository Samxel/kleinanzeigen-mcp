# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3.0,<3", "httpx[http2]>=0.28.1"]
# ///
import argparse
import asyncio
import functools
import html
import inspect
import json
import logging
from typing import Optional, Union

import httpx
from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from kleinanzeigen import api, categories, matching, summaries

HOST = "127.0.0.1"
# geizhals-mcp serves on 8000 and willhaben-mcp on 8010, so all three can run
# side by side
PORT = 8020
MCP_PATH = "/mcp"

MAX_ROWS = 30
# How deep a client-side filter (title_only/require/exclude) may page before
# giving up, so a term that matches nothing can't walk the whole catalogue.
FILTER_MAX_SCAN = 250

# Sent once when a client connects, so what every tool shares is said here
# instead of in each tool's description, which the model reads on every turn.
INSTRUCTIONS = """\
Kleinanzeigen.de, Germany's classifieds site. Prices are in EUR.

Which tool to use:
- something to buy: search_kleinanzeigen. Scope it with a category from \
list_categories and narrow it with the category's attributes from \
get_category_filters; a place comes from search_locations.
- one ad in full: get_ad_detail (full text, attributes, shipping), \
get_ad_images (the photos themselves) or get_seller_info (who sells it).

The category tree stops fairly high up: a finer cut like "Grafikkarten" is an \
attribute value of "PC-Zubehör & Software", not a category.

rows is at most 30; page on with the next_page a result returns, has_more says \
whether anything is left. total is capped at 10000 by Kleinanzeigen.

Fields without a value are left out of results.
"""

# The tool list only changes with a new release, so clients on the 2026-07-28
# protocol may keep it for a day instead of asking again on every connect.
mcp = MCPServer("kleinanzeigen-mcp", instructions=INSTRUCTIONS,
                cache_hints={"tools/list": CacheHint(ttl_ms=24 * 60 * 60 * 1000, scope="public")})


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def _prune(value):
    """Drop the null fields from every dict in `value`; lists keep their items."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


# Every tool only reads, so clients can run them without asking each time. All
# but list_categories, which answers from the shipped tree, go out to
# Kleinanzeigen.
ONLINE = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _tool(fn=None, *, annotations: ToolAnnotations = ONLINE):
    """Register `fn` as a tool whose result goes out as compact JSON with its
    null fields left out. Left to the SDK, a dict is pretty-printed with a
    two-space indent and a list becomes one text block per item.
    structured_output stays off: it would send every result a second time as
    structuredContent and add an output schema to the tool listing. The
    docstring is dedented here because only Python 3.13+ does that itself; on
    older ones every description line would carry four spaces of indent."""
    if fn is None:
        return functools.partial(_tool, annotations=annotations)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        result = await fn(*args, **kwargs)
        return json.dumps(_prune(result), ensure_ascii=False, separators=(",", ":"))
    return mcp.tool(description=inspect.cleandoc(fn.__doc__ or ""), annotations=annotations,
                    structured_output=False)(wrapper)


def _content_tool(fn):
    """Register `fn` as is, for a tool that returns content blocks rather than a
    dict; its docstring is dedented like ``_tool``'s."""
    return mcp.tool(description=inspect.cleandoc(fn.__doc__ or ""), annotations=ONLINE,
                    structured_output=False)(fn)


def _rows(rows: int, page: int = 0) -> int:
    """Validate a page size rather than quietly clamping 0 up to 1, and a page
    index, which Kleinanzeigen would answer for -1 as if it were 0."""
    rows = int(rows)
    if rows < 1:
        raise ToolError(f"rows must be at least 1 (got {rows}).")
    if page < 0:
        raise ToolError(f"page must be 0 or more (got {page}).")
    return min(rows, MAX_ROWS)


def _check_range(name: str, low, high) -> None:
    """Reject an inverted range instead of letting Kleinanzeigen drop the filter
    and quietly answer with everything."""
    if low is not None and high is not None and low > high:
        raise ToolError(
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


_CONTENT_TYPE_FORMAT = {
    "image/webp": "webp",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
}


@_tool
@api.tool_errors("search")
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
    ad_type: Optional[api.AdType] = None,
    poster_type: Optional[api.PosterType] = None,
    sort: api.Sort = "RECOMMENDED",
    title_only: bool = False,
    require: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    rows: int = 5,
    page: int = 0,
    picture_required: bool = False,
    buy_now_only: bool = False,
    shippable: bool = False,
    include_top_ads: bool = False,
) -> dict:
    """Search Kleinanzeigen listings. Needs a ``query``, a
    ``category`` or both.

    A bare query matches the whole ad text and drags in accessories, bundles
    and spare parts, so scope to a category when you can, and use
    ``attributes`` over extra words.

    Put the model in ``query`` and every spec in ``require``. Sellers write
    "128GB", "128 GB" or leave it out of the title, so ``query="iPhone 13",
    require=["128gb"]`` finds what ``query="iPhone 13 128 GB"`` misses.

    These filters run here, paging on until ``rows`` matches turn up or 250 ads
    were scanned (``scanned``):
    - ``title_only``: every query word must be in the title.
    - ``require``: every term must be in the title or description; a number
      with its unit matches however it is spelled.
    - ``exclude``: drop titles carrying any of these words, e.g. ``["pro",
      "max"]``. A word also hits the tail of a compound ("kabel" in
      "Ladekabel"), never a prefix ("pro" spares "Prozessor"). Don't exclude
      ordinary nouns like "akku" or "display", real listings use them too.

    A missing ``price_amount`` is normal: ``price_type`` then says "FREE" (zu
    verschenken) or "PLEASE_CONTACT" (VB); with a price, PLEASE_CONTACT means
    negotiable.

    Args:
        query: Search words.
        category: Category id or name; includes its subcategories.
        attributes: Category filters, e.g. ``{"pc_zubehoer_software.art":
            "grafikkarten"}``; a ``multi_select`` one also takes a list. Keys
            and values come from ``get_category_filters``.
        location_id: From ``search_locations``.
        zip_code: A German postcode, instead of ``location_id``.
        distance_km: Radius around the location or postcode.
        min_price / max_price: Price bounds.
        ad_type: "OFFERED" (Ich biete) or "WANTED" (Ich suche).
        poster_type: "PRIVATE" or "COMMERCIAL".
        sort: Default "RECOMMENDED"; "DISTANCE_ASCENDING" needs a location.
        picture_required / buy_now_only / shippable: Only ads with photos /
            "Direkt kaufen" / shipping.
        include_top_ads: Also return paid "TOP" placements (``is_top_ad``).
            They are pinned above any sort order and mostly repair shops and
            buyers, so they are left out by default.
    """
    if not query and category is None:
        raise ToolError("Provide 'query' and/or 'category'.")
    _check_range("price", min_price, max_price)
    rows = _rows(rows, page)

    wanted = matching.tokens(query) if (title_only and query) else set()
    required = [matching.term_forms(t) for t in (require or []) if str(t).strip()]
    excluded = [matching.term_forms(t) for t in (exclude or []) if str(t).strip()]
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
        params.append(("categoryId", str(categories.resolve(category))))
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
        tokens = matching.tokens(hit["title"])
        if wanted and not wanted <= tokens:
            return False
        if any(matching.has_term(tokens, forms) for forms in excluded):
            return False
        if required:
            # a spec is written wherever the seller felt like it, so look at the
            # whole ad rather than demanding it in the title
            text = tokens | matching.tokens(hit["description"])
            if not all(matching.has_term(text, forms) for forms in required):
                return False
        return True

    # A client-side filter has to page deeper than the caller asked for, so it
    # pulls full pages and keeps going until `rows` survivors are found.
    page_size = MAX_ROWS if post_filtered else rows
    results: list = []
    cursor, total, scanned = page, None, 0
    while True:
        page_params = params + [("page", str(cursor)), ("size", str(page_size))]
        payload = api.collection(await api.get("ads.json", params=page_params), "ads")
        ads = payload.get("ad", [])
        total = (payload.get("paging") or {}).get("numFound", total)
        for ad in ads:
            scanned += 1
            hit = summaries.summarize_ad_hit(ad)
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


@_tool
@api.tool_errors("ad")
async def get_ad_detail(ad_id: int) -> dict:
    """One ad in full: the complete description, attributes by their
    label ("Zustand", "Versand", ...), category, location, shipping options,
    seller and ``image_count``.

    Args:
        ad_id: The ad id from a search.
    """
    data = await api.get(f"ads/{ad_id}.json")
    return summaries.summarize_ad_detail(api.collection(data, "ad"))


@_content_tool
@api.tool_errors("ad")
async def get_ad_images(ad_id: int, max_images: int = 4) -> list:
    """The ad's photos as images you can look at, up to
    ``max_images`` (at most 10). Use them whenever the answer depends on what
    the item looks like: condition, damage, completeness, or details only a
    picture shows, such as a label or a screen.

    Args:
        ad_id: The ad id from a search.
        max_images: How many photos to fetch. Default 4.
    """
    max_images = max(1, min(int(max_images), 10))
    data = await api.get(f"ads/{ad_id}.json")

    ad = api.collection(data, "ad")
    urls = summaries.image_urls(ad.get("pictures"))[:max_images]
    if not urls:
        return [f"No images found for ad {ad_id}."]

    async def fetch(url: str):
        try:
            response = await api.client.get(url, headers={"user-agent": api.KA_CLIENT})
            response.raise_for_status()
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            return Image(data=response.content, format=_CONTENT_TYPE_FORMAT.get(ctype, "jpeg"))
        except Exception as exc:  # a single broken image shouldn't fail the tool
            logger.warning("image download failed (%s): %s", url, exc)
            return None

    fetched = await asyncio.gather(*(fetch(u) for u in urls))
    pictures = [img for img in fetched if img is not None]
    title = html.unescape(api.unwrap(ad.get("title")) or "") or f"ad {ad_id}"
    return [f'{len(pictures)} image(s) for "{title}" (ad {ad_id}):', *pictures]


@_tool
@api.tool_errors("seller")
async def get_seller_info(seller_id: int) -> dict:
    """Who sells an ad: name, private or commercial, member
    since, ads run, followers, reply speed and reputation score. For a trust
    check the ad itself does not answer.

    The profile half is guarded by IP-range anti-fraud and can fail from VPN or
    datacenter addresses; ``partial`` then says so and the reputation still
    comes back.

    Args:
        seller_id: ``seller_id`` from a search hit or ad detail.
    """
    # two independent services -- report whichever half answers instead of
    # losing a usable trust check to the other one's failure
    async def half(coro, name):
        try:
            return await coro, None
        except httpx.HTTPStatusError as exc:
            return {}, f"{name}: {api.upstream_message(exc.response.status_code, name, exc.response.text)}"
        except httpx.HTTPError as exc:
            return {}, f"{name}: could not reach Kleinanzeigen ({type(exc).__name__})"

    profile, profile_error = await half(
        api.get(f"users/public/{seller_id}/profile.json"), "profile")
    reputation, reputation_error = await half(
        api.get_gateway(f"user-reputation-service/public/users/{seller_id}/reputation-summary"),
        "reputation")
    if profile_error and reputation_error:
        raise ToolError(f"{profile_error}; {reputation_error}")
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


@_tool
@api.tool_errors("location")
async def search_locations(query: str) -> list[dict]:
    """Find location ids for the ``location_id`` filter of
    ``search_kleinanzeigen`` by name prefix: states, cities and districts. For
    a postcode, pass ``zip_code`` to the search instead.

    Args:
        query: Start of the name, e.g. "berl".
    """
    data = await api.get("locations.json", params={"depth": 1, "q": query})
    payload = api.collection(data, "locations")
    locations = payload.get("location", [])
    out = []
    for loc in locations:
        regions = (loc.get("regions") or {}).get("region") or []
        out.append({
            "id": loc.get("id"),
            "name": api.unwrap(loc.get("localized-name")),
            "region": api.unwrap(regions[0].get("localized-name")) if regions else None,
            "radius_km": api.unwrap(loc.get("radius")),
        })
    return out


@_tool
@api.tool_errors("category filter")
async def get_category_filters(category: Union[int, str]) -> list[dict]:
    """The attribute filters of a category, for the
    ``attributes`` of ``search_kleinanzeigen``: ``[{key, label, type,
    multi_select, values: [{value, label}]}]``. ``values`` is empty for
    free-form attributes.

    Args:
        category: Category id or name.
    """
    data = await api.get(f"ads/search-metadata/{categories.resolve(category)}.json")
    payload = api.collection(data, "ads-search-options")
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


@_tool(annotations=LOCAL)
async def list_categories(query: Optional[str] = None, limit: int = 40) -> dict:
    """Find category ids for ``search_kleinanzeigen`` and
    ``get_category_filters``. Returns ``{count, categories: [{id, title,
    path}]}``.

    Args:
        query: Part of the category path, e.g. "pc-zubehör". Omit to list
            everything up to ``limit``.
        limit: Default 40.
    """
    flat: list = []
    categories.walk(categories.CATEGORIES, [], flat)
    q = matching.norm(query) if query else None
    rows = [{"id": node.get("id"), "title": node.get("title"), "path": path}
            for node, path in flat if not q or q in matching.norm(path)]
    return {"count": len(rows), "categories": rows[:limit]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kleinanzeigen MCP server")
    parser.add_argument("--stdio", action="store_true",
                        help="speak MCP over stdin/stdout instead of serving HTTP")
    if parser.parse_args().stdio:
        # stdout carries the protocol; the log already goes to stderr
        mcp.run("stdio")
    else:
        url = f"http://{HOST}:{PORT}{MCP_PATH}"
        logger.info("Starting kleinanzeigen-mcp server on %s", url)
        mcp.run("streamable-http", host=HOST, port=PORT, streamable_http_path=MCP_PATH)

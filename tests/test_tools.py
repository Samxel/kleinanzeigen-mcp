"""The tools end to end through an MCP client, against a fake Kleinanzeigen."""

import httpx
import pytest

from samples import ad, attribute, detail, enum_filter, locations, profile, reputation, search, search_options

pytestmark = pytest.mark.anyio

API = "api.kleinanzeigen.de"
SEARCH = "/api/ads.json"


def paged(ads):
    """A search endpoint that serves `ads` by the request's page and size."""
    def respond(request):
        page, size = int(request.url.params["page"]), int(request.url.params["size"])
        return search(ads[page * size:(page + 1) * size], total=len(ads))
    return respond


async def test_search_summarizes_hits(ka, call):
    ka.on(API, SEARCH, search([ad(1, "iPhone 13 128GB", price=350)], total=4616))
    result = await call("search_kleinanzeigen", query="iPhone 13")
    hit = result["results"][0]
    assert (hit["id"], hit["title"], hit["price_amount"], hit["zip_code"]) == ("1", "iPhone 13 128GB", 350, "85664")
    assert (result["total"], result["has_more"], result["next_page"]) == (4616, True, 1)
    sent = ka.sent(SEARCH)[0].url.params
    assert (sent["q"], sent["size"], sent["page"]) == ("iPhone 13", "5", "0")


async def test_filters_page_on_until_enough_matches(ka, call):
    ads = ([ad(i, "iPhone 13 Pro 128GB") for i in range(40)]
           + [ad(100 + i, "iPhone 13", description="128 GB, Akku 90%") for i in range(3)])
    ka.on(API, SEARCH, paged(ads))
    result = await call("search_kleinanzeigen", query="iPhone 13", require=["128gb"], exclude=["pro"],
                        title_only=True, rows=3)
    assert [r["id"] for r in result["results"]] == ["100", "101", "102"]
    assert result["scanned"] == 43


async def test_search_sends_category_attributes_and_ranges(ka, call):
    ka.on(API, SEARCH, search([]))
    await call("search_kleinanzeigen", category="PC-Zubehör & Software", min_price=100, max_price=400,
               attributes={"pc_zubehoer_software.art": ["grafikkarten", "mainboards"]})
    sent = ka.sent(SEARCH)[0].url.params
    assert (sent["categoryId"], sent["minPrice"], sent["maxPrice"]) == ("225", "100.0", "400.0")
    assert sent["attr[pc_zubehoer_software.art]"] == "grafikkarten,mainboards"


async def test_detail_reads_the_whole_ad(ka, call):
    ka.on(API, "/api/ads/7.json", detail(7, "iPhone 13", description="Top<br />Zustand", attributes=[
        attribute("handy_telekom.condition", "Zustand", "gut", "Gut")]))
    result = await call("get_ad_detail", ad_id=7)
    assert result["description"] == "Top\nZustand"
    assert result["shipping_options"] == ["DHL_001"]


async def test_images_come_back_as_image_content(ka):
    from mcp import Client
    import main
    ka.on(API, "/api/ads/7.json", detail(7, "iPhone 13", images=3))
    ka.on("img.kleinanzeigen.de", "/", httpx.Response(200, content=b"\xff\xd8jpeg",
                                                      headers={"content-type": "image/jpeg"}))
    async with Client(main.mcp) as client:
        result = await client.call_tool("get_ad_images", {"ad_id": 7, "max_images": 2})
    assert [b.type for b in result.content] == ["text", "image", "image"]


async def test_seller_info_joins_profile_and_reputation(ka, call):
    ka.on(API, "/api/users/public/22075716/profile.json", profile())
    ka.on("gateway.kleinanzeigen.de", "/user-reputation-service/", reputation())
    result = await call("get_seller_info", seller_id=22075716)
    assert (result["member_since"], result["total_ads"], result["reputation_score"]) == ("2015-03-01", 40, 4.9)


async def test_a_blocked_profile_still_returns_the_reputation(ka, call):
    ka.on(API, "/api/users/public/", httpx.Response(403, text="Ihre IP wurde gesperrt"))
    ka.on("gateway.kleinanzeigen.de", "/user-reputation-service/", reputation())
    result = await call("get_seller_info", seller_id=22075716)
    assert result["reputation_score"] == 4.9
    assert "blocked this IP range" in result["partial"]


async def test_location_and_filter_lookups(ka, call):
    ka.on(API, "/api/locations.json", locations("Berlin", "Pankow (Berlin)"))
    ka.on(API, "/api/ads/search-metadata/225.json", search_options(
        enum_filter("pc_zubehoer_software.art", "Art", ("grafikkarten", "Grafikkarten"))))
    berlin = await call("search_locations", query="berl")
    assert [loc["name"] for loc in berlin] == ["Berlin", "Pankow (Berlin)"]
    filters = await call("get_category_filters", category=225)
    assert filters["key"] == "pc_zubehoer_software.art" and filters["multi_select"] is True


async def test_category_list(call):
    result = await call("list_categories", query="pc-zubehör")
    assert [c["id"] for c in result["categories"]] == [225]


async def test_paid_top_ads_stay_out_unless_asked_for(ka, call):
    ka.on(API, SEARCH, search([]))
    await call("search_kleinanzeigen", query="iPhone 13")
    await call("search_kleinanzeigen", query="iPhone 13", include_top_ads=True)
    assert [r.url.params["includeTopAds"] for r in ka.sent(SEARCH)] == ["false", "true"]

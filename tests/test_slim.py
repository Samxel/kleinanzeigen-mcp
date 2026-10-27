"""Hits and details carry what a model reads, not what it has to skip."""

import pytest

from samples import ad, attribute, detail, locations, search

pytestmark = pytest.mark.anyio

API = "api.kleinanzeigen.de"


async def test_a_plain_hit_leaves_out_the_defaults(ka, call):
    ka.on(API, "/api/ads.json", search([ad(1, "iPhone 13", shipping=())]))
    [hit] = (await call("search_kleinanzeigen", query="iPhone 13"))["results"]
    assert hit["url"] == "https://www.kleinanzeigen.de/s-anzeige/1"
    assert hit["start_date"] == "2026-10-27T23:54" and hit["ships"] is False
    assert not {"price_currency", "price_type", "is_top_ad", "image_url"} & set(hit)


async def test_a_negotiable_top_ad_says_so(ka, call):
    ka.on(API, "/api/ads.json", search([ad(1, "iPhone 13", price_type="PLEASE_CONTACT", top=True)]))
    [hit] = (await call("search_kleinanzeigen", query="iPhone 13", include_top_ads=True))["results"]
    assert (hit["price_type"], hit["is_top_ad"], hit["ships"]) == ("PLEASE_CONTACT", True, True)


async def test_detail_names_attributes_by_their_label(ka, call):
    ka.on(API, "/api/ads/7.json", detail(7, "iPhone 13", images=5, attributes=[
        attribute("handy_telekom.condition", "Zustand", "gut", "Gut"),
        attribute("handy_telekom.storage", "Speicher", "128", "128 GB")]))
    result = await call("get_ad_detail", ad_id=7)
    assert result["attributes"] == {"Zustand": "Gut", "Speicher": "128 GB"}
    assert result["image_count"] == 5 and "images" not in result
    assert not {"latitude", "longitude", "ad_type", "ad_status", "buy_now"} & set(result)


async def test_locations_carry_no_coordinates(ka, call):
    ka.on(API, "/api/locations.json", locations("Berlin"))
    [berlin] = await call("search_locations", query="berl")
    assert set(berlin) == {"id", "name", "region", "radius_km"}

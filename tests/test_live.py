"""Smoke tests against the real API. The app API and its credential are
reverse-engineered, so these are what notices Kleinanzeigen changing them; they
only run with KLEINANZEIGEN_LIVE=1 (the scheduled CI job sets it)."""

import os

import httpx
import pytest

import main

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("KLEINANZEIGEN_LIVE"),
                       reason="set KLEINANZEIGEN_LIVE=1 to hit the real API"),
]


@pytest.fixture(autouse=True)
async def fresh_client(monkeypatch):
    """main.client binds to the first event loop it runs on, and every test
    gets its own loop."""
    client = httpx.AsyncClient(http2=True)
    monkeypatch.setattr(main, "client", client)
    yield
    await client.aclose()


async def test_search_and_detail(call):
    result = await call("search_kleinanzeigen", query="iPhone 13", category=173, rows=3)
    assert result["total"] and result["results"]
    detail = await call("get_ad_detail", ad_id=int(result["results"][0]["id"]))
    assert detail["title"] and detail["description"]


async def test_filtered_search_pages_on(call):
    result = await call("search_kleinanzeigen", query="iPhone 13", category=173, require=["128gb"],
                        exclude=["pro", "max", "mini"], title_only=True, rows=3)
    assert len(result["results"]) == 3


async def test_seller_reputation(call):
    hit = (await call("search_kleinanzeigen", query="fahrrad", rows=1))["results"][0]
    seller = await call("get_seller_info", seller_id=int(hit["seller_id"]))
    # the profile half is IP-guarded and 403s from datacenter ranges such as
    # CI runners; the reputation half has to answer either way
    assert "reputation_score" in seller


async def test_lookups(call):
    assert await call("search_locations", query="berl")
    assert await call("get_category_filters", category=225)

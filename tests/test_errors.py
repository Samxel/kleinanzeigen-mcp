"""Failures reach the model as is_error results that say what went wrong."""

import re
from pathlib import Path

import httpx
import pytest

from conftest import ToolFailed

pytestmark = pytest.mark.anyio

API = "api.kleinanzeigen.de"
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("tool, args, message", [
    ("search_kleinanzeigen", {}, "Provide 'query'"),
    ("search_kleinanzeigen", {"query": "x", "rows": 0}, "rows must be at least 1"),
    ("search_kleinanzeigen", {"query": "x", "page": -1}, "page must be 0 or more"),
    ("search_kleinanzeigen", {"query": "x", "min_price": 500, "max_price": 10}, "min_price .* is above max_price"),
    ("search_kleinanzeigen", {"query": "x", "category": "Grafikkarten"}, "Unknown category"),
    ("get_category_filters", {"category": "Gibtsnicht"}, "Unknown category"),
])
async def test_bad_arguments_explain_themselves(ka, call, tool, args, message):
    with pytest.raises(ToolFailed, match=message):
        await call(tool, **args)


async def test_upstream_failures_are_phrased(ka, call):
    ka.on(API, "/api/ads/1.json", httpx.Response(404))
    with pytest.raises(ToolFailed, match="no ad found"):
        await call("get_ad_detail", ad_id=1)
    with pytest.raises(ToolFailed, match="no ad found"):
        await call("get_ad_images", ad_id=1)
    ka.on(API, "/api/ads.json", httpx.Response(503))
    with pytest.raises(ToolFailed, match=r"failed on the search request \(HTTP 503\)"):
        await call("search_kleinanzeigen", query="x")


async def test_a_seller_with_both_halves_failing_is_an_error(ka, call):
    ka.on(API, "/api/users/public/", httpx.Response(403, text="Ihre IP wurde gesperrt"))
    ka.on("gateway.kleinanzeigen.de", "/", httpx.Response(500))
    with pytest.raises(ToolFailed, match="profile: .*blocked this IP range.*; reputation: "):
        await call("get_seller_info", seller_id=1)


async def test_a_refused_credential_names_the_file_that_holds_it(ka, call):
    ka.on(API, "/api/ads/1.json", httpx.Response(401))
    with pytest.raises(ToolFailed, match="client credential") as failed:
        await call("get_ad_detail", ad_id=1)
    path = re.search(r"credential in (\S+) \(KA_BASIC_AUTH\)", str(failed.value)).group(1)
    assert "KA_BASIC_AUTH = " in (ROOT / path).read_text()

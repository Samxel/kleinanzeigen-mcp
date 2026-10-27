"""Results go out as compact JSON, without null fields, and only once."""

import pytest
from mcp import Client

import main
from samples import ad, locations, search

pytestmark = pytest.mark.anyio


def test_prune_drops_null_fields_at_every_depth():
    value = {"a": None, "b": [{"c": None, "d": 1}, None], "e": {"f": None}, "g": 0, "h": ""}
    assert main._prune(value) == {"b": [{"d": 1}, None], "e": {}, "g": 0, "h": ""}


async def test_results_are_compact_single_text_blocks(ka):
    ka.on("api.kleinanzeigen.de", "/api/ads.json", search([ad(1, "Kaffeemaschine für Café")]))
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
        result = await client.call_tool("search_kleinanzeigen", {"query": "kaffeemaschine"})
    assert all(tool.output_schema is None for tool in tools)
    assert result.structured_content is None
    [block] = result.content
    assert "\n" not in block.text and '": ' not in block.text
    assert "Café" in block.text and "null" not in block.text


async def test_a_list_result_is_one_block(ka):
    ka.on("api.kleinanzeigen.de", "/api/locations.json", locations("Berlin", "Pankow (Berlin)"))
    async with Client(main.mcp) as client:
        result = await client.call_tool("search_locations", {"query": "berl"})
    [block] = result.content
    assert block.text.startswith("[{") and result.structured_content is None

"""What every client loads up front: the server instructions and tool listing."""

import inspect
import json

import pytest
from mcp import Client

from kleinanzeigen import server as main

pytestmark = pytest.mark.anyio


async def test_instructions_reach_the_client_and_name_every_tool():
    async with Client(main.mcp) as client:
        instructions = client.instructions
        tools = (await client.list_tools()).tools
    assert instructions == main.INSTRUCTIONS
    for tool in tools:
        assert tool.name in instructions, tool.name


async def test_descriptions_are_dedented_and_the_listing_stays_small():
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        assert tool.description == inspect.cleandoc(tool.description), tool.name
        assert not tool.description.startswith(" ")
    listing = json.dumps([tool.model_dump(exclude_none=True) for tool in tools], ensure_ascii=False)
    # ~8.3k before titles and null branches left the schemas
    assert len(listing) < 7600


async def test_schemas_carry_no_titles_or_null_branches():
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        text = json.dumps(tool.input_schema)
        assert '"title"' not in text and '"null"' not in text, tool.name

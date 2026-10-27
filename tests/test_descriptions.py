"""What every client loads up front: the server instructions and tool listing."""

import inspect
import json

import pytest
from mcp import Client

import main

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
    assert len(listing) < 9000

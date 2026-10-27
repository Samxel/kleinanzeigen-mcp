"""Shared fixtures: an in-process MCP client and a fake Kleinanzeigen behind
the server's HTTP client, so the tools are exercised end to end without the
network."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from mcp import Client  # noqa: E402
from kleinanzeigen import api  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeKleinanzeigen:
    """Answers requests by the first route whose (host, path prefix) matches,
    with a JSON body, an ``httpx.Response`` or a callable taking the request;
    every request is recorded."""

    def __init__(self):
        self.routes = []
        self.requests = []

    def on(self, host, path, answer):
        self.routes.insert(0, (host, path, answer))
        return self

    def handle(self, request):
        self.requests.append(request)
        for host, path, answer in self.routes:
            if request.url.host == host and request.url.path.startswith(path):
                answer = answer(request) if callable(answer) else answer
                return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)
        return httpx.Response(404, json={"error": f"no fake for {request.url}"})

    def sent(self, path):
        return [r for r in self.requests if r.url.path.startswith(path)]


@pytest.fixture
def ka(monkeypatch):
    fake = FakeKleinanzeigen()
    monkeypatch.setattr(api, "client", httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)))

    async def no_sleep(_):
        pass

    monkeypatch.setattr(api.asyncio, "sleep", no_sleep)
    return fake


class ToolFailed(Exception):
    """The call came back with ``is_error`` set; the message is its text."""


async def call_tool(tool, **args):
    """Call a tool through a real MCP client and decode its JSON text. A tool
    returning a list may come back as one text block per item."""
    async with Client(main.mcp) as client:
        result = await client.call_tool(tool, args)
    texts = [block.text for block in result.content if block.type == "text"]
    if result.is_error:
        raise ToolFailed("".join(texts))
    if len(texts) == 1:
        return json.loads(texts[0])
    return [json.loads(text) for text in texts]


@pytest.fixture
def call():
    return call_tool

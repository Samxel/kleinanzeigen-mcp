#!/usr/bin/env python3
"""Fetch Kleinanzeigen's category tree and flatten it into ``data/categories.json``.

``api/categories.json`` wraps everything in JAXB envelopes and a single
"Alle Kategorien" pseudo-root; this strips both down to the same
``{title, id, childs}`` shape willhaben-mcp and geizhals-mcp ship.
"""

import gzip
import json
import urllib.request
from pathlib import Path

CATEGORIES_URL = "https://api.kleinanzeigen.de/api/categories.json"
KA_BASIC_AUTH = "Basic YW5kcm9pZDpUYVI2MHBFdHRZ"
KA_CLIENT = "Kleinanzeigen/2026.37.1 (Android 14; google sdk_gphone64_x86_64)"


def fetch_raw() -> dict:
    request = urllib.request.Request(CATEGORIES_URL, headers={
        "authorization": KA_BASIC_AUTH,
        "user-agent": KA_CLIENT,
        "accept-encoding": "gzip",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body.decode())


def flatten(node: dict) -> dict:
    return {
        "title": (node.get("localized-name") or {}).get("value"),
        "id": int(node["id"]) if "id" in node else None,
        "childs": [flatten(c) for c in node.get("category", [])],
    }


def main() -> None:
    raw = fetch_raw()
    wrap = next(v for k, v in raw.items() if k.endswith("}categories"))
    root = wrap["value"]["category"][0]  # the "Alle Kategorien" pseudo-root
    tree = [flatten(c) for c in root.get("category", [])]

    out = Path(__file__).resolve().parent.parent / "data" / "categories.json"
    out.write_text(json.dumps(tree, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(tree)} top-level categories)")


if __name__ == "__main__":
    main()

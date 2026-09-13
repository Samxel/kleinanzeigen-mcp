#!/usr/bin/env python3
"""Fetch the live Kleinanzeigen platform counts and write ``coverage.json``.

The README's shields.io badges read that file, and a scheduled GitHub Action
runs this script to keep the numbers fresh. Kleinanzeigen has no JSON stats
API (and the search API's own totals cap out at 10000), but its "Über uns"
page renders a handful of headline numbers server-side, so we parse those
``<h3>value</h3><p>label</p>`` pairs out of the HTML.
"""

import datetime
import gzip
import html
import json
import re
import urllib.request
from pathlib import Path

ABOUT_URL = "https://themen.kleinanzeigen.de/ueber-uns/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# stat label text (matched case-insensitively as a substring) -> coverage key
LABELS = {
    "gleichzeitig verf": "listings",
    "besucherinnen und besucher im monat": "visitors",
    "gewerbliche nutzerinnen": "commercial_users",
}


def fetch_counts() -> dict[str, int]:
    request = urllib.request.Request(ABOUT_URL, headers={
        "User-Agent": UA,
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    page = body.decode("utf-8", "replace")

    pairs = re.findall(r"<h3>([^<]+)</h3><p>([^<]+)</p>", page)
    counts: dict[str, int] = {}
    for value, label in pairs:
        value = html.unescape(value).strip()
        match = re.search(r"([\d.]+)\s*(Mio\.)?", value)
        if not match or not match.group(1):
            continue
        number = int(match.group(1).replace(".", ""))
        if match.group(2):
            number *= 1_000_000
        label = html.unescape(label).strip().lower()
        for needle, key in LABELS.items():
            if needle in label:
                counts[key] = number
    missing = set(LABELS.values()) - set(counts)
    if missing:
        raise SystemExit(f"could not parse {sorted(missing)} from {ABOUT_URL} "
                         "(page layout changed or the request was blocked)")
    return counts


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def main() -> None:
    counts = fetch_counts()

    coverage = {"updated": datetime.date.today().isoformat()}
    for key in ("listings", "visitors", "commercial_users"):
        coverage[key] = human(counts[key])
        coverage[f"{key}_count"] = counts[key]

    out = Path(__file__).resolve().parent.parent / "coverage.json"
    out.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()

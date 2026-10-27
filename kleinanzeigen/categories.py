"""The category tree (shipped, built by scripts/build_categories.py) and
resolving a category name the way a model writes it."""

import json
import logging
from pathlib import Path
from typing import Union

from mcp.server.mcpserver.exceptions import ToolError

from . import matching


def _load_categories() -> list[dict]:
    path = Path(__file__).parent.parent / "data" / "categories.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.getLogger(__name__).warning("categories.json not found -- list_categories disabled")
        return []


CATEGORIES = _load_categories()


def walk(nodes, trail, out):
    for nd in nodes:
        label = nd.get("title") or ""
        path = trail + [label]
        out.append((nd, " / ".join(path)))
        walk(nd.get("childs", []), path, out)


def resolve(category: Union[int, str]) -> int:
    """Resolve a category given as id or name to its numeric id, so the caller
    can pass "PC-Zubehör & Software" instead of looking up 225 first."""
    text = str(category).strip()
    if text.isdigit():
        return int(text)
    flat: list = []
    walk(CATEGORIES, [], flat)
    wanted = matching.norm(text)

    exact = [(n, p) for n, p in flat if matching.norm(n.get("title") or "") == wanted]
    if exact:
        # a name can repeat deeper in the tree ("Elektronik" is also a
        # Dienstleistungen child); the shallower one is what was meant
        depth = min(p.count("/") for _, p in exact)
        top = [(n, p) for n, p in exact if p.count("/") == depth]
        if len(top) == 1:
            return top[0][0]["id"]
        paths = ", ".join(p for _, p in top)
        raise ToolError(f"Category name {text!r} is ambiguous ({paths}). Pass the id instead.")

    partial = [(n, p) for n, p in flat if wanted in matching.norm(p)]
    if not partial:
        # words in any order, and the tree's word with or without an ending
        # ("Handys" finds "Handy & Telefon", "Software PC-Zubehör" the reverse)
        words = _category_words(text)
        partial = [(n, p) for n, p in flat if _word_overlap(words, matching.tokens(p)) == len(words)]
    if len(partial) == 1:
        return partial[0][0]["id"]
    if partial:
        matches = ", ".join(f"{n['id']} ({p})" for n, p in partial[:8])
        raise ToolError(f"Category {text!r} is ambiguous. Closest matches: {matches}. Pass the id instead.")
    raise ToolError(f"Unknown category {text!r}.{_closest_categories(text, flat)} Use list_categories "
                    f"to find one -- and note the tree stops fairly high up, so a finer cut like "
                    f"'Grafikkarten' is an attribute value (get_category_filters), not a category.")


# What a model reaches for first, in the tree's own words
_CATEGORY_ALIASES = {"smartphone": "handy", "smartphones": "handy", "fernseher": "tv"}


def _category_words(text: str) -> set:
    return {_CATEGORY_ALIASES.get(word, word) for word in matching.tokens(text)}


def _word_overlap(wanted: set, words: set, *, max_ending: int = 3) -> int:
    """How many of the wanted words a category's words cover. A word counts
    when it is the same, or when one is the other plus an ending of up to
    `max_ending` letters ("handys" and "handy", "fahrrader" and "fahrrad"); that
    needs four letters, so "pc" does not cover "pcs"."""
    def covers(want: str) -> bool:
        return any(want == word or (min(len(want), len(word)) >= 4
                                    and abs(len(want) - len(word)) <= max_ending
                                    and (want.startswith(word) or word.startswith(want)))
                   for word in words)
    return sum(covers(want) for want in wanted)


def _closest_categories(text: str, flat: list, limit: int = 5) -> str:
    """" Closest: <id> (<path>), ..." for the categories sharing the most words
    with `text`, or "" when none shares any. A compound counts here too, so
    "Gartenmöbel" points at "Haus & Garten"."""
    words = _category_words(text)
    scored = sorted(((_word_overlap(words, matching.tokens(p), max_ending=99), len(p), n["id"], p) for n, p in flat),
                    key=lambda row: (-row[0], row[1]))
    best = [f"{cid} ({path})" for score, _, cid, path in scored[:limit] if score]
    return f" Closest: {', '.join(best)}." if best else ""

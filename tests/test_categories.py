"""Category names resolve the way a model writes them, and a miss gets hints."""

import pytest

import main
from conftest import ToolFailed

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("name, category", [
    ("Handys", 173),                 # the tree says "Handy & Telefon"
    ("Smartphones", 173),            # what the ad itself calls it
    ("Software PC-Zubehör", 225),    # words in the other order
    ("Laptop", 278),                 # "Laptops & Notebooks"
    ("Fahrräder", 217),
])
def test_a_name_as_a_model_writes_it_resolves(name, category):
    assert main._resolve_category(name) == category


def test_a_compound_is_no_ending():
    with pytest.raises(main.ToolError, match=r"Unknown category 'Gartenmöbel'. Closest: 80 \(Haus & Garten\)"):
        main._resolve_category("Gartenmöbel")


async def test_an_ambiguous_name_lists_ids(call):
    with pytest.raises(ToolFailed, match=r"ambiguous. Closest matches: 241 \(Auto, Rad & Boot / Weiteres"):
        await call("search_kleinanzeigen", query="x", category="Weiteres")

"""The badge script reads the "Über uns" page's headline numbers."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_coverage.py"
spec = importlib.util.spec_from_file_location("update_coverage", SCRIPT)
update_coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_coverage)

ABOUT = """
<div><h3>Über 40 Mio.</h3><p>gleichzeitig verfügbare Anzeigen</p></div>
<div><h3>33 Mio.</h3><p>Besucherinnen und Besucher im Monat</p></div>
<div><h3>250.000</h3><p>gewerbliche Nutzerinnen und Nutzer</p></div>
"""


def test_parse_counts_reads_all_three_numbers():
    assert update_coverage.parse_counts(ABOUT) == {
        "listings": 40_000_000, "visitors": 33_000_000, "commercial_users": 250_000}


def test_parse_counts_fails_loudly_on_a_changed_page():
    with pytest.raises(SystemExit, match="could not parse"):
        update_coverage.parse_counts("<html>Zugriff verweigert</html>")


def test_human_shortens_the_counts():
    assert [update_coverage.human(n) for n in (40_000_000, 250_000, 999)] == ["40.0M", "250k", "999"]

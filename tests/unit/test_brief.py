"""The recurring brief's renderer (wizard_connectors/brief.py): numbers, the "what moved" sentences, the charts and the
email. It also runs on Metronome inside the generated script, so it must stay standard library only."""
from __future__ import annotations

import ast
import datetime as dt
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest

from wizard_connectors import brief

MARKETS = {"columns": ["market", "units", "units_prev"],
           "rows": [["UAE", 18420, 16980], ["KSA", 14960, 14310], ["Kuwait", 5310, 5620], ["Qatar", 4180, 3720]]}
WEEKS = {"columns": ["week", "units"],
         "rows": [[f"W{36 + i}", v] for i, v in enumerate([41200, 42950, 44100, 43300, 46050, 44900, 45800, 48210])]}
NUMBERS = {"columns": ["units", "units_prev", "revenue", "revenue_prev"], "rows": [[48210, 45800, 61400000, 59000000]]}
SECTION = {"kind": "chart", "chart": "bar", "title": "Units by market", "x": "market", "series": ["units", "units_prev"],
           "change": True, "columns": [{"key": "units", "label": "Week 43"}, {"key": "units_prev", "label": "Week 42"}]}


def say(rule: dict, result=MARKETS, section=SECTION) -> str | None:
    return brief.sentence(section, rule, brief.records(result))


def test_numbers_are_formatted_for_reading():
    assert brief.fmt(48210) == "48,210" and brief.fmt(Decimal("1234.5")) == "1,235" and brief.fmt("7") == "7"
    assert brief.fmt(61_400_000, {"prefix": "AED ", "compact": True}) == "AED 61.4M"
    assert brief.fmt(1273.59, {"prefix": "AED ", "decimals": 0}) == "AED 1,274"
    assert brief.fmt(12.25) == "12.3" and brief.fmt(1234.5, {"decimals": 1}) == "1,234.5"
    assert brief.fmt(-0.004) == "0.00" and brief.fmt(-12.5) == "−12.5" and brief.fmt(0.25, {"suffix": "%"}) == "0.25%"
    assert brief.fmt(None) == "–" and brief.fmt("EG") == "EG" and brief.fmt(dt.date(2026, 10, 19)) == "2026-10-19"
    assert brief.change(48210, 45800) == pytest.approx(5.262, abs=0.001) and brief.change(5, 0) is None
    assert brief.fmt_change(5.26) == "+5.3%" and brief.fmt_change(-5.52) == "−5.5%" and brief.fmt_change(0.01) == "0.0%"
    assert brief.tone(3, "up") == brief.UP and brief.tone(3, "down") == brief.DOWN and brief.tone(None) == brief.GREY


def test_each_rule_says_what_moved_or_nothing():
    assert say({"rule": "change", "value": "units", "previous": "units_prev", "noun": "sell-out"},
               NUMBERS, {"kind": "numbers"}) == "Sell-out rose 5.3% to 48,210, from 45,800."
    assert say({"rule": "largest", "label": "market", "value": "units", "noun": "units"}) == "UAE had the highest units: 18,420."
    assert say({"rule": "smallest", "label": "market", "value": "units"}) == "Qatar had the lowest week 43: 4,180."
    assert say({"rule": "biggest_rise", "label": "market", "value": "units", "previous": "units_prev"}) == \
        "Qatar grew fastest: +12.4%, to 4,180."
    assert say({"rule": "biggest_fall", "label": "market", "value": "units", "previous": "units_prev", "noun": "units"}) \
        == "Kuwait fell the most in units: −5.5%, to 5,310."
    assert say({"rule": "fell", "label": "market", "value": "units", "previous": "units_prev"}) == \
        "Kuwait was the only one down: −5.5%, to 5,310."
    assert say({"rule": "rose", "label": "market", "value": "units", "previous": "units_prev"}) == \
        "3 of 4 were up: Qatar (+12.4%), UAE (+8.5%), KSA (+4.5%)."
    assert say({"rule": "above", "label": "market", "value": "units", "threshold": 10000, "noun": "units"}) == \
        "Above 10,000 units: UAE (18,420), KSA (14,960)."
    assert say({"rule": "below", "label": "market", "value": "units", "threshold": 1000}) is None, "nothing below"
    assert say({"rule": "record_high", "label": "week", "value": "units", "noun": "units"}, WEEKS, {"kind": "chart"}) == \
        "W43: 48,210 units, the highest of the 8 shown."
    assert say({"rule": "record_low", "label": "week", "value": "units"}, WEEKS, {"kind": "chart"}) is None
    everyone_up = {"columns": ["m", "v", "p"], "rows": [["A", 2, 1], ["B", 3, 1]]}
    assert say({"rule": "fell", "label": "m", "value": "v", "previous": "p"}, everyone_up) is None
    assert say({"rule": "rose", "label": "m", "value": "v", "previous": "p"}, everyone_up) == "All 2 were up."
    assert say({"rule": "biggest_fall", "label": "m", "value": "v", "previous": "p"}, everyone_up) is None
    assert say({"rule": "change", "value": "units", "previous": "units_prev"}, {"columns": ["units", "units_prev"],
                                                                              "rows": [[5, 5]]}, {}) == "Units held at 5."
    assert say({"rule": "largest", "label": "market", "value": "units"}, {"columns": [], "rows": []}) is None


def test_the_issue_puts_lead_sentences_first_and_tiles_from_the_first_row():
    the_brief = {"title": "Weekly", "sections": [
        {"kind": "numbers", "items": [{"label": "Units", "value": "units", "previous": "units_prev"},
                                      {"label": "Revenue", "value": "revenue", "previous": "revenue_prev",
                                       "prefix": "AED ", "compact": True, "better": "down", "compare": "vs week 42"}],
         "highlights": [{"rule": "change", "value": "units", "previous": "units_prev", "lead": True}]},
        {**SECTION, "highlights": [{"rule": "fell", "label": "market", "value": "units", "previous": "units_prev"}]}]}
    found = brief.issue(the_brief, [NUMBERS, MARKETS], period="Week 43",
                        read_at=dt.datetime(2026, 10, 26, 4, 0, tzinfo=dt.UTC))
    assert found["lead"] == ["Units rose 5.3% to 48,210, from 45,800."] and found["period"] == "Week 43"
    assert found["read_at"] == "26 Oct 2026, 08:00", "Metronome's clock: Dubai"
    tiles = found["sections"][0]["tiles"]
    assert [t["value"] for t in tiles] == ["48,210", "AED 61.4M"] and tiles[0]["compare"] == "vs the previous period"
    assert tiles[1]["better"] == "down" and found["sections"][1]["highlights"] == ["Kuwait was the only one down: −5.5%, to 5,310."]
    assert found["sections"][1]["drawing"]["alt"].startswith("UAE 18,420 (+8.5%); KSA 14,960 (+4.5%)")


def test_charts_draw_to_scale_and_save_as_svg():
    bars = brief.chart(SECTION, MARKETS)
    assert bars["width"] == brief.WIDTH and bars["height"] > 100
    rects = [s for s in bars["shapes"] if s[0] == "rect" and s[5] == brief.ACCENT and s[3] > 10]
    assert [round(r[3] / rects[0][3], 3) for r in rects] == [round(v / 18420, 3) for v in (18420, 14960, 5310, 4180)]
    texts = [s[3] for s in bars["shapes"] if s[0] == "text"]
    assert "+12.4%" in texts and "−5.5%" in texts and "vs week 42" in texts and "20K" in texts
    line = brief.chart({"kind": "chart", "chart": "line", "x": "week", "series": ["units"]}, WEEKS)
    assert any(s[0] == "polyline" and len(s[1]) == 8 for s in line["shapes"])
    assert "48,210" in [s[3] for s in line["shapes"] if s[0] == "text"]
    for drawing in (bars, line):
        root = ET.fromstring(brief.svg(drawing))  # noqa: S314 - Wizard's own SVG, not untrusted input
        assert root.tag.endswith("svg") and root.get("width") == str(brief.WIDTH)
    assert brief.chart(SECTION, {"columns": ["market"], "rows": []}) is None
    assert brief.chart({**SECTION, "series": ["market"]}, MARKETS) is None, "no numbers, no chart"


def test_the_email_escapes_every_value_and_falls_back_to_tables():
    hostile = {"columns": ["market", "units", "units_prev"], "rows": [["<script>x</script>", 5, 4]]}
    the_brief = {"title": "Sell-out <b>now</b>", "intro": "A & B", "cadence": "Every Monday at 08:00",
                 "requested_by": "Rafael", "created_on": "23 Oct 2026", "database": "analytics",
                 "sections": [{**SECTION, "highlights": [{"rule": "largest", "label": "market", "value": "units"}]},
                              {"kind": "table", "title": "Top", "max_rows": 1, "sql": "x"}]}
    found = brief.issue(the_brief, [hostile, MARKETS], read_at=dt.datetime(2026, 10, 26, 4, 0, tzinfo=dt.UTC))
    page = brief.render(the_brief, found)
    assert "<script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page and "Sell-out &lt;b&gt;now&lt;/b&gt;" in page
    assert "WIZARD BRIEF" not in page and "Wizard brief · Every Monday at 08:00" in page and "A &amp; B" in page
    assert "<img" not in page, "without an image the chart goes in as its table"
    assert "3 more rows in the attached Excel file." in page and "PostgreSQL database analytics: 2 read-only queries" in page
    assert "You get this because Rafael set it up in Wizard on 23 Oct 2026." in page
    with_image = brief.render(the_brief, found, {0: "cid:chart-1.png"})
    assert '<img src="cid:chart-1.png" width="544" alt="&lt;script&gt;x&lt;/script&gt; 5 (+25.0%)"' in with_image


def test_sheet_names_are_safe_and_unique():
    sections = [{"title": "Sell-out: UAE/KSA?"}, {"title": "Sell-out: UAE/KSA?"}, {"title": None}, {"title": "x" * 40}]
    assert brief.sheet_names({"sections": sections}) == ["Sell-out  UAE KSA", "Sell-out  UAE KSA 2", "Section 3", "x" * 28]


def test_the_renderer_stays_standard_library_only():
    """The generated script carries this file verbatim into Metronome's Python: no Wizard imports, no third-party
    imports at module level, and no `from __future__` (it would sit in the middle of the script)."""
    tree = ast.parse(Path(brief.__file__).read_text(encoding="utf-8"))
    top = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    top |= {node.module.split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom) and node.module}
    assert top <= {"datetime", "decimal", "html", "math", "re"}, top
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "__future__" for node in ast.walk(tree))

"""How Wizard's presentations look: design tokens (fonts, colors, point sizes, slide size, cover, footer) read from the
company knowledge base, else Wizard's neutral design.

The company's look is company content, so it never lives in this repository: the presentation guide's
`presentation-look` note (knowledge-standard.md, section 12) carries it as a fenced ```json block under
`## Design tokens`, written by the presentation-guide task from the company's decks or a written guide. Every deck reads
the note when it is made, so a corrected note changes the next deck without an update. A value the note gets wrong
(not a color, a size out of range, an unknown key) is left out with a problem Gemini can report, and Wizard's neutral
value stands in for it; the deck is still made."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from .knowledge import KnowledgeBase

LOOK_NOTE = "presentation-look"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)\n```", re.DOTALL)

# Wizard's own neutral design: a white 16:9 deck in Arial with a navy accent. No company's colors or fonts.
DEFAULT: dict[str, Any] = {
    "name": "Wizard neutral",
    "slide": {"width": 13.333, "height": 7.5},
    "fonts": {"title": "Arial", "subtitle": "Arial", "body": "Arial", "labels": "Arial", "east_asian": "Malgun Gothic"},
    "colors": {
        "brand": "#1F3A93",       # cover band, section dividers, card numbers, header rules
        "title": "#111111",       # slide titles
        "text": "#222222",        # body text and numbers
        "secondary": "#404040",   # subtitles, table header text
        "muted": "#7F7F7F",       # units, labels, footnotes, page numbers
        "background": "#FFFFFF",  # slides
        "card": "#EEF1F5",        # cards, table header rows, bands
        "line": "#D9D9D9",        # borders and gridlines
        "good_fill": "#E2EFDA", "good_text": "#375623",  # a highlighted cell that is good news
        "bad_fill": "#FFF2CC", "bad_text": "#7F6000",    # a highlighted cell that needs attention
        "positive": "#1F7A3A", "negative": "#C00000",    # ▲ and ▼ changes on numbers
        "series": ["#1F3A93", "#8497B0", "#2E75B6", "#A5A5A5", "#264478", "#C9C9C9"],
    },
    "sizes": {"cover_title": 40, "cover_subtitle": 20, "cover_meta": 14, "title": 26, "subtitle": 14,
              "section_title": 36, "agenda": 20, "heading": 14, "body": 12, "kpi": 32, "table": 11,
              "chart_label": 10, "unit": 9, "footnote": 8},
    "cover": {"background": "brand"},  # brand: the title on a brand-colored slide; white: on white with a brand rule
    "footer": {"text": "", "page_numbers": True},
    "rules": {"max_highlights": 4, "max_points": 6},
}

LIMITS = {"slide": (4.0, 20.0), "sizes": (5.0, 96.0), "rules": (1, 12)}
SCHEMA_NOTE = ("The tokens are a JSON object with any of: name; slide {width, height} in inches; fonts {title, "
               "subtitle, body, labels, east_asian}; colors {" + ", ".join(k for k in DEFAULT["colors"] if k != "series")
               + ", series: [hex, ...]} as #RRGGBB; sizes {" + ", ".join(DEFAULT["sizes"]) + "} in points; cover "
               "{background: brand | white}; footer {text, page_numbers}; rules {max_highlights, max_points}.")


def tokens_block(body: str) -> tuple[dict[str, Any] | None, str | None]:
    """The note's design tokens: the first fenced JSON block holding an object with fonts, colors or sizes (the one
    under `## Design tokens`). (None, why) when there is none or it is not JSON."""
    for match in FENCE.finditer(body):
        text = match.group(1).strip()
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            return None, f"its design tokens are not valid JSON ({error.msg}, line {error.lineno})"
        if isinstance(value, dict) and any(k in value for k in ("fonts", "colors", "sizes", "slide")):
            return value, None
    return None, "it has no design tokens block (a ```json block under ## Design tokens)"


def merge(found: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Wizard's neutral design with the note's valid values over it, and what was left out and why."""
    tokens = copy.deepcopy(DEFAULT)
    problems: list[str] = []
    for key, value in found.items():
        if key == "name":
            if isinstance(value, str) and value.strip():
                tokens["name"] = value.strip()[:80]
            continue
        if key not in DEFAULT or key == "name":
            problems.append(f"unknown key '{key}'")
            continue
        if not isinstance(value, dict):
            problems.append(f"'{key}' is not an object")
            continue
        for name, item in value.items():
            where = f"{key}.{name}"
            if name not in DEFAULT[key]:
                problems.append(f"unknown key '{where}'")
            elif key == "fonts":
                if isinstance(item, str) and 0 < len(item.strip()) <= 64:
                    tokens[key][name] = item.strip()
                else:
                    problems.append(f"'{where}' is not a font name")
            elif key == "colors" and name == "series":
                good = [c.upper() for c in item if isinstance(c, str) and HEX.match(c)] if isinstance(item, list) else []
                if good:
                    tokens[key][name] = good[:12]
                if not isinstance(item, list) or len(good) != len(item):
                    problems.append(f"'{where}' must be a list of #RRGGBB colors")
            elif key == "colors":
                if isinstance(item, str) and HEX.match(item):
                    tokens[key][name] = item.upper()
                else:
                    problems.append(f"'{where}' is not a #RRGGBB color")
            elif key in LIMITS:
                low, high = LIMITS[key]
                if isinstance(item, int | float) and not isinstance(item, bool) and low <= item <= high:
                    tokens[key][name] = int(item) if key == "rules" else float(item)
                else:
                    problems.append(f"'{where}' must be a number from {low:g} to {high:g}")
            elif key == "cover":
                if item in ("brand", "white"):
                    tokens[key][name] = item
                else:
                    problems.append(f"'{where}' must be brand or white")
            elif key == "footer":
                if name == "page_numbers" and isinstance(item, bool):
                    tokens[key][name] = item
                elif name == "text" and isinstance(item, str) and len(item) <= 120:
                    tokens[key][name] = item.strip()
                else:
                    problems.append(f"'{where}' is not valid")
    return tokens, problems


def company_design(knowledge: KnowledgeBase) -> dict[str, Any]:
    """The design a new deck uses, with where it came from: {tokens, source: knowledge | default, note, status,
    problems, about}."""
    note = knowledge.by_id.get(LOOK_NOTE)
    if note is None:
        return {"tokens": copy.deepcopy(DEFAULT), "source": "default", "note": None, "status": None, "problems": [],
                "about": f"Wizard's neutral design: the knowledge base has no {LOOK_NOTE} note yet. The task \"Write the "
                         "company's presentation guide\" (Settings → Tasks) writes it from the company's decks or a "
                         "written guide."}
    found, why = tokens_block(note.body)
    if found is None:
        return {"tokens": copy.deepcopy(DEFAULT), "source": "default", "note": note.id, "status": note.status,
                "problems": [why] if why else [],
                "about": f"Wizard's neutral design: the {note.id} note is there but {why}. {SCHEMA_NOTE}"}
    tokens, problems = merge(found)
    return {"tokens": tokens, "source": "knowledge", "note": note.id, "status": note.status, "problems": problems,
            "about": f"The company's design from the {note.id} note ({note.status})" +
                     (f"; left out: {'; '.join(problems[:8])}" if problems else "") + "."}

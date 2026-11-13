"""Presentations (owner, 13 Nov 2026: "Wizard should be able to make complete powerpoint presentations, start to finish
... powerpoints are all about storyline ... any changes can be requested in the chat easily").

Gemini plans the deck and Wizard draws it:
- `wizard_propose_storylines` asks the person which story the deck tells: two to four storylines grounded in what the
  analysis found, each with its arc, shown as a card whose choice is the person's next message (it ends the turn, as
  `wizard_ask_person` does, and shares its one question per request).
- `wizard_make_presentation` takes the deck as slides of a few kinds (cover, agenda, section, summary, kpis, cards,
  chart, table, split, text, closing) that show the conversation's visuals and cite its evidence. It checks what the
  page needs to draw every slide, keeps the deck (D1, D2... per conversation) with copies of the visuals it shows and the
  names of the sources it cites, and returns the outline and anything worth fixing.
- `wizard_change_presentation` applies the person's changes (update, insert, delete or move slides, retitle the deck)
  to a deck as a new version; `wizard_read_presentation` returns a deck's slides in full.

The look is the company's, from the knowledge base (deck_design.py), never Gemini's choice. The page draws the slides
and writes the PowerPoint file, with native, editable charts and tables (apps/web/src/deck/). Nothing here writes to a
company system: a deck is the person's to download."""
from __future__ import annotations

import copy
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..deck_design import company_design
from .registry import ToolContext, ToolError, ToolSpec

EVIDENCE_ID = r"^E[0-9]{1,4}$"
VISUAL_ID = r"^V[0-9]{1,4}$"
DECK_ID = r"^D[0-9]{1,4}$"
MAX_SLIDES = 40
KINDS = ("cover", "agenda", "section", "summary", "kpis", "cards", "chart", "table", "split", "text", "closing")
CHART_STYLES = ("auto", "column", "stacked", "percent", "bar", "stacked_bar", "line")
KIND_WORDS = {"cover": "Cover", "agenda": "Agenda", "section": "Section", "summary": "Executive summary", "kpis": "Key figures",
              "cards": "Cards", "chart": "Chart", "table": "Table", "split": "Two panels", "text": "Text", "closing": "Closing"}
FIGURE = re.compile(r"\d")
LONG_TITLE = 110
MAX_TABLE_ROWS = 16  # rows a table slide shows at a readable size (apps/web/src/deck/layout.ts shrinks, then cuts)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- The storyline question -------------------------------------------------------------------------------------------


class Storyline(Args):
    title: str = Field(min_length=5, max_length=140, description=(
        "The story's message in one line, as the deck would argue it, from what the analysis found, e.g. 'Flagship "
        "carried Q3 while Mass lost share: shift spend to the A-series'."))
    arc: list[str] = Field(min_length=2, max_length=7, description=(
        "The beats in order, each a slide or a section, e.g. ['Q3 beat plan by 6%', 'Flagship drove it', 'Mass lost 2 "
        "pp to C-brands', 'Three moves for Q4']. At most 120 characters each."))
    best_for: str | None = Field(default=None, max_length=120, description="Optional: the audience or moment it suits, "
                                 "e.g. 'a board update' or 'a planning workshop'.")

    @model_validator(mode="after")
    def _beats(self) -> Storyline:
        self.arc = [" ".join(b.split())[:120] for b in self.arc if b.strip()]
        if len(self.arc) < 2:
            raise ValueError("give at least two beats")
        return self


class StorylinesArgs(Args):
    question: str = Field(default="What story should the presentation tell?", min_length=5, max_length=200,
                          description="The question as the person reads it, in their language.")
    storylines: list[Storyline] = Field(min_length=2, max_length=4, description=(
        "Two to four different stories the evidence supports (not the same story reworded), the one you would choose "
        "first. The person picks one or writes their own."))
    why: str | None = Field(default=None, max_length=300, description="Optional: one short sentence on what the choice "
                            "changes in the deck.")


def propose_storylines(ctx: ToolContext, args: StorylinesArgs) -> dict[str, Any]:
    storylines: list[dict[str, Any]] = []
    for item in args.storylines:
        title = " ".join(item.title.split())
        if any(str(s["title"]).casefold() == title.casefold() for s in storylines):
            continue
        storylines.append({"title": title, "arc": item.arc, "best_for": " ".join((item.best_for or "").split()) or None})
    if len(storylines) < 2:
        raise ToolError("invalid_arguments", "Give at least two different storylines.")
    return {"question": " ".join(args.question.split()), "storylines": storylines,
            "why": " ".join((args.why or "").split()) or None,
            "next": "The storylines are a card under your answer. End your turn now: say in one or two short lines what "
                    "you found and that the deck follows the story they choose (or one they write). Make no deck yet; "
                    "their choice comes as their next message."}


# --- The deck ---------------------------------------------------------------------------------------------------------


class Point(Args):
    text: str = Field(min_length=1, max_length=300, description="The bullet; **bold** marks a lead-in, e.g. '**Flagship:** +18% vs plan'.")
    sub: list[str] = Field(default_factory=list, max_length=4, description="Optional second-level bullets, at most 200 characters each.")


PointItem = str | Point


class Kpi(Args):
    value: str = Field(min_length=1, max_length=24, description="The figure as shown, e.g. '$12.4M', '+18%', '2.1 pp'.")
    label: str = Field(min_length=1, max_length=80, description="What it is, with its period and scope, e.g. 'Q3 sell-out, MENA'.")
    change: str | None = Field(default=None, max_length=40, description="Optional comparison, e.g. '▲ 6% vs plan' or '▼ 1.2 pp YoY'.")
    tone: Literal["good", "bad", "neutral"] = Field(default="neutral", description="good or bad colours the change; neutral leaves it plain.")
    evidence_ids: list[str] = Field(default_factory=list, max_length=6, description="Evidence the figure comes from, e.g. ['E2'].")


class Card(Args):
    heading: str = Field(min_length=1, max_length=80, description="The card's title, e.g. 'Win the mid-tier'.")
    points: list[PointItem] = Field(default_factory=list, max_length=6)
    value: str | None = Field(default=None, max_length=24, description="Optional big figure at the top of the card.")


class Highlight(Args):
    row: str = Field(min_length=1, max_length=120, description="The row's label, as in the visual's first column (its x).")
    column: str = Field(min_length=1, max_length=80, description="The column's key or label.")
    tone: Literal["good", "bad"] = Field(description="good: the light green fill (target met, growth); bad: the light yellow fill (gap, decline).")


class Panel(Args):
    heading: str | None = Field(default=None, max_length=80)
    visual: str | None = Field(default=None, pattern=VISUAL_ID, description="A visual id from wizard_render_visual, e.g. 'V2'.")
    chart: Literal["auto", "column", "stacked", "percent", "bar", "stacked_bar", "line"] = "auto"
    points: list[PointItem] = Field(default_factory=list, max_length=6)


class SlideFields(Args):
    """Every field a slide can have; which ones a kind uses is in wizard_make_presentation's description."""
    title: str | None = Field(default=None, max_length=160, description=(
        "The slide's message as a full sentence (a takeaway, not a topic), e.g. 'Flagship carried Q3: +18% vs plan'. "
        "The cover's title is the deck's title; an agenda's defaults to 'Agenda'."))
    subtitle: str | None = Field(default=None, max_length=200, description="The scope under the title: market, period, unit, e.g. 'MENA · Q3 2026 · sell-out, units'.")
    meta: str | None = Field(default=None, max_length=120, description="cover: the line with the region and date, e.g. 'MENA · November 2026'.")
    points: list[PointItem] | None = Field(default=None, max_length=8, description="Bullets (summary, text, closing, beside a chart or table).")
    kpis: list[Kpi] | None = Field(default=None, max_length=6, description="kpis (2-6) or a summary's key figures (up to 4).")
    cards: list[Card] | None = Field(default=None, max_length=4, description="cards: 2-4 columns, each numbered.")
    visual: str | None = Field(default=None, pattern=VISUAL_ID, description="chart or table: the visual's id, e.g. 'V1'.")
    chart: Literal["auto", "column", "stacked", "percent", "bar", "stacked_bar", "line"] | None = Field(default=None, description=(
        "chart: how a bar visual is drawn: column (vertical bars; time or few categories), stacked (stacked columns: a "
        "total split by channel or segment over time), percent (100% stacked columns: mix and share splits), bar "
        "(horizontal bars: rankings, long names), stacked_bar, or line (trends with markers). auto chooses."))
    highlights: list[Highlight] | None = Field(default=None, max_length=16, description=(
        "table: the few cells to shade, good (green) or bad (yellow); a handful per slide, never a whole column."))
    left: Panel | None = Field(default=None, description="split: the left panel (a visual or bullets, with a heading).")
    right: Panel | None = Field(default=None, description="split: the right panel.")
    items: list[str] | None = Field(default=None, max_length=10, description="agenda: the topics; leave empty to list the deck's section slides with their pages.")
    evidence_ids: list[str] | None = Field(default=None, max_length=20, description="Evidence behind figures in the slide's text (a visual's evidence is added by itself).")
    footnote: str | None = Field(default=None, max_length=300, description="An extra footnote: a definition, a caveat, how a figure was derived.")
    notes: str | None = Field(default=None, max_length=2000, description="Speaker notes: what to say on this slide.")


class Slide(SlideFields):
    kind: Literal["cover", "agenda", "section", "summary", "kpis", "cards", "chart", "table", "split", "text", "closing"] = Field(
        description="The slide's kind; see the tool description for what each holds.")


class SlidePatch(SlideFields):
    kind: Literal["cover", "agenda", "section", "summary", "kpis", "cards", "chart", "table", "split", "text", "closing"] | None = None


class DeckArgs(Args):
    title: str = Field(min_length=1, max_length=160, description="The deck's title (its file name too).")
    storyline: str = Field(min_length=10, max_length=600, description=(
        "The story the deck tells, in one or two sentences: the storyline the person chose or wrote, which every slide "
        "title advances."))
    audience: str | None = Field(default=None, max_length=120, description="Optional: who it is for, e.g. 'the CEO's monthly review'.")
    slides: list[Slide] = Field(min_length=1, max_length=MAX_SLIDES, description="The slides in order, the cover first.")


class DeckPatch(Args):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    storyline: str | None = Field(default=None, min_length=10, max_length=600)
    audience: str | None = Field(default=None, max_length=120)


class Change(Args):
    action: Literal["update", "insert", "delete", "move", "deck"] = Field(description=(
        "update: change fields of slide `at` (only the fields given in `slide`; a field set to null is removed); insert: "
        "add `slide` (a whole slide with its kind) after slide `at` (0 puts it first); delete: remove slide `at`; move: "
        "put slide `at` at number `to`; deck: change the deck's title, storyline or audience (`deck`)."))
    at: int | None = Field(default=None, ge=0, le=MAX_SLIDES, description="The slide number, as the deck stands after the changes before this one.")
    to: int | None = Field(default=None, ge=1, le=MAX_SLIDES, description="move: the slide's new number.")
    slide: SlidePatch | None = Field(default=None, description=(
        "update: the fields that change, e.g. {\"title\": \"...\"} or {\"kind\": \"table\", \"highlights\": [...]}; "
        "insert: the whole new slide, with its kind."))
    deck: DeckPatch | None = Field(default=None, description="deck: the deck's fields that change.")


class ChangeArgs(Args):
    deck: str = Field(pattern=DECK_ID, description="The deck to change, e.g. 'D1' (its latest version is what the person sees).")
    changes: list[Change] = Field(min_length=1, max_length=30, description="Applied in order.")


class ReadDeckArgs(Args):
    deck: str = Field(pattern=DECK_ID, description="The deck, e.g. 'D1'.")
    slides: list[int] = Field(default_factory=list, max_length=MAX_SLIDES, description="Slide numbers to return in full; empty: all.")


def _points(items: list[Any] | None) -> list[Any]:
    return [i if isinstance(i, dict) else " ".join(str(i).split()) for i in items or [] if (i.get("text") if isinstance(i, dict) else str(i).strip())]


def _clean(slide: dict[str, Any]) -> dict[str, Any]:
    """A slide as the deck keeps it: only the fields it has, text without stray spaces."""
    out: dict[str, Any] = {}
    for key, value in slide.items():
        if value is None or value == [] or value == "":
            continue
        if key in ("title", "subtitle", "meta", "footnote") and isinstance(value, str):
            value = " ".join(value.split())
        if key == "points":
            value = _points(value)
        if key == "cards":
            value = [{**{k: v for k, v in c.items() if v not in (None, [], "")}, "points": _points(c.get("points"))} for c in value]
        if key in ("left", "right") and isinstance(value, dict):
            value = {k: (_points(v) if k == "points" else v) for k, v in value.items() if v not in (None, [], "")}
        out[key] = value
    return out


def _visuals(ctx: ToolContext) -> dict[str, dict[str, Any]]:
    return {v["id"]: v for v in ctx.recorder.all_visuals()}


def _row_labels(visual: dict[str, Any]) -> list[str]:
    keys = [c["key"] for c in visual["columns"]]
    index = keys.index(visual["x"]) if visual.get("x") in keys else 0
    return [str(r[index]) for r in visual["rows"] if r[index] is not None]


def _check(slides: list[dict[str, Any]], visuals: dict[str, dict[str, Any]], known: set[str],
           rules: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(problems that stop the deck, warnings worth fixing). Numbers are the slides' page numbers."""
    problems: list[str] = []
    warnings: list[str] = []
    max_points, max_highlights = int(rules.get("max_points", 6)), int(rules.get("max_highlights", 4))

    def visual(n: int, vid: str | None, need: str, chart: str | None = None) -> dict[str, Any] | None:
        if not vid:
            problems.append(f"Slide {n} ({need}) needs a visual id from wizard_render_visual.")
            return None
        found = visuals.get(vid)
        if found is None:
            problems.append(f"Slide {n}: there is no visual {vid} in this conversation (known: {', '.join(sorted(visuals, key=lambda v: int(v[1:]))) or 'none yet'}).")
            return None
        if need == "chart" and found["kind"] not in ("bar", "line", "scatter"):
            problems.append(f"Slide {n}: {vid} is a {found['kind']}; show it on a table slide, or render a chart.")
        if chart in ("stacked", "percent", "stacked_bar") and (found["kind"] != "bar" or len(found["series"]) < 2):
            problems.append(f"Slide {n}: a {chart} chart needs a bar visual with two or more series; {vid} has "
                            f"{len(found['series'])} {found['kind']} series.")
        if chart and chart != "auto" and found["kind"] == "scatter":
            problems.append(f"Slide {n}: {vid} is a scatter chart; leave chart as auto.")
        return found

    for n, slide in enumerate(slides, 1):
        kind = slide["kind"]
        title = slide.get("title") or ""
        if kind not in ("agenda",) and not title:
            problems.append(f"Slide {n} ({kind}) needs a title.")
        if len(title) > LONG_TITLE and kind not in ("cover",):
            warnings.append(f"Slide {n}'s title has {len(title)} characters; it is drawn smaller. Aim under 90.")
        points = slide.get("points") or []
        if len(points) > max_points:
            warnings.append(f"Slide {n} has {len(points)} bullets; the company's slides keep to {max_points}.")
        if kind == "kpis" and not 2 <= len(slide.get("kpis") or []) <= 6:
            problems.append(f"Slide {n} (kpis) needs 2 to 6 kpis.")
        if kind == "summary" and len(points) + len(slide.get("kpis") or []) < 2:
            problems.append(f"Slide {n} (summary) needs at least two points or key figures.")
        if kind == "summary" and len(slide.get("kpis") or []) > 4:
            problems.append(f"Slide {n} (summary) shows at most 4 key figures; use a kpis slide for more.")
        if kind == "cards" and not 2 <= len(slide.get("cards") or []) <= 4:
            problems.append(f"Slide {n} (cards) needs 2 to 4 cards.")
        if kind == "text" and not points:
            problems.append(f"Slide {n} (text) needs points.")
        if kind == "chart":
            visual(n, slide.get("visual"), "chart", slide.get("chart"))
        if kind == "table":
            found = visual(n, slide.get("visual"), "table")
            if found and len(found["rows"]) > MAX_TABLE_ROWS:
                warnings.append(f"Slide {n}'s table has {len(found['rows'])} rows; a slide shows about {MAX_TABLE_ROWS}. "
                                "Render a table of the rows that carry the message, or split it over two slides.")
            if found and slide.get("highlights"):
                rows = {r.casefold() for r in _row_labels(found)}
                columns = {c["key"].casefold() for c in found["columns"]} | {c["label"].casefold() for c in found["columns"]}
                for h in slide["highlights"]:
                    if h["row"].casefold() not in rows:
                        problems.append(f"Slide {n}: no row '{h['row']}' in {found['id']} (rows are named by its first column).")
                    if h["column"].casefold() not in columns:
                        problems.append(f"Slide {n}: no column '{h['column']}' in {found['id']}.")
                for tone in ("good", "bad"):
                    count = sum(1 for h in slide["highlights"] if h["tone"] == tone)
                    if count > max_highlights:
                        warnings.append(f"Slide {n} shades {count} {tone} cells; the company's tables shade at most "
                                        f"{max_highlights} of each, so the few that matter stand out.")
        if kind != "table" and slide.get("highlights"):
            problems.append(f"Slide {n}: highlights apply to a table slide only.")
        if kind == "split":
            for side in ("left", "right"):
                panel = slide.get(side)
                if not panel or not (panel.get("visual") or panel.get("points")):
                    problems.append(f"Slide {n} (split) needs a {side} panel with a visual or points.")
                elif panel.get("visual"):
                    visual(n, panel["visual"], "panel", panel.get("chart"))
        if kind not in ("chart", "table") and slide.get("visual"):
            problems.append(f"Slide {n}: a {kind} slide shows no visual; use a chart, table or split slide.")
        cited = list(slide.get("evidence_ids") or []) + [e for k in slide.get("kpis") or [] for e in k.get("evidence_ids") or []]
        unknown = [e for e in cited if e not in known]
        if unknown:
            problems.append(f"Slide {n}: unknown evidence id(s) {', '.join(unknown)}.")
        if kind in ("summary", "kpis", "cards", "text") and not cited and _has_figures(slide):
            warnings.append(f"Slide {n} states figures but cites no evidence: add evidence_ids so its source line names them.")
    if slides and slides[0]["kind"] != "cover":
        warnings.append("The first slide is not a cover.")
    return problems, warnings


def _has_figures(slide: dict[str, Any]) -> bool:
    texts = [str(slide.get("title") or "")] + [p if isinstance(p, str) else p["text"] for p in slide.get("points") or []]
    texts += [k["value"] for k in slide.get("kpis") or []] + [c.get("value") or "" for c in slide.get("cards") or []]
    return any(FIGURE.search(t) for t in texts[1:]) or bool(slide.get("kpis"))


def _evidence_of(slide: dict[str, Any], visuals: dict[str, dict[str, Any]]) -> list[str]:
    ids = list(slide.get("evidence_ids") or []) + [e for k in slide.get("kpis") or [] for e in k.get("evidence_ids") or []]
    for vid in (slide.get("visual"), (slide.get("left") or {}).get("visual"), (slide.get("right") or {}).get("visual")):
        if vid and vid in visuals:
            ids += visuals[vid].get("evidence_ids") or []
    return list(dict.fromkeys(ids))


def _source(evidence: dict[str, Any]) -> dict[str, Any]:
    name = " · ".join(str(p) for p in (evidence.get("system_name") or evidence.get("system"), evidence.get("report_name")) if p)
    return {"name": name or evidence["id"], "as_of": evidence.get("as_of"), "data_mode": evidence.get("data_mode")}


def outline(slides: list[dict[str, Any]]) -> list[str]:
    return [f"{n}. {KIND_WORDS[s['kind']]}: {s.get('title') or ('Agenda' if s['kind'] == 'agenda' else '')}".rstrip(": ")
            for n, s in enumerate(slides, 1)]


def _store(ctx: ToolContext, head: dict[str, Any], slides: list[dict[str, Any]], revises: dict[str, Any] | None) -> dict[str, Any]:
    visuals = _visuals(ctx)
    evidence = {e["id"]: e for e in ctx.recorder.all_evidence()}
    design = revises["design"] if revises else company_design(ctx.services.knowledge)
    problems, warnings = _check(slides, visuals, set(evidence), design["tokens"]["rules"])
    if problems:
        raise ToolError("invalid_presentation", " ".join(problems[:12]) + " Fix these and call the tool again.")
    shown = {vid for s in slides for vid in (s.get("visual"), (s.get("left") or {}).get("visual"),
                                            (s.get("right") or {}).get("visual")) if vid}
    cited = list(dict.fromkeys(e for s in slides for e in _evidence_of(s, visuals)))
    modes = sorted({str(evidence[e].get("data_mode")) for e in cited if evidence[e].get("data_mode")})
    payload = {**head, "slides": slides, "design": design, "revises": revises["id"] if revises else None,
               "family": (revises.get("family") or revises["id"]) if revises else None,
               "version": int(revises.get("version") or 1) + 1 if revises else 1,
               "visuals": {vid: visuals[vid] for vid in sorted(shown, key=lambda v: int(v[1:]))},
               "sources": {e: _source(evidence[e]) for e in cited}, "evidence_ids": cited,
               "data_mode": "SYNTHETIC" if "SYNTHETIC" in modes else modes[0] if len(modes) == 1 else ("MIXED" if modes else None),
               "created_at": ctx.services.now().isoformat(timespec="seconds")}
    deck_id = ctx.recorder.add_deck(payload)
    family = payload["family"] or deck_id
    return {"deck_id": deck_id, "cite_as": f"[{deck_id}]", "revises": payload["revises"], "version": payload["version"],
            "family": family, "slides": len(slides), "outline": outline(slides), "warnings": warnings,
            "design": design["about"],
            "next": f"The deck is a card under your answer with every slide, Download and Open. Put [{deck_id}] on its own "
                    "line where it belongs and tell the person in a few lines what the deck argues, slide by slide in "
                    "short, and that they can ask for any change here in the chat"
                    + (" (fix the warnings first with wizard_change_presentation if they matter)" if warnings else "") + "."}


def make_presentation(ctx: ToolContext, args: DeckArgs) -> dict[str, Any]:
    slides = [_clean(s.model_dump()) for s in args.slides]
    head = {"title": " ".join(args.title.split()), "storyline": " ".join(args.storyline.split()),
            "audience": " ".join((args.audience or "").split()) or None}
    return _store(ctx, head, slides, None)


def _deck(ctx: ToolContext, deck_id: str) -> dict[str, Any]:
    decks = {d["id"]: d for d in ctx.recorder.all_decks()}
    if deck_id not in decks:
        raise ToolError("unknown_deck", f"No deck {deck_id} in this conversation. Decks: {', '.join(decks) or 'none yet'}.")
    return decks[deck_id]


def change_presentation(ctx: ToolContext, args: ChangeArgs) -> dict[str, Any]:
    base = _deck(ctx, args.deck)
    later = [d["id"] for d in ctx.recorder.all_decks() if d.get("revises") == base["id"]]
    slides = copy.deepcopy(base["slides"])
    head = {k: base.get(k) for k in ("title", "storyline", "audience")}
    for index, change in enumerate(args.changes, 1):
        where = f"Change {index} ({change.action})"

        def number(value: int | None, allow_zero: bool = False, where: str = where) -> int:
            if value is None or not ((0 if allow_zero else 1) <= value <= len(slides)):
                raise ToolError("invalid_change", f"{where}: slide number {value} is not in the deck (1 to {len(slides)}).")
            return value

        if change.action == "update":
            at = number(change.at)
            if change.slide is None:
                raise ToolError("invalid_change", f"{where}: give the fields that change in `slide`.")
            merged = {**slides[at - 1], **change.slide.model_dump(exclude_unset=True)}
            slides[at - 1] = _clean(Slide.model_validate({k: v for k, v in merged.items() if v is not None}).model_dump())
        elif change.action == "insert":
            at = number(change.at, allow_zero=True)
            if change.slide is None or change.slide.kind is None:
                raise ToolError("invalid_change", f"{where}: give the new slide, with its kind, in `slide`.")
            if len(slides) >= MAX_SLIDES:
                raise ToolError("invalid_change", f"{where}: a deck has at most {MAX_SLIDES} slides.")
            slides.insert(at, _clean(Slide.model_validate(change.slide.model_dump(exclude_none=True)).model_dump()))
        elif change.action == "delete":
            at = number(change.at)
            if len(slides) == 1:
                raise ToolError("invalid_change", f"{where}: a deck keeps at least one slide.")
            slides.pop(at - 1)
        elif change.action == "move":
            at = number(change.at)
            to = number(change.to)
            slides.insert(to - 1, slides.pop(at - 1))
        else:
            if change.deck is None:
                raise ToolError("invalid_change", f"{where}: give the deck's fields that change in `deck`.")
            for key, value in change.deck.model_dump(exclude_unset=True).items():
                if key != "audience" and not value:
                    raise ToolError("invalid_change", f"{where}: the deck's {key} cannot be empty.")
                head[key] = " ".join(value.split()) if isinstance(value, str) else None
    result = _store(ctx, head, slides, base)
    if later:
        result["note"] = (f"{base['id']} had already been changed into {', '.join(later)}; this version starts again from "
                          f"{base['id']}. Change the latest version unless the person asked to go back.")
    return result


def read_presentation(ctx: ToolContext, args: ReadDeckArgs) -> dict[str, Any]:
    deck = _deck(ctx, args.deck)
    wanted = set(args.slides)
    newer = [d["id"] for d in ctx.recorder.all_decks() if d.get("revises") == deck["id"]]
    return {"deck": deck["id"], "title": deck["title"], "storyline": deck["storyline"], "audience": deck.get("audience"),
            "version": deck.get("version", 1), "changed_into": newer or None, "outline": outline(deck["slides"]),
            "slides": [{"number": n, **s} for n, s in enumerate(deck["slides"], 1) if not wanted or n in wanted],
            "design": deck["design"]["about"]}


MAKE_DESCRIPTION = (
    "Make a PowerPoint presentation from your analysis: the person gets every slide to see, download and open in "
    "PowerPoint, with editable charts and tables, in the company's design (from the knowledge base). Use it once the "
    "person has chosen the storyline (wizard_propose_storylines) or said the story themselves; render the charts and "
    "tables first with wizard_render_visual and show them by id. Every slide's title is a full-sentence takeaway that "
    "advances the storyline; the subtitle gives the scope (market, period, unit). Slide kinds and their fields: "
    "cover (title, subtitle, meta: region and date); agenda (items, or empty to list the section slides); section "
    "(title, subtitle: a divider); summary (the executive summary: points, up to 4 kpis); kpis (2-6 kpis: big figures "
    "with label, change and tone); cards (2-4 cards: numbered columns with heading, points, optional value: strategy, "
    "options, initiatives); chart (visual, chart style, up to 4 points beside it as the 'so what'); table (a table or "
    "heatmap visual, highlights: the few cells to shade good or bad, points); split (left and right panels, each a "
    "visual or points, with a heading: comparisons); text (points); closing (title: next steps or the ask, points). "
    "Any slide takes evidence_ids, a footnote and speaker notes; sources and units are written on each slide from the "
    "evidence and the visuals. Returns the deck id (D1...) to place in your answer, the outline and warnings.")

DECK_TOOLS = [
    ToolSpec("wizard_propose_storylines", "Ask the person which story the presentation should tell, before you make "
             "it: two to four storylines the evidence supports, each with its message and its arc (the beats, in order). "
             "They become a card under your answer; the one clicked, or a story the person writes, is their next "
             "message. Use it when the person wants a presentation and has not said its story; skip it when they did. "
             "Then end your turn; it counts as your one question for this request.", StorylinesArgs,
             propose_storylines, "wizard", "present"),
    ToolSpec("wizard_make_presentation", MAKE_DESCRIPTION, DeckArgs, make_presentation, "wizard", "present"),
    ToolSpec("wizard_change_presentation", "Change a presentation you made, as the person asks in the chat (a title, "
             "a slide's kind or chart style, cells to highlight, a slide added, removed or moved, the storyline): "
             "the changes make a new version the person sees in place of the old one. Read the slides first with "
             "wizard_read_presentation when you need their full content.", ChangeArgs, change_presentation, "wizard",
             "present"),
    ToolSpec("wizard_read_presentation", "Read a presentation made in this conversation, slide by slide in full (its "
             "kinds, titles, bullets, visuals, highlights, notes), before you change it.", ReadDeckArgs,
             read_presentation, "wizard", "present"),
]

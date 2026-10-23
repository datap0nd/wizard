"""Recurring briefs: the newsletter email Wizard proposes and Metronome sends on a schedule.

Owner decision, 23 October 2026 (docs/decisions/2026-10-23-recurring-briefs.md). A brief is a title and up to eight
sections: key numbers, charts and tables, each with its own read-only query, plus "what moved" sentences that rules
fill in from each run's rows (no AI at send time). Wizard runs this module for the preview card; the script Metronome
runs carries a verbatim copy (wizard_connectors/metronome.py), so what the person approves is what arrives.

So this file uses the standard library only, has no `from __future__` import (the copy sits in the middle of the
script) and imports matplotlib only to save a chart as PNG on Metronome. It works on plain dicts: the brief, and each
section's result as {"columns": [...], "rows": [[...]]}. Every value from a query or the conversation reaches the HTML
through html.escape.
"""
import datetime
import decimal
import html
import math
import re

# Wizard's palette (apps/web/src/styles.css): ink header, white page, one cobalt accent.
INK, INK_2, GREY, LINE, SOFT, PAGE = "#18233b", "#4b5563", "#6b7280", "#e5e7eb", "#f5f4f0", "#eef0f4"
ACCENT, UP, DOWN = "#315bd6", "#047857", "#b91c1c"
BAR_COLORS = (ACCENT, "#a9bbf0", "#cfd8f6")  # this period, then the periods it is compared with
LINE_COLORS = (ACCENT, "#d97706", "#0f766e", "#7c3aed")
FONT = "Segoe UI, Calibri, Arial, sans-serif"
WIDTH = 544  # the email's content width: 600 less 28 px either side
DUBAI = datetime.timezone(datetime.timedelta(hours=4), "Dubai")  # Metronome's clock; Dubai keeps no summer time

KINDS = ("numbers", "chart", "table")
RULES = ("change", "largest", "smallest", "biggest_rise", "biggest_fall", "rose", "fell", "above", "below",
         "record_high", "record_low")
NEEDS_PREVIOUS = ("change", "biggest_rise", "biggest_fall", "rose", "fell")
NEEDS_LABEL = ("largest", "smallest", "biggest_rise", "biggest_fall", "rose", "fell", "above", "below", "record_high",
               "record_low")
MAX_SECTIONS = 8
MAX_CHART_ROWS = 15  # bars; a line chart takes up to 60 points
MAX_LINE_POINTS = 60
MAX_LISTED = 5
NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


# Values ----------------------------------------------------------------------------------------------------------------
def number(value):
    """A float for a numeric cell (int, float, Decimal or a numeric string), else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, decimal.Decimal)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str) and NUMBER.match(value.strip()):
        return float(value.strip())
    return None


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def fmt(value, style=None) -> str:
    """A cell as the email shows it: thousands separators, the style's prefix and suffix, compact M/B when asked."""
    style = style or {}
    amount = number(value)
    if amount is None:
        return "–" if value is None else text(value)
    unit, scaled = "", amount
    if style.get("compact"):
        for size, letter in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(amount) >= size:
                scaled, unit = amount / size, letter
                break
    decimals = style.get("decimals")
    if decimals is None:
        whole = float(scaled).is_integer() and not unit
        decimals = 0 if whole or abs(scaled) >= 100 else 1 if abs(scaled) >= 1 or unit else 2
    rounded = decimal.Decimal(repr(abs(scaled))).quantize(decimal.Decimal(1).scaleb(-decimals), decimal.ROUND_HALF_UP)
    sign = "−" if scaled < 0 and rounded > 0 else ""
    return f"{sign}{style.get('prefix') or ''}{rounded:,.{decimals}f}{unit}{style.get('suffix') or ''}"


def change(current, previous):
    """Percent change from previous to current; None when there is no base to compare with."""
    now, before = number(current), number(previous)
    if now is None or before is None or before == 0:
        return None
    return (now - before) / abs(before) * 100


def fmt_change(percent) -> str:
    if percent is None:
        return ""
    if round(abs(percent), 1) == 0:
        return "0.0%"
    return f"{'+' if percent > 0 else '−'}{abs(percent):.1f}%"


def tone(percent, better="up") -> str:
    """Green when the change goes the good way, red when it goes the bad way, grey when flat or unknown."""
    if percent is None or round(percent, 1) == 0:
        return GREY
    return UP if (percent > 0) == (better != "down") else DOWN


def records(result) -> list[dict]:
    columns = list(result.get("columns") or [])
    return [dict(zip(columns, row, strict=False)) for row in result.get("rows") or []]


def style_of(section, key) -> dict:
    for column in section.get("columns") or []:
        if column.get("key") == key:
            return column
    for item in section.get("items") or []:
        if item.get("value") == key or item.get("previous") == key:
            return item
    return {}


def label_of(section, key) -> str:
    column = style_of(section, key)
    if column.get("label") and "key" in column:
        return str(column["label"])
    return str(key).replace("_", " ").strip().capitalize()


# "What moved": sentences rules fill in from the rows ------------------------------------------------------------------
def _listed(entries) -> str:
    shown = ", ".join(entries[:MAX_LISTED])
    return shown + (f" and {len(entries) - MAX_LISTED} more" if len(entries) > MAX_LISTED else "")


def sentence(section, rule, rows) -> str | None:
    """One sentence for a highlight rule, or None when the rows give it nothing to say (no market fell, say)."""
    name, noun = rule.get("rule"), (rule.get("noun") or "").strip()
    value_key, previous_key, label_key = rule.get("value"), rule.get("previous"), rule.get("label")
    style = style_of(section, value_key)
    in_noun = f" in {noun}" if noun else ""
    entries = []
    for row in rows:
        current = number(row.get(value_key))
        if current is None:
            continue
        entries.append({"label": text(row.get(label_key)) if label_key else "", "value": current,
                        "shown": fmt(row.get(value_key), style),
                        "previous": number(row.get(previous_key)) if previous_key else None,
                        "change": change(row.get(value_key), row.get(previous_key)) if previous_key else None})
    if not entries:
        return None
    if name == "change":
        first = entries[0]
        subject = (noun or label_of(section, value_key))
        subject = subject[:1].upper() + subject[1:]
        if first["previous"] is None:
            return None
        before = fmt(first["previous"], style)
        if first["change"] is None or round(first["change"], 1) == 0:
            return f"{subject} held at {first['shown']}." if first["value"] == first["previous"] else \
                f"{subject} moved from {before} to {first['shown']}."
        verb = "rose" if first["change"] > 0 else "fell"
        return f"{subject} {verb} {fmt_change(first['change']).lstrip('+−')} to {first['shown']}, from {before}."
    if name in ("largest", "smallest"):
        pick = (max if name == "largest" else min)(entries, key=lambda e: e["value"])
        word = "highest" if name == "largest" else "lowest"
        what = noun or label_of(section, value_key).lower()
        return f"{pick['label']} had the {word} {what}: {pick['shown']}."
    if name in ("biggest_rise", "biggest_fall"):
        moved = [e for e in entries if e["change"] is not None and (e["change"] > 0 if name == "biggest_rise"
                                                                     else e["change"] < 0)]
        if not moved:
            return None
        pick = (max if name == "biggest_rise" else min)(moved, key=lambda e: e["change"])
        verb = "grew fastest" if name == "biggest_rise" else "fell the most"
        return f"{pick['label']} {verb}{in_noun}: {fmt_change(pick['change'])}, to {pick['shown']}."
    if name in ("rose", "fell"):
        compared = [e for e in entries if e["change"] is not None]
        moved = [e for e in compared if (e["change"] > 0 if name == "rose" else e["change"] < 0)]
        word = "up" if name == "rose" else "down"
        if not moved:
            return None
        if len(moved) == 1 and len(compared) > 1:
            only = moved[0]
            return f"{only['label']} was the only one {word}{in_noun}: {fmt_change(only['change'])}, to {only['shown']}."
        if len(moved) == len(compared):
            return f"All {len(compared)} were {word}{in_noun}."
        moved.sort(key=lambda e: abs(e["change"]), reverse=True)
        listed = _listed(["{} ({})".format(e["label"], fmt_change(e["change"])) for e in moved])
        return f"{len(moved)} of {len(compared)} were {word}{in_noun}: {listed}."
    if name in ("above", "below"):
        limit = number(rule.get("threshold"))
        if limit is None:
            return None
        hits = [e for e in entries if (e["value"] > limit if name == "above" else e["value"] < limit)]
        if not hits:
            return None
        hits.sort(key=lambda e: e["value"], reverse=name == "above")
        what = f" {noun}" if noun else ""
        listed = _listed(["{} ({})".format(e["label"], e["shown"]) for e in hits])
        return f"{name.capitalize()} {fmt(limit, style)}{what}: {listed}."
    if name in ("record_high", "record_low"):
        if len(entries) < 3:
            return None
        last, earlier = entries[-1], [e["value"] for e in entries[:-1]]
        if (name == "record_high" and last["value"] > max(earlier)) or \
                (name == "record_low" and last["value"] < min(earlier)):
            word = "highest" if name == "record_high" else "lowest"
            what = f" {noun}" if noun else ""
            return f"{last['label']}: {last['shown']}{what}, the {word} of the {len(entries)} shown."
        return None
    return None


# Charts: one drawing (shapes in pixels) saved as SVG for the preview and as PNG for the email --------------------------
def _width(words: str, size: float, bold: bool = False) -> float:
    return len(words) * size * (0.6 if bold else 0.55)


def _clip(words: str, chars: int) -> str:
    return words if len(words) <= chars else words[: max(1, chars - 1)] + "…"


def _nice(span: float) -> float:
    if span <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(span))
    for step in (1, 2, 2.5, 5, 10):
        if span <= step * power:
            return step * power
    return 10 * power


def _ticks(low: float, high: float, count: int = 4):
    step = _nice((high - low) / count) if high > low else _nice(abs(high) or 1)
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    if end <= start:
        end = start + step
    ticks, value = [], start
    while value <= end + step / 1000:
        ticks.append(round(value, 10))
        value += step
    return start, end, ticks


def _axis(value: float) -> str:
    return fmt(value, {"compact": True, "decimals": 0 if float(value).is_integer() or abs(value) >= 1000 else 1})


def chart(section, result) -> dict | None:
    """The section's chart as a drawing: {"width", "height", "shapes", "alt"}; None when no row has a number."""
    rows = records(result)
    x_key, series = section.get("x"), list(section.get("series") or [])
    if not rows or not x_key or not series:
        return None
    if section.get("chart") == "line":
        return _line_chart(section, rows[-MAX_LINE_POINTS:], x_key, series)
    return _bar_chart(section, rows[:MAX_CHART_ROWS], x_key, series)


def _legend(section, series, colors, shapes, y=12):
    x = 0.0
    for index, key in enumerate(series):
        name = label_of(section, key)
        shapes.append(("rect", x, y - 9, 10, 10, colors[index % len(colors)]))
        shapes.append(("text", x + 15, y, name, 11, GREY, "start", False))
        x += 15 + _width(name, 11) + 18


def _bar_chart(section, rows, x_key, series):
    series = series[:3]
    style = style_of(section, series[0])
    shapes: list = []
    labels = [_clip(text(row.get(x_key)), 24) for row in rows]
    values = [[number(row.get(key)) for key in series] for row in rows]
    shown = [fmt(row.get(series[0]), style) for row in rows]
    if not any(v is not None for row in values for v in row):
        return None
    compare = bool(section.get("change")) and len(series) >= 2
    better = section.get("better") or "up"
    label_w = min(170.0, max(40.0, max(_width(t, 12) for t in labels) + 12))
    value_w = max(_width(t, 11, True) for t in shown) + 10
    right_w = 56.0 if compare else 0.0
    plot_x0, plot_x1 = label_w, WIDTH - right_w - value_w
    legend = 22.0 if len(series) > 1 else 0.0
    row_h = {1: 26.0, 2: 34.0, 3: 42.0}[len(series)]
    top = legend + 6
    bottom = top + row_h * len(rows)
    high = max([v for row in values for v in row if v is not None] + [0.0])
    _, end, ticks = _ticks(0.0, high or 1.0)
    scale = (plot_x1 - plot_x0) / end
    if len(series) > 1:
        _legend(section, series, BAR_COLORS, shapes)
    if compare:
        shapes.append(("text", WIDTH, 12, f"vs {label_of(section, series[1]).lower()}", 10.5, GREY, "end", False))
    for tick in ticks:
        x = plot_x0 + tick * scale
        shapes.append(("line", x, top - 2, x, bottom, LINE, 1))
        shapes.append(("text", x, bottom + 15, _axis(tick), 10.5, GREY, "middle", False))
    for index, row in enumerate(rows):
        y = top + index * row_h + 4
        shapes.append(("text", 0, y + 11, labels[index], 12, INK, "start", False))
        offset = 0.0
        for position, value in enumerate(values[index]):
            height = 12.0 if position == 0 else 7.0
            if value is not None and value > 0:
                shapes.append(("rect", plot_x0, y + offset, max(1.0, value * scale), height, BAR_COLORS[position]))
            offset += height + 2
        first = values[index][0]
        bar_end = plot_x0 + max(0.0, first or 0.0) * scale
        shapes.append(("text", bar_end + 6, y + 10, shown[index], 11, INK, "start", True))
        if compare:
            percent = change(row.get(series[0]), row.get(series[1]))
            if percent is not None:
                shapes.append(("text", WIDTH, y + 10, fmt_change(percent), 11, tone(percent, better), "end", True))
    alt = "; ".join(
        f"{text(row.get(x_key))} {shown[i]}" + (f" ({fmt_change(change(row.get(series[0]), row.get(series[1])))})"
                                                if compare and change(row.get(series[0]), row.get(series[1])) is not None
                                                else "")
        for i, row in enumerate(rows))
    return {"width": WIDTH, "height": bottom + 22, "shapes": shapes, "alt": alt}


def _line_chart(section, rows, x_key, series):
    series = series[:4]
    style = style_of(section, series[0])
    shapes: list = []
    values = [[number(row.get(key)) for row in rows] for key in series]
    known = [v for line in values for v in line if v is not None]
    if not known:
        return None
    low, high = min(known), max(known)
    if low >= 0 and (high - low) > high * 0.5:
        low = 0.0
    if high == low:
        low, high = low - (abs(low) or 1) * 0.1, high + (abs(high) or 1) * 0.1
    start, end, ticks = _ticks(low, high)
    legend = 22.0 if len(series) > 1 else 0.0
    left = max(_width(_axis(t), 10.5) for t in ticks) + 10
    x0, x1, y0, y1 = left, WIDTH - 8.0, legend + 16, legend + 156
    count = len(rows)

    def px(index):
        return (x0 + x1) / 2 if count == 1 else x0 + (x1 - x0) * index / (count - 1)

    def py(value):
        return y1 - (value - start) / (end - start) * (y1 - y0)

    if len(series) > 1:
        _legend(section, series, LINE_COLORS, shapes)
    for tick in ticks:
        shapes.append(("line", x0, py(tick), x1, py(tick), LINE, 1))
        shapes.append(("text", x0 - 6, py(tick) + 3.5, _axis(tick), 10.5, GREY, "end", False))
    step = max(1, math.ceil(count / 8))
    marks = list(range(0, count, step))
    if count - 1 not in marks:
        if marks and (count - 1 - marks[-1]) < step * 0.6:
            marks.pop()
        marks.append(count - 1)
    for index in marks:
        anchor = "start" if index == 0 and count > 1 else "end" if index == count - 1 and count > 1 else "middle"
        shapes.append(("text", px(index), y1 + 16, _clip(text(rows[index].get(x_key)), 12), 10.5, GREY, anchor, False))
    for position in reversed(range(len(series))):
        points = [(px(i), py(v)) for i, v in enumerate(values[position]) if v is not None]
        if not points:
            continue
        color = LINE_COLORS[position % len(LINE_COLORS)]
        if position == 0 and len(points) > 1:
            shapes.append(("area", points + [(points[-1][0], y1), (points[0][0], y1)], color, 0.08))
        if len(points) > 1:
            shapes.append(("polyline", points, color, 2.25 if position == 0 else 1.75))
        if position == 0:
            if count <= 16:
                for x, y in points[:-1]:
                    shapes.append(("circle", x, y, 3, "#ffffff", color))
            last_x, last_y = points[-1]
            shapes.append(("circle", last_x, last_y, 4.5, color, color))
            last = next(row.get(series[0]) for row in reversed(rows) if number(row.get(series[0])) is not None)
            shapes.append(("text", min(last_x, x1), last_y - 10, fmt(last, style), 11, INK, "end" if count > 1 else
                           "middle", True))
    alt = "; ".join(f"{text(row.get(x_key))} {fmt(row.get(series[0]), style)}" for row in rows)
    return {"width": WIDTH, "height": y1 + 26, "shapes": shapes, "alt": alt}


def svg(drawing) -> str:
    """The drawing as SVG text (Wizard's preview)."""
    def attr(value):
        return html.escape(str(value), quote=True)

    def n(value):
        return f"{value:.1f}".rstrip("0").rstrip(".")

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{drawing["width"]}" height="{n(drawing["height"])}" '
             f'viewBox="0 0 {drawing["width"]} {n(drawing["height"])}" font-family="{attr(FONT)}">'
             f'<rect width="100%" height="100%" fill="#ffffff"/>']
    for shape in drawing["shapes"]:
        kind = shape[0]
        if kind == "rect":
            _, x, y, w, h, color = shape
            parts.append(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="1.5" fill="{color}"/>')
        elif kind == "line":
            _, xa, ya, xb, yb, color, width = shape
            parts.append(f'<line x1="{n(xa)}" y1="{n(ya)}" x2="{n(xb)}" y2="{n(yb)}" stroke="{color}" '
                         f'stroke-width="{width}"/>')
        elif kind == "polyline":
            _, points, color, width = shape
            parts.append(f'<polyline points="{" ".join(f"{n(x)},{n(y)}" for x, y in points)}" fill="none" '
                         f'stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
        elif kind == "area":
            _, points, color, opacity = shape
            parts.append(f'<polygon points="{" ".join(f"{n(x)},{n(y)}" for x, y in points)}" fill="{color}" '
                         f'fill-opacity="{opacity}"/>')
        elif kind == "circle":
            _, x, y, r, fill, stroke = shape
            parts.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        elif kind == "text":
            _, x, y, words, size, color, anchor, bold = shape
            weight = ' font-weight="600"' if bold else ""
            parts.append(f'<text x="{n(x)}" y="{n(y)}" font-size="{size}" fill="{color}" text-anchor="{anchor}"'
                         f'{weight}>{html.escape(words)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def png(drawing, path) -> None:
    """Save the drawing as a PNG at twice its size (sharp on high-density screens). Needs matplotlib: Metronome's
    worker has it; Wizard never calls this."""
    import logging

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot
    from matplotlib.patches import Circle, FancyBboxPatch, Polygon

    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = ["Segoe UI", "Calibri", "Arial", "DejaVu Sans"]
    width, height = drawing["width"], drawing["height"]
    figure = pyplot.figure(figsize=(width / 100, height / 100), dpi=100)
    try:
        axes = figure.add_axes((0, 0, 1, 1))
        axes.set_xlim(0, width)
        axes.set_ylim(height, 0)
        axes.axis("off")
        points_per_pixel = 72 / 100
        for shape in drawing["shapes"]:
            kind = shape[0]
            if kind == "rect":
                _, x, y, w, h, color = shape
                axes.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.5", linewidth=0,
                                              facecolor=color))
            elif kind == "line":
                _, xa, ya, xb, yb, color, line_width = shape
                axes.plot([xa, xb], [ya, yb], color=color, linewidth=line_width * points_per_pixel,
                          solid_capstyle="butt")
            elif kind == "polyline":
                _, points, color, line_width = shape
                axes.plot([p[0] for p in points], [p[1] for p in points], color=color,
                          linewidth=line_width * points_per_pixel, solid_joinstyle="round")
            elif kind == "area":
                _, points, color, opacity = shape
                axes.add_patch(Polygon(points, closed=True, facecolor=color, alpha=opacity, linewidth=0))
            elif kind == "circle":
                _, x, y, r, fill, stroke = shape
                axes.add_patch(Circle((x, y), r, facecolor=fill, edgecolor=stroke, linewidth=2 * points_per_pixel,
                                      zorder=3))
            elif kind == "text":
                _, x, y, words, size, color, anchor, bold = shape
                axes.text(x, y, words, fontsize=size * points_per_pixel, color=color, fontweight="bold" if bold else
                          "normal", ha={"start": "left", "middle": "center", "end": "right"}[anchor], va="baseline",
                          zorder=4)
        figure.savefig(path, dpi=200, facecolor="#ffffff")
    finally:
        pyplot.close(figure)


# The issue: what one run of the brief says -----------------------------------------------------------------------------
def issue(brief, results, *, period=None, read_at=None) -> dict:
    """Everything the email shows for one run: each section's rows, key numbers, chart and sentences."""
    sections: list = []
    lead: list[str] = []
    for index, section in enumerate(brief.get("sections") or []):
        result = results[index] if index < len(results) else {"columns": [], "rows": []}
        rows = records(result)
        notes: list[str] = []
        for rule in section.get("highlights") or []:
            said = sentence(section, rule, rows)
            if said:
                (lead if rule.get("lead") else notes).append(said)
        entry = {"index": index, "kind": section.get("kind"), "rows": rows, "columns": list(result.get("columns") or []),
                 "highlights": notes, "total_rows": len(rows)}
        if section.get("kind") == "numbers":
            first = rows[0] if rows else {}
            entry["tiles"] = [{
                "label": item.get("label") or label_of(section, item.get("value")),
                "value": fmt(first.get(item.get("value")), item),
                "change": change(first.get(item.get("value")), first.get(item.get("previous")))
                if item.get("previous") else None,
                "compare": item.get("compare") or "vs the previous period",
                "better": item.get("better") or "up",
            } for item in section.get("items") or []]
        elif section.get("kind") == "chart":
            entry["drawing"] = chart(section, result)
        sections.append(entry)
    when = read_at.astimezone(DUBAI) if isinstance(read_at, datetime.datetime) and read_at.tzinfo else read_at
    return {"period": text(period) if period is not None else None, "lead": lead, "sections": sections,
            "read_at": when.strftime("%d %b %Y, %H:%M") if isinstance(when, datetime.datetime) else None}


# The email -------------------------------------------------------------------------------------------------------------
def _e(value) -> str:
    return html.escape(text(value), quote=True)


def _label_cell(words: str) -> str:
    return (f'<p style="margin:0 0 6px;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:{GREY};'
            f'font-weight:600">{_e(words)}</p>')


def _heading(section) -> str:
    out = ""
    if section.get("title"):
        out += f'<p style="margin:0 0 2px;font-size:16px;font-weight:600;color:{INK}">{_e(section["title"])}</p>'
    if section.get("subtitle"):
        out += f'<p style="margin:0 0 10px;font-size:12.5px;color:{GREY}">{_e(section["subtitle"])}</p>'
    elif section.get("title"):
        out += '<div style="height:8px;line-height:8px;font-size:0">&nbsp;</div>'
    return out


def _tiles(entry) -> str:
    tiles = entry.get("tiles") or []
    if not tiles:
        return ""
    width = f"{100 // len(tiles)}%"
    cells = []
    for tile in tiles:
        moved = ""
        if tile["change"] is not None:
            arrow = "▲" if tile["change"] > 0 else "▼" if tile["change"] < 0 else "■"
            moved = (f'<p style="margin:2px 0 0;font-size:12.5px;color:{tone(tile["change"], tile["better"])}">'
                     f'{arrow} {_e(fmt_change(tile["change"]).lstrip("+−"))} {_e(tile["compare"])}</p>')
        cells.append(f'<td width="{width}" valign="top" style="border:1px solid {LINE};padding:12px 14px">'
                     f'<p style="margin:0;font-size:12px;color:{GREY}">{_e(tile["label"])}</p>'
                     f'<p style="margin:2px 0 0;font-size:22px;font-weight:600;color:{INK}">{_e(tile["value"])}</p>'
                     f'{moved}</td>')
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;width:100%"><tr>{"".join(cells)}</tr></table>')


def _table(section, entry, keys=None, limit=None) -> str:
    columns = keys or entry["columns"]
    rows = entry["rows"][: limit or int(section.get("max_rows") or 10)]
    if not columns:
        return ""
    numeric = {key: any(number(row.get(key)) is not None for row in rows) and
               all(number(row.get(key)) is not None or row.get(key) is None for row in rows) for key in columns}
    head = "".join(
        f'<th align="{"right" if numeric[key] else "left"}" style="padding:6px 8px;border-bottom:2px solid {LINE};'
        f'font-size:11px;letter-spacing:0.04em;text-transform:uppercase;color:{GREY};font-weight:600">'
        f'{_e(label_of(section, key))}</th>' for key in columns)
    body = "".join(
        "<tr>" + "".join(
            f'<td align="{"right" if numeric[key] else "left"}" style="padding:7px 8px;border-bottom:1px solid {LINE};'
            f'font-size:13px;color:{INK}">{_e(fmt(row.get(key), style_of(section, key)) if numeric[key] else text(row.get(key)))}</td>'
            for key in columns) + "</tr>" for row in rows)
    more = entry["total_rows"] - len(rows)
    note = (f'<p style="margin:6px 0 0;font-size:12px;color:{GREY}">{more:,} more row{"s" if more != 1 else ""} in the '
            f'attached Excel file.</p>') if more > 0 else ""
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;width:100%">{"<tr>" + head + "</tr>"}{body}</table>{note}')


def _bullets(notes) -> str:
    if not notes:
        return ""
    items = "".join(f'<li style="margin:0 0 6px">{_e(note)}</li>' for note in notes)
    return (f'<div style="height:14px;line-height:14px;font-size:0">&nbsp;</div>{_label_cell("What moved")}'
            f'<ul style="margin:0;padding-left:20px;font-size:14px;color:{INK}">{items}</ul>')


def _block(content: str, top: int = 24) -> str:
    return f'<tr><td style="padding:{top}px 28px 0 28px">{content}</td></tr>'


def render(brief, the_issue, images=None) -> str:
    """The email as one HTML document: Outlook-safe tables and inline styles, 600 px wide. `images` maps a chart
    section's index to its <img> source (cid:... in the email, a data: URI in the preview); a chart without one is
    shown as its table."""
    images = images or {}
    title = brief.get("title") or "Wizard brief"
    eyebrow = " · ".join(part for part in ("Wizard brief", brief.get("cadence")) if part)
    period = " · ".join(part for part in (the_issue.get("period"),
                                         f"data read {the_issue['read_at']} Dubai time" if the_issue.get("read_at")
                                         else None) if part)
    rows = [
        f'<tr><td style="background:{INK};padding:22px 28px 20px 28px">'
        f'<p style="margin:0;font-size:12px;letter-spacing:0.06em;text-transform:uppercase;color:#c9d3ea">{_e(eyebrow)}</p>'
        f'<p style="margin:8px 0 4px;font-size:24px;font-weight:600;color:#ffffff">{_e(title)}</p>'
        + (f'<p style="margin:0;font-size:13px;color:#c9d3ea">{_e(period)}</p>' if period else "")
        + (f'<p style="margin:10px 0 0;font-size:13px;color:#e6eaf4">{_e(brief["intro"])}</p>' if brief.get("intro")
           else "")
        + "</td></tr>"
    ]
    if the_issue.get("lead"):
        rows.append(_block(_label_cell("In short") + f'<p style="margin:0;font-size:15.5px;line-height:1.55;color:{INK}">'
                           f'{_e(" ".join(the_issue["lead"]))}</p>'))
    for entry in the_issue.get("sections") or []:
        section = brief["sections"][entry["index"]]
        content = _heading(section)
        if entry["kind"] == "numbers":
            content += _tiles(entry)
        elif entry["kind"] == "chart":
            drawing, source = entry.get("drawing"), images.get(entry["index"])
            if drawing and source:
                content += (f'<img src="{_e(source)}" width="{WIDTH}" alt="{_e(drawing["alt"][:900])}" '
                            f'style="display:block;width:100%;max-width:{WIDTH}px;height:auto;border:0">')
            elif entry["rows"]:
                keys = [section.get("x")] + list(section.get("series") or [])
                content += _table(section, entry, [k for k in keys if k in entry["columns"]], MAX_CHART_ROWS)
            else:
                content += f'<p style="margin:0;font-size:13px;color:{GREY}">No rows this time.</p>'
        else:
            content += _table(section, entry) if entry["rows"] else \
                f'<p style="margin:0;font-size:13px;color:{GREY}">No rows this time.</p>'
        content += _bullets(entry["highlights"])
        rows.append(_block(content))
    queries = len(brief.get("sections") or []) + (1 if brief.get("period_sql") else 0)
    source = f"PostgreSQL{' database ' + brief['database'] if brief.get('database') else ''}"
    when = f" at {the_issue['read_at']} Dubai time" if the_issue.get("read_at") else ""
    who = brief.get("requested_by") or "a Wizard user"
    since = f" on {brief['created_on']}" if brief.get("created_on") else ""
    rows.append(
        f'<tr><td style="padding:24px 0 0 0"></td></tr><tr><td style="background:{SOFT};padding:18px 28px 22px 28px;'
        f'font-size:12px;line-height:1.5;color:{INK_2}">'
        f'<p style="margin:0 0 8px"><b style="color:{INK}">Sources</b> · {_e(source)}: {queries} read-only '
        f'quer{"ies" if queries != 1 else "y"}{_e(when)}. The attached Excel file has every row, one sheet per section.</p>'
        f'<p style="margin:0">You get this because {_e(who)} set it up in Wizard{_e(since)}. To stop it, open '
        f'Recurring in Wizard.</p></td></tr>')
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{_e(title)}</title></head><body style="margin:0;padding:0;background:{PAGE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE}"><tr>'
        '<td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'style="width:600px;max-width:100%;background:#ffffff;border-collapse:collapse;font-family:{FONT};'
        f'font-size:14px;line-height:1.5;color:{INK}">' + "".join(rows) + "</table></td></tr></table></body></html>")


def sheet_names(brief) -> list[str]:
    """One Excel sheet per section: its title, made safe and unique within Excel's 31 characters."""
    names, seen = [], set()
    for index, section in enumerate(brief.get("sections") or []):
        base = re.sub(r"[\[\]:*?/\\']+", " ", section.get("title") or f"Section {index + 1}").strip()[:28] or \
            f"Section {index + 1}"
        name, attempt = base, 2
        while name.casefold() in seen:
            name, attempt = f"{base[:27]} {attempt}", attempt + 1
        seen.add(name.casefold())
        names.append(name)
    return names

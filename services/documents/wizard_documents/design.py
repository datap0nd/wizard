"""How a presentation looks, read for the company's presentation guide (owner, 1 Nov 2026: "digest these PowerPoints ...
create an MD of how to create PowerPoints ... appropriate for the company"): slide size, the theme's colors and fonts,
the master's text styles, the layouts and how often each is used, what recurs on every slide (logo, footer,
confidentiality label, page number), and per slide the fonts, sizes and colors actually used, fills, charts, tables
and pictures, with the deck's outline.

Two readers fill the same facts. PowerPoint itself, through COM, is the only way to open NASCA-protected decks and
reports the font each text really shows. The standard-library reader opens plain .pptx/.potx files without Office and
sees only formatting written on the slide, so the master's text styles stand for the rest. summarize() turns one deck's
facts into its profile; combine() counts what many decks share, which is what a guide is written from. Text is kept
only where the guide needs it (slide titles, recurring footer texts); the profile holds no slide body text."""
from __future__ import annotations

import contextlib
import statistics
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .common import ConversionError, mask_contacts
from .office import MSO_TRUE, PICTURES, OfficeSession, _get, _items, _text_of
from .ooxml import A, C, P, R, parse_xml, placeholder_type, relationships

EMU_PER_PT = 12700
SLOTS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink")
SLOT_NAMES = {"dk1": "dark 1", "lt1": "light 1", "dk2": "dark 2", "lt2": "light 2", "accent1": "accent 1",
              "accent2": "accent 2", "accent3": "accent 3", "accent4": "accent 4", "accent5": "accent 5",
              "accent6": "accent 6", "hlink": "hyperlink", "folHlink": "followed hyperlink"}
# Text colors often name the theme by role: tx1 is dark 1, bg1 light 1, and so on.
ALIASES = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}
# MsoThemeColorIndex (a run's ObjectThemeColor) to the theme slot.
COM_THEME = {1: "dk1", 2: "lt1", 3: "dk2", 4: "lt2", 5: "accent1", 6: "accent2", 7: "accent3", 8: "accent4",
             9: "accent5", 10: "accent6", 11: "hlink", 12: "folHlink", 13: "dk1", 14: "lt1", 15: "dk2", 16: "lt2"}
CHART_TAGS = {"barChart": "bar", "bar3DChart": "bar", "lineChart": "line", "line3DChart": "line", "pieChart": "pie",
              "pie3DChart": "pie", "doughnutChart": "doughnut", "areaChart": "area", "area3DChart": "area",
              "scatterChart": "scatter", "bubbleChart": "bubble", "radarChart": "radar", "stockChart": "stock",
              "ofPieChart": "pie", "surfaceChart": "surface"}
# XlChartType numbers PowerPoint reports, by family.
COM_CHARTS = {51: "column", 52: "column", 53: "column", 54: "column", 55: "column", 56: "column", 57: "bar", 58: "bar",
              59: "bar", 60: "bar", 61: "bar", 62: "bar", 4: "line", 63: "line", 64: "line", 65: "line", 66: "line",
              67: "line", 5: "pie", 69: "pie", 70: "pie", 68: "pie", 71: "pie", -4102: "pie", -4120: "doughnut",
              80: "doughnut", 1: "area", 76: "area", 77: "area", 78: "area", 79: "area", -4169: "scatter", 72: "scatter",
              73: "scatter", 74: "scatter", 75: "scatter", 15: "bubble", 87: "bubble", -4151: "radar", 81: "radar",
              82: "radar", 111: "waterfall", 121: "treemap", 120: "sunburst", 118: "histogram", 119: "pareto",
              113: "funnel", 112: "box and whisker"}
MAX_RUNS_PER_SLIDE = 80
OUTLINE = 60


@dataclass
class TextRun:
    role: str  # title | body
    chars: int
    font: str = ""
    size: float | None = None
    color: str = ""  # #RRGGBB
    bold: bool = False


@dataclass
class Element:
    """Something on the master or a layout, so on every slide that uses it: a picture (usually the logo), a footer,
    the slide number, the date, or a fixed text such as a confidentiality label."""
    kind: str
    where: str
    text: str = ""
    width_pct: int = 0


@dataclass
class SlideFacts:
    number: int
    layout: str
    title: str
    hidden: bool = False
    runs: list[TextRun] = field(default_factory=list)
    fills: list[str] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)
    tables: int = 0
    pictures: int = 0
    shapes: int = 0
    words: int = 0


@dataclass
class DesignFacts:
    method: str  # office | ooxml
    width_pt: float = 0.0
    height_pt: float = 0.0
    theme: str = ""
    colors: dict[str, str] = field(default_factory=dict)  # slot -> #RRGGBB
    fonts: dict[str, str] = field(default_factory=dict)   # heading / body, latin / east asian
    styles: dict[str, dict[str, Any]] = field(default_factory=dict)  # the master's title and body levels
    layouts: list[str] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    slides: list[SlideFacts] = field(default_factory=list)


def where(x: float, y: float, w: float, h: float, width: float, height: float) -> str:
    """'top right', 'bottom left', 'middle center' ... from a shape's centre on the slide."""
    if width <= 0 or height <= 0:
        return "unknown"
    cx, cy = (x + w / 2) / width, (y + h / 2) / height
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    column = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    return f"{row} {column}"


def hex_color(value: str) -> str:
    value = value.strip().lstrip("#").upper()
    return f"#{value}" if len(value) == 6 and all(c in "0123456789ABCDEF" for c in value) else ""


def bgr(value: Any) -> str:
    """A COM color (R + G*256 + B*65536) as #RRGGBB."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number < 0 or number > 0xFFFFFF:
        return ""
    return f"#{number & 0xFF:02X}{(number >> 8) & 0xFF:02X}{(number >> 16) & 0xFF:02X}"


def _short(text: str, limit: int = 120) -> str:
    return mask_contacts(" ".join(text.split()))[:limit]


# --- Without Office: the file's own XML --------------------------------------------------------------------------------


def _xfrm(element: ET.Element) -> tuple[float, float, float, float] | None:
    off = element.find(f".//{A}xfrm/{A}off")
    ext = element.find(f".//{A}xfrm/{A}ext")
    if off is None or ext is None:
        return None
    try:
        return (int(off.get("x", "0")) / EMU_PER_PT, int(off.get("y", "0")) / EMU_PER_PT,
                int(ext.get("cx", "0")) / EMU_PER_PT, int(ext.get("cy", "0")) / EMU_PER_PT)
    except ValueError:
        return None


def _fill(element: ET.Element | None, colors: dict[str, str]) -> str:
    """The color of a solidFill (srgbClr, sysClr or a theme slot)."""
    if element is None:
        return ""
    solid = element.find(f"{A}solidFill")
    if solid is None:
        return ""
    for child in solid:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "srgbClr":
            return hex_color(child.get("val", ""))
        if tag == "sysClr":
            return hex_color(child.get("lastClr", ""))
        if tag == "schemeClr":
            slot = child.get("val", "")
            return colors.get(ALIASES.get(slot, slot), "")
    return ""


def _typeface(properties: ET.Element | None, fonts: dict[str, str]) -> str:
    latin = properties.find(f"{A}latin") if properties is not None else None
    face = latin.get("typeface", "") if latin is not None else ""
    return {"+mj-lt": fonts.get("heading", ""), "+mn-lt": fonts.get("body", "")}.get(face, face)


def _size(properties: ET.Element | None) -> float | None:
    try:
        return int(properties.get("sz", "")) / 100 if properties is not None and properties.get("sz") else None
    except ValueError:
        return None


def _theme(archive: zipfile.ZipFile, master: str, facts: DesignFacts) -> None:
    theme = next((t for kind, t in relationships(archive, master).values() if kind == "theme"), None)
    if not theme or theme not in archive.namelist():
        return
    root = parse_xml(archive.read(theme))
    facts.theme = root.get("name", "")
    scheme = root.find(f"{A}themeElements/{A}clrScheme")
    for slot in SLOTS:
        holder = scheme.find(f"{A}{slot}") if scheme is not None else None
        if holder is not None and len(holder):
            child = holder[0]
            facts.colors[slot] = hex_color(child.get("val", "") if child.tag.endswith("srgbClr") else child.get("lastClr", ""))
    for kind, key in (("majorFont", "heading"), ("minorFont", "body")):
        scheme_font = root.find(f"{A}themeElements/{A}fontScheme/{A}{kind}")
        if scheme_font is None:
            continue
        for script, suffix in (("latin", ""), ("ea", " (East Asian)")):
            face = scheme_font.find(f"{A}{script}")
            if face is not None and face.get("typeface"):
                facts.fonts[key + suffix] = face.get("typeface", "")


def _master_styles(root: ET.Element, facts: DesignFacts) -> None:
    for name, path in (("title", f"{P}txStyles/{P}titleStyle/{A}lvl1pPr"), ("body level 1", f"{P}txStyles/{P}bodyStyle/{A}lvl1pPr"),
                       ("body level 2", f"{P}txStyles/{P}bodyStyle/{A}lvl2pPr"), ("body level 3", f"{P}txStyles/{P}bodyStyle/{A}lvl3pPr")):
        level = root.find(path)
        properties = level.find(f"{A}defRPr") if level is not None else None
        if properties is None:
            continue
        facts.styles[name] = {"font": _typeface(properties, facts.fonts) or facts.fonts.get("heading" if name == "title" else "body", ""),
                              "size": _size(properties), "color": _fill(properties, facts.colors),
                              "bold": properties.get("b") == "1"}


def _elements(root: ET.Element, facts: DesignFacts) -> list[Element]:
    """Pictures, footers, slide numbers, dates and fixed texts drawn on a master or layout."""
    found: list[Element] = []
    tree = root.find(f"{P}cSld/{P}spTree")
    for element in list(tree) if tree is not None else []:
        box = _xfrm(element)
        spot = where(*box, facts.width_pt, facts.height_pt) if box else "unknown"
        width_pct = round(100 * box[2] / facts.width_pt) if box and facts.width_pt else 0
        if element.tag == f"{P}pic":
            found.append(Element("picture", spot, width_pct=width_pct))
        elif element.tag == f"{P}sp":
            kind = placeholder_type(element)
            text = _short(" ".join(t.text or "" for t in element.iter(f"{A}t")))
            if kind in ("sldNum", "ftr", "dt"):
                found.append(Element({"sldNum": "slide number", "ftr": "footer", "dt": "date"}[kind], spot,
                                     "" if kind == "sldNum" else text, width_pct))
            elif not kind and text:
                found.append(Element("text", spot, text, width_pct))
    return found


def _runs(shape: ET.Element, role: str, facts: DesignFacts) -> list[TextRun]:
    runs = []
    for run in shape.iter(f"{A}r"):
        text = "".join(t.text or "" for t in run.iter(f"{A}t"))
        if not text.strip():
            continue
        properties = run.find(f"{A}rPr")
        runs.append(TextRun(role, len(text), _typeface(properties, facts.fonts), _size(properties),
                            _fill(properties, facts.colors), properties is not None and properties.get("b") == "1"))
    return runs


def ooxml_facts(path: Path) -> DesignFacts:
    try:
        with zipfile.ZipFile(path) as archive:
            return _ooxml(archive)
    except zipfile.BadZipFile:
        raise ConversionError("not a plain Office file (protected, for example by NASCA, or damaged): its design is "
                              "read through PowerPoint") from None
    except (KeyError, ET.ParseError) as error:
        raise ConversionError(f"damaged Office file ({type(error).__name__}: {error})") from None


def _ooxml(archive: zipfile.ZipFile) -> DesignFacts:
    facts = DesignFacts("ooxml")
    presentation = parse_xml(archive.read("ppt/presentation.xml"))
    size = presentation.find(f"{P}sldSz")
    if size is not None:
        facts.width_pt = int(size.get("cx", "0")) / EMU_PER_PT
        facts.height_pt = int(size.get("cy", "0")) / EMU_PER_PT
    rels = relationships(archive, "ppt/presentation.xml")
    names = set(archive.namelist())
    masters = [target for kind, target in rels.values() if kind == "slideMaster" and target in names]
    layout_names: dict[str, str] = {}
    for number, master in enumerate(sorted(masters)):
        root = parse_xml(archive.read(master))
        if number == 0:
            _theme(archive, master, facts)
            _master_styles(root, facts)
        facts.elements += _elements(root, facts)
        for kind, layout in relationships(archive, master).values():
            if kind != "slideLayout" or layout not in names:
                continue
            layout_root = parse_xml(archive.read(layout))
            common = layout_root.find(f"{P}cSld")
            name = (common.get("name", "") if common is not None else "") or Path(layout).stem
            layout_names[layout] = name
            facts.layouts.append(name)
            facts.elements += _elements(layout_root, facts)
    slide_list = presentation.find(f"{P}sldIdLst")
    slides = [rels[s.get(f"{R}id", "")][1] for s in (slide_list if slide_list is not None else []) if s.get(f"{R}id", "") in rels]
    for number, part in enumerate(slides, start=1):
        if part not in names:
            continue
        root = parse_xml(archive.read(part))
        slide_rels = relationships(archive, part)
        layout = next((layout_names.get(t, Path(t).stem) for kind, t in slide_rels.values() if kind == "slideLayout"), "")
        slide = SlideFacts(number, layout, "", hidden=root.get("show") == "0")
        tree = root.find(f"{P}cSld/{P}spTree")
        for element in tree.iter() if tree is not None else []:
            if element.tag == f"{P}sp":
                slide.shapes += 1
                role = "title" if placeholder_type(element) in ("title", "ctrTitle") else "body"
                if role == "title" and not slide.title:
                    slide.title = _short(" ".join(t.text or "" for t in element.iter(f"{A}t")))
                slide.runs += _runs(element, role, facts)
                color = _fill(element.find(f"{P}spPr"), facts.colors)
                if color:
                    slide.fills.append(color)
            elif element.tag == f"{P}pic":
                slide.shapes += 1
                slide.pictures += 1
            elif element.tag == f"{A}tbl":
                slide.tables += 1
            elif element.tag == f"{P}graphicFrame":
                slide.shapes += 1
        slide.words = sum(len((t.text or "").split()) for t in root.iter(f"{A}t"))
        slide.runs = slide.runs[:MAX_RUNS_PER_SLIDE]
        for kind, target in slide_rels.values():
            if kind == "chart" and target in names:
                area = parse_xml(archive.read(target)).find(f"{C}chart/{C}plotArea")
                for child in list(area) if area is not None else []:
                    family = CHART_TAGS.get(child.tag.rsplit("}", 1)[-1])
                    if family == "bar":
                        direction = child.find(f"{C}barDir")
                        family = "column" if direction is not None and direction.get("val") == "col" else "bar"
                    if family:
                        slide.charts.append(family)
        facts.slides.append(slide)
    return facts


# --- Through PowerPoint (protected decks) ------------------------------------------------------------------------------


def _com_font(font: Any, colors: dict[str, str]) -> dict[str, Any]:
    color = _get(font, "Color")
    theme = COM_THEME.get(int(_get(color, "ObjectThemeColor", 0) or 0))
    size = _get(font, "Size")
    return {"font": str(_get(font, "Name", "") or ""), "size": float(size) if isinstance(size, int | float) and size > 0 else None,
            "color": colors.get(theme, "") if theme else bgr(_get(color, "RGB")), "bold": _get(font, "Bold") == MSO_TRUE}


def _com_elements(shapes: Any, facts: DesignFacts) -> list[Element]:
    found = []
    for shape in _items(shapes):
        kind = int(_get(shape, "Type", 0) or 0)
        left, top, width, height = (float(_get(shape, name, 0) or 0) for name in ("Left", "Top", "Width", "Height"))
        spot = where(left, top, width, height, facts.width_pt, facts.height_pt)
        width_pct = round(100 * width / facts.width_pt) if facts.width_pt else 0
        placeholder = int(_get(_get(shape, "PlaceholderFormat"), "Type", 0) or 0) if kind == 14 else 0
        if kind in PICTURES:
            found.append(Element("picture", spot, width_pct=width_pct))
        elif placeholder in (13, 15, 16):  # ppPlaceholderSlideNumber, Footer, Date
            text = "" if placeholder == 13 else _short(_text_of(shape))
            found.append(Element({13: "slide number", 15: "footer", 16: "date"}[placeholder], spot, text, width_pct))
        elif kind != 14 and _get(shape, "HasTextFrame") == MSO_TRUE:
            text = _short(_text_of(shape))
            if text:
                found.append(Element("text", spot, text, width_pct))
    return found


def _com_shape(shape: Any, slide: SlideFacts, facts: DesignFacts, depth: int = 0) -> None:
    if depth > 8:
        return
    kind = int(_get(shape, "Type", 0) or 0)
    if kind == 6:  # msoGroup
        for item in _items(_get(shape, "GroupItems")):
            _com_shape(item, slide, facts, depth + 1)
        return
    slide.shapes += 1
    if _get(shape, "HasChart") == MSO_TRUE:
        number = int(_get(_get(shape, "Chart"), "ChartType", 0) or 0)
        slide.charts.append(COM_CHARTS.get(number, f"type {number}"))
        return
    if _get(shape, "HasTable") == MSO_TRUE:
        slide.tables += 1
        return
    contained = int(_get(_get(shape, "PlaceholderFormat"), "ContainedType", 0) or 0) if kind == 14 else 0
    if kind in PICTURES or contained in PICTURES:
        slide.pictures += 1
        return
    fill = _get(shape, "Fill")
    if kind == 1 and _get(fill, "Visible") == MSO_TRUE:  # msoAutoShape with a fill
        color = _get(fill, "ForeColor")
        theme = COM_THEME.get(int(_get(color, "ObjectThemeColor", 0) or 0))
        value = facts.colors.get(theme, "") if theme else bgr(_get(color, "RGB"))
        if value:
            slide.fills.append(value)
    if _get(shape, "HasTextFrame") != MSO_TRUE or _get(_get(shape, "TextFrame"), "HasText") != MSO_TRUE:
        return
    placeholder = int(_get(_get(shape, "PlaceholderFormat"), "Type", 0) or 0) if kind == 14 else 0
    role = "title" if placeholder in (1, 3) else "body"  # ppPlaceholderTitle, ppPlaceholderCenterTitle
    text_range = shape.TextFrame.TextRange
    slide.words += len(str(_get(text_range, "Text", "") or "").split())
    for run in _items(_get(text_range, "Runs")):
        if len(slide.runs) >= MAX_RUNS_PER_SLIDE:
            return
        text = str(_get(run, "Text", "") or "")
        if text.strip():
            font = _com_font(_get(run, "Font"), facts.colors)
            slide.runs.append(TextRun(role, len(text), font["font"], font["size"], font["color"], font["bold"]))


def office_facts(session: OfficeSession, path: Path) -> DesignFacts:
    application = session.app("powerpoint")
    try:
        presentation = application.Presentations.Open(str(path), ReadOnly=True, Untitled=False, WithWindow=False)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    facts = DesignFacts("office")
    try:
        facts.width_pt = float(presentation.PageSetup.SlideWidth)
        facts.height_pt = float(presentation.PageSetup.SlideHeight)
        master = presentation.SlideMaster
        theme = _get(master, "Theme")
        scheme = _get(theme, "ThemeColorScheme")
        for index, slot in enumerate(SLOTS, start=1):
            with contextlib.suppress(Exception):
                facts.colors[slot] = bgr(scheme.Colors(index).RGB)
        font_scheme = _get(theme, "ThemeFontScheme")
        for kind, key in (("MajorFont", "heading"), ("MinorFont", "body")):
            for index, suffix in ((1, ""), (3, " (East Asian)")):  # msoThemeLatin, msoThemeEastAsian
                with contextlib.suppress(Exception):
                    name = str(getattr(font_scheme, kind).Item(index).Name or "")
                    if name:
                        facts.fonts[key + suffix] = name
        facts.theme = str(_get(_get(master, "Design"), "Name", "") or _get(master, "Name", "") or "")
        for name, style, level in (("title", 2, 1), ("body level 1", 3, 1), ("body level 2", 3, 2), ("body level 3", 3, 3)):
            with contextlib.suppress(Exception):
                facts.styles[name] = _com_font(master.TextStyles(style).Levels(level).Font, facts.colors)
        facts.elements += _com_elements(_get(master, "Shapes"), facts)
        for design in _items(_get(presentation, "Designs")):
            for layout in _items(_get(_get(design, "SlideMaster"), "CustomLayouts")):
                facts.layouts.append(str(_get(layout, "Name", "") or ""))
                facts.elements += _com_elements(_get(layout, "Shapes"), facts)
        for slide_object in _items(presentation.Slides):
            shapes = slide_object.Shapes
            title = _short(_text_of(shapes.Title)) if _get(shapes, "HasTitle") == MSO_TRUE else ""
            slide = SlideFacts(int(slide_object.SlideIndex), str(_get(_get(slide_object, "CustomLayout"), "Name", "") or ""),
                               title, hidden=_get(_get(slide_object, "SlideShowTransition"), "Hidden") == MSO_TRUE)
            for shape in _items(shapes):
                _com_shape(shape, slide, facts)
            facts.slides.append(slide)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    finally:
        with contextlib.suppress(Exception):
            presentation.Close()
    return facts


# --- Profiles ----------------------------------------------------------------------------------------------------------


def _theme_name(color: str, colors: dict[str, str]) -> str:
    return next((SLOT_NAMES[slot] for slot in SLOTS if colors.get(slot) == color), "")


def _shares(counter: Counter[Any], total: int, key: str, limit: int, colors: dict[str, str] | None = None) -> list[dict[str, Any]]:
    out = []
    for value, count in counter.most_common(limit):
        item: dict[str, Any] = {key: value, "share_pct": round(100 * count / total) if total else 0}
        if colors is not None and _theme_name(value, colors):
            item["theme"] = _theme_name(value, colors)
        out.append(item)
    return out


def _aspect(width: float, height: float) -> str:
    if not width or not height:
        return "unknown"
    ratio = width / height
    return next((name for name, value in (("16:9", 16 / 9), ("4:3", 4 / 3), ("16:10", 1.6), ("A4", 297 / 210)) if abs(ratio - value) < 0.02),
                f"{ratio:.2f}:1")


def summarize(facts: DesignFacts) -> dict[str, Any]:
    """One deck's design profile: what a person writing the company's presentation guide needs to see."""
    runs = [r for s in facts.slides if not s.hidden for r in s.runs]
    visible = [s for s in facts.slides if not s.hidden]
    chars = sum(r.chars for r in runs) or 1
    fonts: Counter[str] = Counter()
    colors: Counter[str] = Counter()
    title_sizes: Counter[float] = Counter()
    body_sizes: Counter[float] = Counter()
    for run in runs:
        if run.font:
            fonts[run.font] += run.chars
        if run.color:
            colors[run.color] += run.chars
        if run.size:
            (title_sizes if run.role == "title" else body_sizes)[run.size] += run.chars
    fills = Counter(color for s in visible for color in s.fills)
    elements: Counter[tuple[str, str, str]] = Counter((e.kind, e.where, e.text) for e in facts.elements)
    layouts_used = Counter(s.layout or "(unnamed)" for s in visible)
    charts = Counter(c for s in visible for c in s.charts)
    words = [s.words for s in visible]
    profile: dict[str, Any] = {
        "read_with": "PowerPoint (the fonts and colors each text really shows)" if facts.method == "office" else
                     "the file itself, without PowerPoint (only formatting written on the slides; the master's text styles stand for the rest)",
        "slide_size": {"width_cm": round(facts.width_pt / 72 * 2.54, 2), "height_cm": round(facts.height_pt / 72 * 2.54, 2),
                       "aspect": _aspect(facts.width_pt, facts.height_pt)},
        "theme": {"name": facts.theme, "colors": {SLOT_NAMES[k]: v for k, v in facts.colors.items() if v}, "fonts": facts.fonts},
        "master_text_styles": facts.styles,
        "layouts_in_template": list(dict.fromkeys(n for n in facts.layouts if n))[:60],
        "layouts_used": [{"layout": name, "slides": count} for name, count in layouts_used.most_common(25)],
        "on_every_slide": [{"kind": kind, "where": spot, **({"text": text} if text else {}), "masters_and_layouts": count}
                           for (kind, spot, text), count in elements.most_common(20)],
        "slides": len(facts.slides), "hidden_slides": len(facts.slides) - len(visible),
        "text": {"fonts": _shares(fonts, chars, "font", 6), "colors": _shares(colors, chars, "color", 8, facts.colors),
                 "title_sizes_pt": _shares(title_sizes, sum(title_sizes.values()), "pt", 5),
                 "body_sizes_pt": _shares(body_sizes, sum(body_sizes.values()), "pt", 6),
                 "bold_pct": round(100 * sum(r.chars for r in runs if r.bold) / chars)},
        "shape_fills": [{"color": c, **({"theme": _theme_name(c, facts.colors)} if _theme_name(c, facts.colors) else {}), "shapes": n}
                        for c, n in fills.most_common(8)],
        "charts": dict(charts.most_common()), "slides_with_chart": sum(1 for s in visible if s.charts),
        "slides_with_table": sum(1 for s in visible if s.tables), "slides_with_picture": sum(1 for s in visible if s.pictures),
        "words_per_slide": {"median": statistics.median(words) if words else 0, "max": max(words, default=0)},
        "shapes_per_slide": statistics.median([s.shapes for s in visible]) if visible else 0,
        "outline": [f"{s.number}. [{s.layout or '?'}] {s.title or '(no title)'}" + (" (hidden)" if s.hidden else "")
                    for s in facts.slides[:OUTLINE]],
    }
    if len(facts.slides) > OUTLINE:
        profile["outline"].append(f"... {len(facts.slides) - OUTLINE} more slides")
    return profile


def combine(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """What the decks share, each value counted once per deck: the consistent parts are the company's style; the rest
    is one team's or one person's choice."""
    def tally(values: list[list[Any]]) -> Counter[Any]:
        return Counter(v for deck in values for v in dict.fromkeys(deck))

    def ranked(counter: Counter[Any], key: str, limit: int) -> list[dict[str, Any]]:
        return [{key: value, "decks": count} for value, count in counter.most_common(limit)]

    decks = [p for p in profiles if p]
    theme_colors = tally([[f"{v} ({k})" for k, v in p["theme"]["colors"].items()] for p in decks])
    theme_fonts = tally([[" / ".join(f"{k}: {v}" for k, v in sorted(p["theme"]["fonts"].items()))] for p in decks if p["theme"]["fonts"]])
    title_styles = tally([[" ".join(str(x) for x in (s.get("font"), s.get("size") and f"{s['size']:g} pt", s.get("color"),
                                                         "bold" if s.get("bold") else "") if x)]
                          for p in decks for name, s in p["master_text_styles"].items() if name == "title"])
    every = tally([[f"{e['kind']} {e['where']}" + (f": {e['text']}" if e.get("text") else "") for e in p["on_every_slide"]] for p in decks])
    layouts = tally([[item["layout"] for item in p["layouts_used"]] for p in decks])
    slides_per_layout: Counter[str] = Counter()
    for p in decks:
        for item in p["layouts_used"]:
            slides_per_layout[item["layout"]] += item["slides"]
    charts: Counter[str] = Counter()
    for p in decks:
        charts.update(p["charts"])
    return {
        "decks": len(decks),
        "slide_sizes": ranked(tally([[f"{p['slide_size']['width_cm']} x {p['slide_size']['height_cm']} cm ({p['slide_size']['aspect']})"] for p in decks]), "size", 5),
        "theme_names": ranked(tally([[p["theme"]["name"]] for p in decks if p["theme"]["name"]]), "theme", 8),
        "theme_colors": ranked(theme_colors, "color", 24),
        "theme_fonts": ranked(theme_fonts, "fonts", 6),
        "master_title_styles": ranked(title_styles, "style", 6),
        "fonts_used": ranked(tally([[f["font"] for f in p["text"]["fonts"]] for p in decks]), "font", 10),
        "text_colors": ranked(tally([[c["color"] + (f" ({c['theme']})" if c.get("theme") else "") for c in p["text"]["colors"]] for p in decks]), "color", 12),
        "title_sizes_pt": ranked(tally([[s["pt"] for s in p["text"]["title_sizes_pt"][:2]] for p in decks]), "pt", 6),
        "body_sizes_pt": ranked(tally([[s["pt"] for s in p["text"]["body_sizes_pt"][:3]] for p in decks]), "pt", 8),
        "shape_fills": ranked(tally([[f["color"] + (f" ({f['theme']})" if f.get("theme") else "") for f in p["shape_fills"]] for p in decks]), "color", 12),
        "on_every_slide": ranked(every, "element", 15),
        "layouts": [{"layout": name, "decks": count, "slides": slides_per_layout[name]} for name, count in layouts.most_common(25)],
        "charts": dict(charts.most_common()),
        "slides_per_deck": {"median": statistics.median([p["slides"] for p in decks]) if decks else 0,
                            "max": max((p["slides"] for p in decks), default=0)},
        "median_words_per_slide": statistics.median([p["words_per_slide"]["median"] for p in decks]) if decks else 0,
        "share_of_slides_with": {kind: round(100 * sum(p[f"slides_with_{kind}"] for p in decks)
                                             / max(sum(p["slides"] - p["hidden_slides"] for p in decks), 1))
                                 for kind in ("chart", "table", "picture")},
    }


def profile(path: Path, session: OfficeSession | None) -> dict[str, Any]:
    """PowerPoint when it runs here (it opens protected decks), else the file itself; a plain file PowerPoint could not
    open is read without it."""
    suffix = path.suffix.lower()
    if suffix not in (".pptx", ".pptm", ".ppsx", ".potx", ".ppt", ".pps", ".pot", ".potm"):
        raise ConversionError(f"{suffix or 'this file'} is not a presentation")
    if session is not None:
        try:
            return summarize(office_facts(session, path))
        except ConversionError:
            if suffix not in (".pptx", ".pptm", ".ppsx", ".potx", ".potm"):
                raise
    elif suffix in (".ppt", ".pps", ".pot"):
        raise ConversionError(f"{suffix} files need PowerPoint, which is not available here")
    return summarize(ooxml_facts(path))

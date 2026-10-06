"""Read Office Open XML files (docx, pptx, xlsx) with the standard library: the fallback when Office automation is not
available (CI, Linux, a PC without Office) and a check that the Office reader is not required for plain files.

It cannot open NASCA/DRM-protected files (they are not ZIP archives), legacy binary formats, or render slide images;
the Office reader does all three."""
from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .common import ConversionError, Converted, chart_block, markdown_table
from .sheets import Sheet, render
from .tables import MAX_TABLE_ROWS, build

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_SHEET_ROWS = 1000


def parse_xml(data: bytes) -> ET.Element:
    """Parse one part of an Office file. Office parts never declare a DOCTYPE, so refusing one rules out entity
    expansion attacks; expat never fetches external entities."""
    if b"<!DOCTYPE" in data[:4096].upper():
        raise ConversionError("unexpected DOCTYPE in an Office file part")
    return ET.fromstring(data)  # noqa: S314 - DOCTYPE refused above


def relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """rId -> (relationship type suffix, absolute part name) for one part."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels_name not in archive.namelist():
        return {}
    out = {}
    for rel in parse_xml(archive.read(rels_name)).iter(f"{REL}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], resolved)
    return out


# --- Word ------------------------------------------------------------------------------------------------------------


def word_paragraph(paragraph: ET.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{W}tab":
            parts.append("\t")
        elif node.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    text = "".join(parts).strip()
    if not text:
        return ""
    style = paragraph.find(f"{W}pPr/{W}pStyle")
    value = (style.get(f"{W}val") or "") if style is not None else ""
    level = re.match(r"(?i)^(heading|titre|überschrift|título|titulo)\s*([1-6])$", value)
    if level:
        return f"{'#' * int(level.group(2))} {text}"
    if value.lower() == "title":
        return f"# {text}"
    if paragraph.find(f"{W}pPr/{W}numPr") is not None:
        return f"- {text}"
    return text


def word_blocks(container: ET.Element) -> list[str]:
    out: list[str] = []
    for block in container:
        if block.tag == f"{W}p":
            out.append(word_paragraph(block))
        elif block.tag == f"{W}tbl":
            rows = [[" ".join(word_paragraph(p) for p in c.iter(f"{W}p")).strip() for c in row.findall(f"{W}tc")]
                    for row in block.findall(f"{W}tr")]
            out.append(markdown_table(rows))
        elif block.tag == f"{W}sdt":
            content = block.find(f"{W}sdtContent")
            if content is not None:
                out += word_blocks(content)
    return out


def read_docx(archive: zipfile.ZipFile) -> Converted:
    body = parse_xml(archive.read("word/document.xml")).find(f"{W}body")
    blocks = [b for b in word_blocks(body) if b] if body is not None else []
    return Converted("\n\n".join(blocks), "ooxml", parts=[b.lstrip("# ") for b in blocks if b.startswith("#")][:60])


# --- PowerPoint ------------------------------------------------------------------------------------------------------


def drawing_paragraphs(element: ET.Element) -> list[str]:
    lines = []
    for paragraph in element.iter(f"{A}p"):
        text = "".join(t.text or "" for t in paragraph.iter(f"{A}t")).strip()
        if text:
            properties = paragraph.find(f"{A}pPr")
            level = int(properties.get("lvl", "0")) if properties is not None else 0
            lines.append(f"{'  ' * level}- {text}")
    return lines


def placeholder_type(shape: ET.Element) -> str:
    placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
    return placeholder.get("type", "body") if placeholder is not None else ""


def chart_text(chart: ET.Element) -> str:
    """Title, series names, categories and cached values of one chart part."""
    title_el = chart.find(f"{C}chart/{C}title")
    title = " ".join(t.text or "" for t in title_el.iter(f"{A}t")).strip() if title_el is not None else ""
    series: list[tuple[str, list[str], list[str]]] = []
    for ser in chart.iter(f"{C}ser"):
        found = {tag: ser.find(f"{C}{tag}") for tag in ("tx", "cat", "val")}
        points = {tag: [v.text or "" for v in el.iter(f"{C}v")] if el is not None else [] for tag, el in found.items()}
        series.append((" ".join(points["tx"]).strip() or f"Series {len(series) + 1}", points["cat"], points["val"]))
    return chart_block(title, series)


def read_pptx(archive: zipfile.ZipFile) -> Converted:
    presentation = parse_xml(archive.read("ppt/presentation.xml"))
    rels = relationships(archive, "ppt/presentation.xml")
    slide_list = presentation.find(f"{P}sldIdLst")
    slides = [rels[s.get(f"{R}id", "")][1] for s in (slide_list if slide_list is not None else [])
              if s.get(f"{R}id", "") in rels]
    names = set(archive.namelist())
    out, parts = [], []
    for number, part in enumerate(slides, start=1):
        root = parse_xml(archive.read(part))
        tree = root.find(f"{P}cSld/{P}spTree")
        title, lines = "", []
        for element in tree.iter() if tree is not None else []:
            if element.tag == f"{P}sp":
                if placeholder_type(element) in ("title", "ctrTitle") and not title:
                    title = " ".join(t.text or "" for t in element.iter(f"{A}t")).strip()
                    continue
                lines += drawing_paragraphs(element)
            elif element.tag == f"{A}tbl":
                rows = [[" ".join((t.text or "") for t in c.iter(f"{A}t")).strip() for c in row.findall(f"{A}tc")]
                        for row in element.findall(f"{A}tr")]
                lines.append(markdown_table(rows))
            elif element.tag == f"{P}pic":
                described = element.find(f"{P}nvPicPr/{P}cNvPr")
                alt = (described.get("descr") or "").strip() if described is not None else ""
                lines.append(f"Picture: {alt}" if alt else "Picture (no description; open the slide image if it matters)")
        slide_rels = relationships(archive, part)
        for kind, target in slide_rels.values():
            if target not in names:
                continue
            if kind == "diagramData":
                nodes = [t.text.strip() for t in parse_xml(archive.read(target)).iter(f"{A}t") if t.text and t.text.strip()]
                if nodes:
                    lines.append("Diagram: " + " -> ".join(nodes))
            elif kind == "chart":
                lines.append(chart_text(parse_xml(archive.read(target))))
        notes = next((target for kind, target in slide_rels.values() if kind == "notesSlide"), None)
        note_lines: list[str] = []
        if notes and notes in names:
            for shape in parse_xml(archive.read(notes)).iter(f"{P}sp"):
                if placeholder_type(shape) == "body":
                    note_lines += drawing_paragraphs(shape)
        hidden = " (hidden slide)" if root.get("show") == "0" else ""
        heading = f"Slide {number}" + (f": {title}" if title else "")
        parts.append(heading)
        block = [f"## {heading}{hidden}", *lines]
        if note_lines:
            block += ["Speaker notes:", *note_lines]
        out.append("\n".join(block))
    return Converted("\n\n".join(out), "ooxml", parts=parts,
                     notes=["Read without Office: slide images were not produced."] if out else [])


# --- Excel -----------------------------------------------------------------------------------------------------------


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "A")
    index = 0
    for char in letters.group(0) if letters else "A":
        index = index * 26 + ord(char) - 64
    return index - 1


def read_xlsx(archive: zipfile.ZipFile, max_rows: int = MAX_SHEET_ROWS, tables: bool = False) -> Converted:
    names = set(archive.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in parse_xml(archive.read("xl/sharedStrings.xml")).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in item.iter(f"{S}t")))
    workbook = parse_xml(archive.read("xl/workbook.xml"))
    rels = relationships(archive, "xl/workbook.xml")
    out: list[str] = []
    parts: list[str] = []
    built: list[Any] = []
    keep = MAX_TABLE_ROWS if tables else max_rows  # tables keep every row; the text shows the first max_rows
    for sheet_el in workbook.iter(f"{S}sheet"):
        name = sheet_el.get("name", "Sheet")
        target = rels.get(sheet_el.get(f"{R}id", ""), ("", ""))[1]
        if target not in names:
            continue
        values: list[list[object]] = []
        formulas: list[list[str]] = []
        total, width = 0, 0
        for row in parse_xml(archive.read(target)).iter(f"{S}row"):
            total += 1
            if len(values) >= keep:
                continue
            row_values: list[object] = []
            row_formulas: list[str] = []
            for c in row.findall(f"{S}c"):
                index = column_index(c.get("r", ""))
                if index >= 60:
                    continue
                kind, value, formula = c.get("t", "n"), c.find(f"{S}v"), c.find(f"{S}f")
                text = value.text if value is not None else None
                content: object
                if kind == "s" and text and text.isdigit() and int(text) < len(shared):
                    content = shared[int(text)]
                elif kind == "inlineStr":
                    content = "".join(t.text or "" for t in c.iter(f"{S}t"))
                elif kind == "b":
                    content = text == "1"
                elif kind in ("str", "e"):
                    content = text or ""
                else:
                    try:
                        content = float(text) if text not in (None, "") else None
                    except ValueError:
                        content = text
                pad = index - len(row_values)
                row_values += [None] * pad + [content]
                row_formulas += [""] * pad + [f"={formula.text}" if formula is not None and formula.text else ""]
            width = max(width, len(row_values))
            values.append(row_values)
            formulas.append(row_formulas)
        hidden = sheet_el.get("state", "visible") != "visible"
        parts.append(f"Sheet: {name}")
        out.append(render(Sheet(name, values[:max_rows], formulas[:max_rows], hidden=hidden, total_rows=total,
                                total_columns=width)))
        if tables:
            table = build(name, values, total)
            if table is not None:
                built.append(table)
    return Converted("\n\n".join(out), "ooxml", parts=parts, tables=built,
                     notes=["Read without Office: pivot tables and charts were not described."] if out else [])


def read(path: Path, max_rows: int = MAX_SHEET_ROWS, tables: bool = False) -> Converted:
    try:
        with zipfile.ZipFile(path) as archive:
            suffix = path.suffix.lower()
            if suffix in (".docx", ".docm", ".dotx"):
                return read_docx(archive)
            if suffix in (".pptx", ".pptm", ".ppsx", ".potx"):
                return read_pptx(archive)
            return read_xlsx(archive, max_rows, tables)
    except zipfile.BadZipFile:
        raise ConversionError("not a plain Office file (protected, for example by NASCA, or damaged): it needs the "
                              "Office applications") from None
    except (KeyError, ET.ParseError) as error:
        raise ConversionError(f"damaged Office file ({type(error).__name__}: {error})") from None

"""Read Office files and Outlook mail through the installed Office applications (pywin32 COM), in the user's own
Windows session.

Why Office and not a parser: NASCA/DRM-protected files open only in Office for the signed-in user, legacy .doc/.ppt/.xls
and Outlook .msg have no standard-library reader, and only PowerPoint can render a slide as a picture.

Rules learned on the work PC (data_governance, September 2026):
- Borrow a running application (GetActiveObject) before starting one: a fresh DispatchEx Excel can wait forever inside
  the NASCA protection provider while the user's own Excel is healthy.
- Open the original file where it is. NASCA binds access to the downloaded path, so a renamed or copied file may not
  open. Never SaveAs to "decrypt"; read the content through the object model.
- Read-only, macros forced off, alerts off. Leave Excel's EnableEvents alone (the protection provider may need it).
  Restore every setting changed on a borrowed application; quit only what this session started, and only when it has
  nothing else open.
Each OfficeSession lives on one thread, between CoInitialize and CoUninitialize."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import os
import re
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import ConversionError, Converted, chart_block, markdown_table, safe_name, tidy, unique
from .emails import email_header
from .sheets import Sheet, render, show
from .tables import MAX_TABLE_ROWS, build

PROGIDS = {"word": "Word.Application", "powerpoint": "PowerPoint.Application", "excel": "Excel.Application",
           "outlook": "Outlook.Application"}
MSO_TRUE = -1
# Shape types that carry an image Gemini can only understand by looking at it (msoEmbeddedOLEObject, msoLinkedOLEObject,
# msoLinkedPicture, msoPicture, msoMedia, msoWebVideo, msoGraphic, msoLinkedGraphic, mso3DModel).
PICTURES = {7, 10, 11, 13, 16, 26, 28, 29, 30}
SLIDE_IMAGE_WIDTH = 1600
EXCEL_READ_ROWS = 1000
EXCEL_READ_COLUMNS = 60
OL_MAIL = 43
DEFAULT_NAMES = re.compile(r"(?i)^(picture|image|graphic|grafik|imagem|imagen|immagine|content placeholder)\s*\d*$")

_loaded: tuple[Any, Any, Any] | None = None


class OfficeUnavailable(ConversionError):
    """pywin32 or the Office application is missing or blocked on this PC."""


def _portable_paths() -> None:
    """Portable installs unpack wheels into <release>/vendor without running pywin32's .pth file (the embeddable Python
    does not import site), so add its folders and DLL directory by hand."""
    for entry in list(sys.path):
        base = Path(entry)
        system32 = base / "pywin32_system32"
        if not system32.is_dir():
            continue
        for sub in ("win32", os.path.join("win32", "lib"), "pythonwin"):
            folder = base / sub
            if folder.is_dir() and str(folder) not in sys.path:
                sys.path.append(str(folder))
        if sys.platform == "win32":  # Windows-only API (also keeps mypy on Linux CI satisfied)
            with contextlib.suppress(OSError):
                os.add_dll_directory(str(system32))
        os.environ["PATH"] = f"{system32}{os.pathsep}{os.environ.get('PATH', '')}"
        return


def load_pywin32() -> tuple[Any, Any, Any]:
    """(pythoncom, pywintypes, win32com.client), or OfficeUnavailable with a reason a person can act on."""
    global _loaded
    if _loaded is not None:
        return _loaded
    if sys.platform != "win32":
        raise OfficeUnavailable("Office automation needs Windows with Microsoft Office installed")
    for attempt in (1, 2):
        try:
            import pythoncom
            import pywintypes
            import win32com.client
            _loaded = (pythoncom, pywintypes, win32com.client)
            return _loaded
        except ImportError as error:
            if "DLL load failed" in str(error):
                raise OfficeUnavailable(f"pywin32 is installed but Windows refused to load its DLLs ({error}): "
                                        "Application Control may block them, or they are for another processor "
                                        "type") from None
            if attempt == 2:
                raise OfficeUnavailable(f"pywin32 is not installed ({error}); run setup.ps1 again") from None
            _portable_paths()
        except OSError as error:
            raise OfficeUnavailable(f"pywin32 could not load ({error}); Windows Application Control may be blocking "
                                    "its DLLs") from None
    raise OfficeUnavailable("pywin32 could not load")


def pywin32_status() -> tuple[bool, str]:
    try:
        load_pywin32()
    except OfficeUnavailable as error:
        return False, str(error)
    try:
        from importlib.metadata import version
        return True, f"pywin32 {version('pywin32')}"
    except Exception:  # noqa: BLE001 - the version is informational
        return True, "pywin32"


def com_message(error: BaseException) -> str:
    """A COM failure in words: Office's own description when it gave one, plus the HRESULT."""
    args: tuple[Any, ...] = tuple(getattr(error, "args", ()) or ())
    if len(args) >= 2 and isinstance(args[0], int):
        detail = str(args[1])
        if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) > 2 and args[2][2]:
            detail = str(args[2][2])
        text = f"{' '.join(detail.split())} (COM 0x{args[0] & 0xFFFFFFFF:08X})"
    else:
        text = f"{type(error).__name__}: {error}"
    if re.search(r"(?i)password", text):
        return "the file is password-protected: " + text
    if re.search(r"(?i)0x80040154|class not registered|invalid class string|0x800401F3", text):
        return "the Office application for this file is not installed: " + text
    return text


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """A property that may not exist on this kind of object, or may raise (COM is uneven across shape types)."""
    if obj is None:
        return default
    try:
        value = getattr(obj, name)
    except Exception:  # noqa: BLE001 - absent or failing COM properties read as missing
        return default
    if isinstance(value, types.MethodType):  # not a COM object: those are callable too (their default member)
        try:
            value = value()  # methods and parameterised properties (ChartObjects, RowFields...) in late binding
        except Exception:  # noqa: BLE001
            return default
    return value


def _items(collection: Any) -> Iterator[Any]:
    if collection is None:
        return
    try:
        yield from iter(collection)
        return
    except TypeError:
        pass
    count = int(_get(collection, "Count", 0) or 0)
    for index in range(1, count + 1):
        with contextlib.suppress(Exception):
            yield collection.Item(index)


class OfficeSession:
    """Office automation for one thread. Use as a context manager; applications start on first use."""

    def __init__(self) -> None:
        self.pythoncom, self.pywintypes, self.client = load_pywin32()
        self.pythoncom.CoInitialize()
        self.apps: dict[str, tuple[Any, bool, dict[str, Any]]] = {}

    def __enter__(self) -> OfficeSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def app(self, name: str) -> Any:
        if name in self.apps:
            return self.apps[name][0]
        progid = PROGIDS[name]
        owned = False
        try:
            application = self.client.GetActiveObject(progid)
        except self.pywintypes.com_error:
            try:
                application = self.client.Dispatch(progid) if name == "outlook" else self.client.DispatchEx(progid)
            except self.pywintypes.com_error as error:
                raise OfficeUnavailable(f"{progid} could not start: {com_message(error)}") from None
            owned = True
        saved: dict[str, Any] = {}

        def change(attribute: str, value: Any) -> None:
            try:
                saved[attribute] = getattr(application, attribute)
                setattr(application, attribute, value)
            except Exception:  # noqa: BLE001 - a setting this version does not expose is skipped
                saved.pop(attribute, None)

        if name in ("word", "excel", "powerpoint"):
            change("AutomationSecurity", 3)  # msoAutomationSecurityForceDisable: never run macros
        if name == "word":
            change("DisplayAlerts", 0)  # wdAlertsNone
        elif name == "excel":
            change("DisplayAlerts", False)
            change("AskToUpdateLinks", False)
        elif name == "powerpoint":
            change("DisplayAlerts", 1)  # ppAlertsNone
        self.apps[name] = (application, owned, saved)
        return application

    def close(self) -> None:
        for name, (application, owned, saved) in self.apps.items():
            for attribute, value in saved.items():
                with contextlib.suppress(Exception):
                    setattr(application, attribute, value)
            if owned:
                with contextlib.suppress(Exception):
                    open_documents = {"word": "Documents", "excel": "Workbooks", "powerpoint": "Presentations"}.get(name)
                    if open_documents is None or int(getattr(application, open_documents).Count) == 0:
                        application.Quit()
        self.apps.clear()
        with contextlib.suppress(Exception):
            self.pythoncom.CoUninitialize()

    def error(self, error: BaseException) -> ConversionError:
        return error if isinstance(error, ConversionError) else ConversionError(com_message(error))


# --- PowerPoint ------------------------------------------------------------------------------------------------------


@dataclass
class _Slide:
    lines: list[str] = field(default_factory=list)
    text_chars: int = 0
    picture_area: float = 0.0
    graphics: int = 0


def _text_of(shape: Any) -> str:
    frame = _get(shape, "TextFrame")
    if _get(frame, "HasText") != MSO_TRUE:
        return ""
    return tidy(str(_get(_get(frame, "TextRange"), "Text", "") or ""))


def _chart(chart: Any) -> str:
    title = str(_get(_get(chart, "ChartTitle"), "Text", "") or "") if _get(chart, "HasTitle") else ""
    series: list[tuple[str, list[str], list[str]]] = []
    for item in _items(_get(chart, "SeriesCollection")):
        values = [show(v) for v in (_get(item, "Values", ()) or ())]
        categories = [show(c) for c in (_get(item, "XValues", ()) or ())]
        series.append((str(_get(item, "Name", "") or f"Series {len(series) + 1}"), categories, values))
    return chart_block(title, series)


def _shape(shape: Any, slide: _Slide, title: str, depth: int = 0) -> None:
    if depth > 8:
        return
    kind = int(_get(shape, "Type", 0) or 0)
    if kind == 6:  # msoGroup
        for item in _items(_get(shape, "GroupItems")):
            _shape(item, slide, title, depth + 1)
        return
    if _get(shape, "HasTable") == MSO_TRUE:
        table = shape.Table
        rows = [[_text_of(table.Cell(r, c).Shape) for c in range(1, int(table.Columns.Count) + 1)]
                for r in range(1, int(table.Rows.Count) + 1)]
        slide.lines.append(markdown_table(rows))
        slide.text_chars += sum(len(c) for row in rows for c in row)
        return
    if _get(shape, "HasChart") == MSO_TRUE:  # its values are read as text, so it does not make a slide 'visual'
        slide.lines.append(_chart(shape.Chart))
        return
    if _get(shape, "HasSmartArt") == MSO_TRUE:
        nodes = [str(_get(_get(_get(node, "TextFrame2"), "TextRange"), "Text", "") or "").strip()
                 for node in _items(_get(_get(shape, "SmartArt"), "AllNodes"))]
        nodes = [n for n in nodes if n]
        if nodes:
            slide.lines.append("Diagram: " + " -> ".join(nodes))
            slide.text_chars += sum(len(n) for n in nodes)
        return
    contained = int(_get(_get(shape, "PlaceholderFormat"), "ContainedType", 0) or 0) if kind == 14 else 0
    if kind in PICTURES or contained in PICTURES:
        slide.picture_area += float(_get(shape, "Width", 0) or 0) * float(_get(shape, "Height", 0) or 0)
        slide.graphics += 1
        alt = " ".join(str(_get(shape, "AlternativeText", "") or "").split())
        slide.lines.append(f"Picture: {alt}" if alt and not DEFAULT_NAMES.match(alt) else "Picture")
        return
    if _get(shape, "HasTextFrame") != MSO_TRUE:
        return
    text = _text_of(shape)
    if not text or text == title:
        return
    text_range = shape.TextFrame.TextRange
    # PowerPoint separates paragraphs with CR and line breaks inside one with VT, so CR positions are paragraph numbers.
    for index, paragraph in enumerate(str(_get(text_range, "Text", "") or "").split("\r"), start=1):
        paragraph = " ".join(paragraph.replace("\x0b", " ").split())
        if not paragraph:
            continue
        try:
            level = int(text_range.Paragraphs(index, 1).IndentLevel)
        except Exception:  # noqa: BLE001 - indentation is cosmetic
            level = 1
        slide.lines.append(f"{'  ' * max(level - 1, 0)}- {paragraph}")
        slide.text_chars += len(paragraph)


def read_powerpoint(session: OfficeSession, path: Path, assets: Path, slide_images: str = "auto") -> Converted:
    application = session.app("powerpoint")
    try:
        presentation = application.Presentations.Open(str(path), ReadOnly=True, Untitled=False, WithWindow=False)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    blocks, parts, images = [], [], []
    try:
        width = float(presentation.PageSetup.SlideWidth)
        height = float(presentation.PageSetup.SlideHeight)
        for slide_object in _items(presentation.Slides):
            index = int(slide_object.SlideIndex)
            shapes_collection = slide_object.Shapes
            title = ""
            if _get(shapes_collection, "HasTitle") == MSO_TRUE:
                title = " ".join(_text_of(shapes_collection.Title).split())
            slide = _Slide()
            shapes = list(_items(shapes_collection))
            shapes.sort(key=lambda s: (round(float(_get(s, "Top", 0) or 0) / 24), float(_get(s, "Left", 0) or 0)))
            for shape in shapes:
                _shape(shape, slide, title)
            notes = []
            for placeholder in _items(_get(_get(_get(slide_object, "NotesPage"), "Shapes"), "Placeholders")):
                if int(_get(_get(placeholder, "PlaceholderFormat"), "Type", 0) or 0) == 2:  # ppPlaceholderBody
                    notes += [f"- {line.strip()}" for line in _text_of(placeholder).split("\n") if line.strip()]
            hidden = _get(_get(slide_object, "SlideShowTransition"), "Hidden") == MSO_TRUE
            heading = f"Slide {index}" + (f": {title}" if title else "")
            parts.append(heading)
            block = [f"## {heading}{' (hidden slide)' if hidden else ''}", *slide.lines]
            if notes:
                block += ["Speaker notes:", *notes]
            visual = slide.picture_area >= 0.15 * width * height or (slide.graphics > 0 and slide.text_chars < 80)
            if slide_images == "all" or (slide_images == "auto" and visual):
                assets.mkdir(parents=True, exist_ok=True)
                target = assets / f"slide-{index:03d}.png"
                try:
                    slide_object.Export(str(target), "PNG", SLIDE_IMAGE_WIDTH, round(SLIDE_IMAGE_WIDTH * height / width))
                    images.append(target)
                    block.append(f"Slide image: {target.name} (the slide is mostly visual: look at the image)")
                except session.pywintypes.com_error as error:
                    block.append(f"(slide image could not be exported: {com_message(error)})")
            blocks.append("\n".join(block))
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    finally:
        with contextlib.suppress(Exception):
            presentation.Close()
    return Converted("\n\n".join(blocks), "office", images=images, parts=parts)


# --- Excel -----------------------------------------------------------------------------------------------------------


def _grid(value: Any) -> list[list[Any]]:
    if isinstance(value, tuple):
        return [list(row) if isinstance(row, tuple) else [row] for row in value]
    return [[value]]


def _all_rows(worksheet: Any, first_row: int, first_column: int, total_rows: int, columns: int) -> list[list[Any]]:
    """Every row of the used range (up to MAX_TABLE_ROWS), read in batches like data_governance's NASCA reader."""
    grid: list[list[Any]] = []
    last = first_row + min(total_rows, MAX_TABLE_ROWS) - 1
    for start in range(first_row, last + 1, 5000):
        end = min(start + 4999, last)
        window = worksheet.Range(worksheet.Cells(start, first_column), worksheet.Cells(end, first_column + columns - 1))
        grid += _grid(window.Value)
    return grid


def read_excel(session: OfficeSession, path: Path, max_rows: int = EXCEL_READ_ROWS, tables: bool = False) -> Converted:
    application = session.app("excel")
    try:
        workbook = application.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True,
                                              AddToMru=False)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    blocks, parts, built = [], [], []
    try:
        for worksheet in _items(workbook.Worksheets):
            name = str(worksheet.Name)
            used = worksheet.UsedRange
            total_rows, total_columns = int(used.Rows.Count), int(used.Columns.Count)
            first_row, first_column = int(used.Row), int(used.Column)
            take_rows, take_columns = min(total_rows, max_rows), min(total_columns, EXCEL_READ_COLUMNS)
            window = worksheet.Range(worksheet.Cells(first_row, first_column),
                                     worksheet.Cells(first_row + take_rows - 1, first_column + take_columns - 1))
            values = _grid(window.Value)
            formulas = [[str(f) if isinstance(f, str) and f.startswith("=") else "" for f in row]
                        for row in _grid(window.Formula)]
            pivots = []
            for pivot in _items(_get(worksheet, "PivotTables")):
                fields = {label: [str(_get(f, "Name", "")) for f in _items(_get(pivot, attribute))]
                          for label, attribute in (("rows", "RowFields"), ("columns", "ColumnFields"),
                                                   ("values", "DataFields"), ("filters", "PageFields"))}
                described = "; ".join(f"{label}: {', '.join(names)}" for label, names in fields.items() if names)
                pivots.append(f"{_get(pivot, 'Name', 'Pivot')} from {_get(pivot, 'SourceData', 'unknown source')}"
                              + (f" ({described})" if described else ""))
            charts = []
            for chart_object in _items(_get(worksheet, "ChartObjects")):
                charts.append(_chart(_get(chart_object, "Chart")).replace("\n", "\n  "))
            parts.append(f"Sheet: {name}")
            blocks.append(render(Sheet(name, values, formulas, hidden=int(_get(worksheet, "Visible", -1)) != MSO_TRUE,
                                       total_rows=total_rows, total_columns=total_columns, first_row=first_row,
                                       first_column=first_column, pivots=pivots, charts=charts)))
            if tables:
                full = values if total_rows <= take_rows else \
                    _all_rows(worksheet, first_row, first_column, total_rows, take_columns)
                table = build(name, full, total_rows)
                if table is not None:
                    built.append(table)
        for chart_sheet in _items(_get(workbook, "Charts")):
            parts.append(f"Chart sheet: {_get(chart_sheet, 'Name', '')}")
            blocks.append(f"## Chart sheet: {_get(chart_sheet, 'Name', '')}\n\n{_chart(chart_sheet)}")
        names = []
        for defined in _items(_get(workbook, "Names")):
            label, refers = str(_get(defined, "Name", "")), str(_get(defined, "RefersTo", ""))
            if _get(defined, "Visible", True) and "_xlnm" not in label and "#REF" not in refers:
                names.append(f"- {label}: {refers[:120]}")
        if names:
            blocks.append("## Named ranges\n\n" + "\n".join(names[:80]))
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    finally:
        with contextlib.suppress(Exception):
            workbook.Close(False)
    return Converted("\n\n".join(blocks), "office", parts=parts, tables=built)


# --- Word ------------------------------------------------------------------------------------------------------------


def _word_table(table: Any) -> str:
    cells: dict[tuple[int, int], str] = {}
    for item in _items(_get(_get(table, "Range"), "Cells")):
        text = tidy(str(_get(_get(item, "Range"), "Text", "") or "")).replace("\n", " ")
        cells[(int(_get(item, "RowIndex", 0)), int(_get(item, "ColumnIndex", 0)))] = text
    if not cells:
        return ""
    rows = max(r for r, _ in cells)
    columns = max(c for _, c in cells)
    return markdown_table([[cells.get((r, c), "") for c in range(1, columns + 1)] for r in range(1, rows + 1)])


def read_word(session: OfficeSession, path: Path) -> Converted:
    application = session.app("word")
    try:
        document = application.Documents.Open(str(path), ConfirmConversions=False, ReadOnly=True,
                                              AddToRecentFiles=False, Visible=False)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    blocks, parts = [], []
    try:
        if int(document.Paragraphs.Count) > 5000:  # very long: plain text is far faster than paragraph by paragraph
            blocks.append(tidy(str(document.Content.Text)))
        else:
            tables = [(int(t.Range.Start), int(t.Range.End), t) for t in _items(document.Tables)]
            skip_until = -1
            for paragraph in _items(document.Paragraphs):
                start = int(paragraph.Range.Start)
                if start < skip_until:
                    continue
                inside = next(((s, e, t) for s, e, t in tables if s <= start < e), None)
                if inside:
                    blocks.append(_word_table(inside[2]))
                    skip_until = inside[1]
                    continue
                text = tidy(str(paragraph.Range.Text or ""))
                if not text:
                    continue
                level = int(_get(paragraph, "OutlineLevel", 10) or 10)
                if 1 <= level <= 6:
                    blocks.append(f"{'#' * level} {text}")
                    parts.append(text)
                elif int(_get(_get(paragraph.Range, "ListFormat"), "ListType", 0) or 0):
                    blocks.append(f"- {text}")
                else:
                    blocks.append(text)
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    finally:
        with contextlib.suppress(Exception):
            document.Close(SaveChanges=0)
    return Converted("\n\n".join(b for b in blocks if b), "office", parts=parts[:60])


# --- Outlook ---------------------------------------------------------------------------------------------------------


def _when(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
    return str(value or "")


def _save_attachments(item: Any, folder: Path) -> tuple[list[str], list[Path]]:
    names, saved = [], []
    for attachment in _items(_get(item, "Attachments")):
        name = safe_name(str(_get(attachment, "FileName", "") or ""))
        if not name or name == "attachment":
            continue
        names.append(name)
        folder.mkdir(parents=True, exist_ok=True)
        target = unique(folder / name)
        with contextlib.suppress(Exception):
            attachment.SaveAsFile(str(target))
            if target.is_file():
                saved.append(target)
    return names, saved


def message_text(item: Any, attachments: list[str]) -> str:
    header = email_header(str(_get(item, "Subject", "") or ""), str(_get(item, "SenderName", "") or ""),
                          str(_get(item, "To", "") or ""), str(_get(item, "CC", "") or ""),
                          _when(_get(item, "SentOn") or _get(item, "ReceivedTime")), attachments)
    return header + "\n\n" + tidy(str(_get(item, "Body", "") or ""))


def read_msg(session: OfficeSession, path: Path, attachments: Path) -> Converted:
    outlook = session.app("outlook")
    try:
        item = outlook.Session.OpenSharedItem(str(path))
    except session.pywintypes.com_error as error:
        raise session.error(error) from None
    try:
        names, saved = _save_attachments(item, attachments)
        return Converted(message_text(item, names), "office", attachments=saved)
    finally:
        with contextlib.suppress(Exception):
            item.Close(1)  # olDiscard


def _slug(text: str, limit: int = 50) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit] or "untitled"


def _folders(folder: Any, path: str, depth: int) -> Iterator[tuple[str, Any]]:
    for child in _items(_get(folder, "Folders")):
        child_path = f"{path}/{_get(child, 'Name', '?')}"
        if int(_get(child, "DefaultItemType", 0) or 0) == 0:  # olMailItem
            yield child_path, child
        if depth > 1:
            yield from _folders(child, child_path, depth - 1)


def mail_folders(session: OfficeSession, depth: int = 3) -> list[tuple[str, int]]:
    """Every mail folder of every mailbox and its item count, as 'Mailbox/Inbox/Projects'."""
    namespace = session.app("outlook").GetNamespace("MAPI")
    found = []
    for store in _items(_get(namespace, "Stores")):
        root = _get(store, "GetRootFolder")
        for path, folder in _folders(root, str(_get(root, "Name", "Mailbox")), depth):
            found.append((path, int(_get(_get(folder, "Items"), "Count", 0) or 0)))
    return found


def resolve_folder(session: OfficeSession, path: str) -> Any:
    """'Inbox', 'Sent Items', 'Inbox/Projects' (default mailbox, any display language) or 'Mailbox name/Folder/...'."""
    namespace = session.app("outlook").GetNamespace("MAPI")
    parts = [p for p in re.split(r"[\\/]", path) if p]
    if not parts:
        raise ConversionError("give a folder, e.g. Inbox or Inbox/Projects")
    special = {"inbox": 6, "sent": 5, "sent items": 5}
    if parts[0].lower() in special:
        folder, rest = namespace.GetDefaultFolder(special[parts[0].lower()]), parts[1:]
    else:
        default_root = namespace.GetDefaultFolder(6).Parent
        roots = [default_root, *[_get(s, "GetRootFolder") for s in _items(_get(namespace, "Stores"))]]
        match = next((r for r in roots if str(_get(r, "Name", "")).lower() == parts[0].lower()), None)
        folder, rest = (match, parts[1:]) if match is not None else (default_root, parts)
    for name in rest:
        child = next((c for c in _items(_get(folder, "Folders")) if str(_get(c, "Name", "")).lower() == name.lower()), None)
        if child is None:
            raise ConversionError(f"no Outlook folder '{name}' under '{_get(folder, 'Name', '?')}' (list them with "
                                  "outlook-folders)")
        folder = child
    return folder


@dataclass
class MailExport:
    exported: int = 0
    already: int = 0
    private: int = 0
    unmatched: int = 0
    other_items: int = 0
    attachments: int = 0
    folders: list[str] = field(default_factory=list)


def export_mail(session: OfficeSession, folder_paths: list[str], out: Path, since: dt.datetime, until: dt.datetime,
                words: list[str], limit: int, include_private: bool = False, subfolders: bool = False) -> MailExport:
    """Copy mail items to Markdown files (header with display names, then the body) and their attachments to a sibling
    '<name>.attachments' folder. Read-only on the mailbox; an item already exported is skipped."""
    result = MailExport()
    lowered = [w.lower() for w in words if w.strip()]
    for path in folder_paths:
        root = resolve_folder(session, path)
        targets = [(path, root)] + (list(_folders(root, path, 6)) if subfolders else [])
        for label, folder in targets:
            result.folders.append(label)
            items = folder.Items
            with contextlib.suppress(Exception):
                items.Sort("[ReceivedTime]", True)
            for item in _items(items):
                if result.exported >= limit:
                    return result
                if int(_get(item, "Class", 0) or 0) != OL_MAIL:
                    result.other_items += 1
                    continue
                received = _get(item, "ReceivedTime")
                when = received.replace(tzinfo=None) if isinstance(received, dt.datetime) else None
                if when is None or when > until:
                    continue
                if when < since:
                    break  # sorted newest first
                if int(_get(item, "Sensitivity", 0) or 0) >= 2 and not include_private:  # olPrivate, olConfidential
                    result.private += 1
                    continue
                subject = str(_get(item, "Subject", "") or "")
                if lowered:
                    haystack = f"{subject}\n{_get(item, 'Body', '') or ''}".lower()
                    if not any(w in haystack for w in lowered):
                        result.unmatched += 1
                        continue
                entry = hashlib.sha1(str(_get(item, "EntryID", subject)).encode(), usedforsecurity=False).hexdigest()[:6]
                name = f"{when:%Y-%m-%d_%H%M}_{_slug(subject)}_{entry}"
                folder_dir = out / _slug(label.replace("/", "_"), 80)
                target = folder_dir / f"{name}.md"
                if target.exists():
                    result.already += 1
                    continue
                names, saved = _save_attachments(item, folder_dir / f"{name}.attachments")
                result.attachments += len(saved)
                folder_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(f"Folder: {label}\n" + message_text(item, names) + "\n", encoding="utf-8")
                result.exported += 1
    return result

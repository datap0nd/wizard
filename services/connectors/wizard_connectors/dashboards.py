"""Dashboards: the team's HTML dashboards (owner, 2 Nov 2026: "I believe these dashboards should definitely be the first
thing in the priority list as they are dashboards prepared combining logic and data that wizard will struggle to get
right off the bat").

A folder of standalone HTML pages, usually on a network share (WIZARD_HTML_REPORTS_DIR; Settings → Dashboards). Wizard
lists them and reads one as data: its title, the date it states, headings and visible text, tables as rows, and the
data embedded in its scripts that parses as JSON (chart series, data arrays, the objects handed to Plotly, ECharts,
Chart.js, Highcharts or Vega), with names and chart and axis titles. It never runs a script and never fetches anything a
page references: data a page loads from an address, and script data that is not JSON, are named as not read.

Only files inside the folder are read (no `..`, no absolute paths, no links out), each within a size and a time limit;
a parse is kept under the data folder by path, size and modified time. A mapped drive letter is stored as the network
path it maps to (WNetGetConnectionW): another PC may map the share to another letter, or not at all (owner: "Y:\\ is
indeed a risk as it's mapped as that in my pc but might not be the same in another PC"). A folder this PC cannot reach
never stops Wizard: the tools and `run.py --check` say so, and to ask for access to the share."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from html.parser import HTMLParser
from pathlib import Path, PureWindowsPath
from typing import Any, TypeVar

SYSTEM = "dashboards"
DEFAULT_NAME = "Dashboards"
SUFFIXES = (".html", ".htm")
ID = re.compile(r"^d[0-9a-f]{10}$")
MAX_FILES = 2000
MAX_DEPTH = 12
MAX_BYTES = 50 * 1024 * 1024  # a page larger than this is not read
HEAD_BYTES = 512 * 1024  # what the list reads of a page it has not read whole: title, headings, the date it states
LOOSE_MAX = 2 * 1024 * 1024  # script data that is not strict JSON is read loosely only up to this size
MAX_TABLES = 300
MAX_DATASETS = 300
MAX_ROWS = 20_000  # rows kept of one table or data set
MAX_COLUMNS = 60
CELL_CHARS = 300
TEXT_CHARS = 400_000  # visible text kept of one page
PROBE_S = 10.0
LIST_S = 90.0
READ_S = 100.0  # a tool call answers well within the 180 seconds the Gemini CLI route gives it
LISTING_S = 60.0  # the folder is walked again at most once a minute
PARSER = 1  # a cached parse made by another version of the reader is made again

T = TypeVar("T")


class DashboardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# The folder's path ----------------------------------------------------------------------------------------------------
DRIVE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$", re.S)


def _windows() -> bool:
    return os.name == "nt"


def clean(text: str) -> str:
    """A path as people paste it: quotes from Copy as path removed, ~ and %VARIABLES% expanded."""
    cleaned = text.strip().strip('"').strip("'").strip()
    return os.path.expandvars(os.path.expanduser(cleaned)) if cleaned else ""


def drive_connection(drive: str) -> str | None:
    """The network path a drive letter ("Y:") maps to on this PC, also while it is disconnected; None for a local drive,
    a letter nothing maps, or off Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    try:
        connect = ctypes.WinDLL("mpr").WNetGetConnectionW
        connect.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        connect.restype = wintypes.DWORD
        size = wintypes.DWORD(1024)
        for _ in range(2):
            buffer = ctypes.create_unicode_buffer(size.value)
            result = connect(drive, buffer, ctypes.byref(size))
            if result == 234:  # ERROR_MORE_DATA: size now holds what is needed
                continue
            # 0: connected; 1201 (ERROR_CONNECTION_UNAVAIL): remembered, not connected right now.
            if result in (0, 1201) and buffer.value:
                return str(buffer.value)
            return None
    except (OSError, AttributeError, ValueError):
        return None
    return None


def network_path(path: str) -> str:
    """A path on a mapped network drive (Y:\\Dashboards) as the network path it maps to (\\\\server\\share\\Dashboards),
    so it names the same folder on every PC; any other path as it is."""
    match = DRIVE.match(path)
    if not match or not _windows():
        return path
    remote = drive_connection(match.group(1).upper() + ":")
    if not remote:
        return path
    rest = (match.group(2) or "").replace("/", "\\").strip("\\")
    return remote.rstrip("\\") + ("\\" + rest if rest else "")


def stored_value(text: str) -> str:
    """What Wizard keeps for the folder a person typed: quotes removed, a mapped drive as its network path."""
    return network_path(clean(text))


def folder_path(text: str, base: Path) -> Path:
    """The folder a setting names, worked out without touching the disk (a share that does not answer must not hold up
    start-up). Relative paths are inside `base`, the install folder."""
    value = stored_value(text)
    if value.startswith(("\\\\", "//")) or PureWindowsPath(value).is_absolute() or Path(value).is_absolute():
        return Path(os.path.normpath(value))
    return Path(os.path.normpath(base / value))


def bounded(work: Callable[[], T], seconds: float, what: str) -> T:
    """Run `work` in a thread of its own and wait at most `seconds`: Windows holds a file call on a share that does not
    answer for a long time, and a tool must answer."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = work()
        except Exception as error:  # handed to the caller below
            box["error"] = error

    thread = threading.Thread(target=target, name="wizard-dashboards", daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise DashboardError("no_answer", f"{what} did not answer within {max(1, round(seconds))} seconds")
    if "error" in box:
        raise box["error"]
    return box["value"]


def dashboard_id(relative: str) -> str:
    return "d" + hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:10]


@dataclass(frozen=True)
class Dashboard:
    id: str
    path: Path
    relative: str  # inside the folder, with / between folders
    bytes: int
    modified: float

    @property
    def subfolder(self) -> str:
        return self.relative.rpartition("/")[0]


def _junction(entry: os.DirEntry[str]) -> bool:
    check = getattr(entry, "is_junction", None)  # Python 3.12+
    return bool(check()) if check else False


def _walk(root: Path) -> Iterator[Path]:
    """HTML files under root, never following a link out of it, skipping hidden folders and lock files."""
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith((".", "~$")):
                continue
            try:
                if entry.is_symlink() or _junction(entry):
                    continue
                if entry.is_dir():
                    if depth < MAX_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                elif entry.is_file() and entry.name.lower().endswith(SUFFIXES):
                    yield Path(entry.path)
            except OSError:
                continue


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")


def as_of(stated: dict[str, Any] | None, modified: float) -> dict[str, Any]:
    """The date a dashboard's figures are as of: the one the page states, else the file's modified time, and which."""
    if stated:
        return stated
    return {"date": iso(modified), "from": "file modified time"}


def unreachable(root: Path, problem: str) -> str:
    return (f"This PC cannot reach the dashboards folder {root}: {problem}. Ask for access to the share that holds it (or "
            "set the folder again in Settings → Dashboards if it moved). Until then Wizard cannot read the dashboards: "
            "answer from the other sources and say so.")


class Dashboards:
    """The dashboards folder on this PC: what is in it, and each page read as data (kept by path, size and time)."""

    def __init__(self, root: Path, data_dir: Path | None, name: str = DEFAULT_NAME):
        self.root = root
        self.name = name
        self.cache = data_dir  # data/dashboards: parses and the list's summaries; None keeps nothing
        self._lock = threading.Lock()
        self._listing: tuple[float, list[Dashboard]] | None = None
        self._probe: tuple[float, str | None] | None = None

    # Reaching the folder ------------------------------------------------------------------------------------------------
    def _check_root(self) -> str | None:
        try:
            info = os.stat(self.root)
        except FileNotFoundError:
            return "it is not there (the share or folder does not exist, or this PC is not connected to it)"
        except PermissionError:
            return "this PC's Windows account is not allowed to open it"
        except OSError as error:
            return error.strerror or str(error)
        return None if stat.S_ISDIR(info.st_mode) else "it is a file, not a folder"

    def problem(self, fresh: bool = False) -> str | None:
        """None when this PC can open the folder; else what is wrong, in words the person can act on."""
        cached = self._probe
        if cached and not fresh and time.monotonic() - cached[0] < LISTING_S:
            return cached[1]
        try:
            problem = bounded(self._check_root, PROBE_S, "the folder")
        except DashboardError as error:
            problem = error.message
        self._probe = (time.monotonic(), problem)
        return problem

    def known_count(self) -> int | None:
        """How many dashboards the last listing found, without walking the folder again; None before one."""
        return len(self._listing[1]) if self._listing else None

    # What is in it -------------------------------------------------------------------------------------------------------
    def listing(self, fresh: bool = False) -> list[Dashboard]:
        cached = self._listing
        if cached and not fresh and time.monotonic() - cached[0] < LISTING_S:
            return cached[1]
        problem = self.problem(fresh=True)
        if problem:
            raise DashboardError("folder_unreachable", unreachable(self.root, problem))
        try:
            found = bounded(self._list, LIST_S, "Listing the dashboards folder")
        except DashboardError as error:
            raise DashboardError("folder_unreachable", unreachable(self.root, error.message)) from None
        self._listing = (time.monotonic(), found)
        return found

    def _list(self) -> list[Dashboard]:
        found = []
        for path in _walk(self.root):
            try:
                info = path.stat()
            except OSError:
                continue
            relative = path.relative_to(self.root).as_posix()
            found.append(Dashboard(dashboard_id(relative), path, relative, info.st_size, info.st_mtime))
            if len(found) >= MAX_FILES:
                break
        found.sort(key=lambda d: d.relative.casefold())
        return found

    def find(self, key: str) -> Dashboard:
        """A dashboard by its id, or by its path inside the folder. Anything that points outside is refused."""
        wanted = key.strip().strip('"').strip("'").replace("\\", "/").strip()
        by_id = bool(ID.match(wanted))
        if not by_id and (not wanted or wanted.startswith("/") or ":" in wanted
                          or any(p in ("..", ".") for p in wanted.split("/"))):
            raise DashboardError("outside_folder", "Only dashboards inside the dashboards folder can be read: give an id "
                                                   "from wizard_dashboards or a path inside the folder.")
        folded = wanted.casefold()
        for fresh in (False, True):
            item = next((d for d in self.listing(fresh=fresh)
                         if (d.id == wanted if by_id else d.relative.casefold() == folded)), None)
            if item is not None:
                return item
        raise DashboardError("unknown_dashboard", f"No dashboard '{key}' in the dashboards folder. Ids come from "
                                                  "wizard_dashboards.")

    def title_of(self, key: str) -> str | None:
        """A dashboard's title as last read, without touching the folder (for step labels)."""
        if not self._listing:
            return None
        item = next((d for d in self._listing[1] if d.id == key or d.relative.casefold() == key.casefold()), None)
        if item is None:
            return None
        summary = self._summaries().get(item.relative)
        return str(summary["title"]) if summary and summary.get("title") else item.relative

    # Reading ------------------------------------------------------------------------------------------------------------
    def _inside(self, item: Dashboard) -> Path:
        """The file itself, checked once more: inside the folder, an HTML file, not a link out of it."""
        try:
            real = item.path.resolve(strict=True)
            root = self.root.resolve(strict=True)
        except OSError:
            raise DashboardError("dashboard_gone", f"{item.relative} is no longer in the dashboards folder (moved or "
                                                   "renamed). List the dashboards again.") from None
        if item.path.is_symlink() or not real.is_relative_to(root) or real.suffix.lower() not in SUFFIXES:
            raise DashboardError("outside_folder", f"{item.relative} points outside the dashboards folder; Wizard does "
                                                   "not read it.")
        return real

    def _cache_file(self, item: Dashboard) -> Path | None:
        if self.cache is None:
            return None
        return self.cache / "pages" / (hashlib.sha256(item.relative.casefold().encode("utf-8")).hexdigest()[:20] + ".json")

    def _cached(self, item: Dashboard) -> dict[str, Any] | None:
        target = self._cache_file(item)
        if target is None:
            return None
        try:
            record = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (record.get("parser") != PARSER or record.get("bytes") != item.bytes
                or record.get("modified") != round(item.modified, 3)):
            return None
        page = record.get("page")
        return page if isinstance(page, dict) else None

    def _keep(self, item: Dashboard, page: dict[str, Any]) -> None:
        target = self._cache_file(item)
        if target is None:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_suffix(".tmp")
            pending.write_text(json.dumps({"parser": PARSER, "relative": item.relative, "bytes": item.bytes,
                                           "modified": round(item.modified, 3), "page": page}, ensure_ascii=False),
                               encoding="utf-8")
            pending.replace(target)
            self._remember({item.relative: self._entry(item, summary_of(page))})
        except OSError:
            pass  # the cache only saves time

    def _current(self, item: Dashboard) -> Dashboard:
        """The file as it is now (the list is up to a minute old): its size and modified time."""
        try:
            info = bounded(item.path.stat, PROBE_S, f"The dashboard {item.relative}")
        except DashboardError as error:
            raise DashboardError("folder_unreachable", unreachable(self.root, error.message)) from None
        except OSError:
            raise DashboardError("dashboard_gone", f"{item.relative} is no longer in the dashboards folder (moved, "
                                                   "renamed or deleted). List the dashboards again.") from None
        if info.st_size == item.bytes and info.st_mtime == item.modified:
            return item
        return Dashboard(item.id, item.path, item.relative, info.st_size, info.st_mtime)

    def page(self, item: Dashboard) -> dict[str, Any]:
        """The dashboard read as data (see parse_page), from the cache when the file has not changed. `modified` is the
        file's modified time when it was read: the as-of date when the page states none."""
        item = self._current(item)
        cached = self._cached(item)
        if cached is not None:
            return {**cached, "modified": item.modified}
        if item.bytes > MAX_BYTES:
            raise DashboardError("too_large", f"{item.relative} is {item.bytes / 1_048_576:.0f} MB; Wizard reads "
                                              f"dashboards up to {MAX_BYTES // 1_048_576} MB. Say it could not be read.")

        def read() -> dict[str, Any]:
            real = self._inside(item)
            with real.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise DashboardError("too_large", f"{item.relative} is larger than {MAX_BYTES // 1_048_576} MB; Wizard "
                                                  "does not read it.")
            page = parse_page(decode(raw), deadline=time.monotonic() + READ_S - 10)
            page["sha256"] = hashlib.sha256(raw).hexdigest()
            page["bytes"] = len(raw)
            return page

        try:
            page = bounded(read, READ_S, f"Reading {item.relative}")
        except DashboardError as error:
            if error.code == "no_answer":
                raise DashboardError("folder_unreachable", unreachable(self.root, error.message)) from None
            raise
        except OSError as error:
            raise DashboardError("dashboard_unreadable", f"{item.relative} could not be opened: "
                                                         f"{error.strerror or error}.") from None
        self._keep(item, page)
        return {**page, "modified": item.modified}

    # The list's summaries (title, headings, stated date) ------------------------------------------------------------------
    def _index_file(self) -> Path | None:
        return self.cache / "index.json" if self.cache is not None else None

    def _summaries(self) -> dict[str, dict[str, Any]]:
        target = self._index_file()
        if target is None:
            return {}
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _remember(self, entries: dict[str, dict[str, Any]]) -> None:
        """Add summaries (by relative path) to the list's index."""
        target = self._index_file()
        if target is None or not entries:
            return
        try:
            with self._lock:
                known = {**self._summaries(), **entries}
                target.parent.mkdir(parents=True, exist_ok=True)
                pending = target.with_suffix(".tmp")
                pending.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
                pending.replace(target)
        except OSError:
            pass  # the index only saves time

    @staticmethod
    def _entry(item: Dashboard, summary: dict[str, Any]) -> dict[str, Any]:
        return {**summary, "bytes": item.bytes, "modified": round(item.modified, 3), "parser": PARSER}

    def summaries(self, items: list[Dashboard], seconds: float = LIST_S) -> dict[str, dict[str, Any]]:
        """Each dashboard's title, first headings and stated date, from the cache or from the start of the file. Pages
        not reached before the time is up show their file name."""
        known = self._summaries()
        found: dict[str, dict[str, Any]] = {}
        todo = []
        for item in items:
            entry = known.get(item.relative)
            if (entry and entry.get("bytes") == item.bytes and entry.get("modified") == round(item.modified, 3)
                    and entry.get("parser") == PARSER):
                found[item.id] = entry
            else:
                todo.append(item)
        if not todo:
            return found
        deadline = time.monotonic() + seconds

        def head(item: Dashboard) -> dict[str, Any]:
            real = self._inside(item)
            with real.open("rb") as handle:
                raw = handle.read(HEAD_BYTES)
            return summary_of(parse_page(decode(raw), deadline=time.monotonic() + 20, scripts=False))

        added: dict[str, dict[str, Any]] = {}
        for item in todo:
            left = deadline - time.monotonic()
            if left <= 1:
                break
            try:
                summary = bounded(partial(head, item), min(left, 30), item.relative)
            except (DashboardError, OSError):
                continue
            added[item.relative] = found[item.id] = self._entry(item, summary)
        self._remember(added)
        return found


def summary_of(page: dict[str, Any]) -> dict[str, Any]:
    return {"title": page.get("title") or None, "headings": [h["text"] for h in page.get("headings", [])[:12]],
            "stated": page.get("as_of")}


def decode(raw: bytes) -> str:
    """The page's text: its byte-order mark, else the charset it declares, else UTF-8."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    declared = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_.:-]{2,40})", raw[:4096], re.I)
    if declared:
        try:
            return raw.decode(declared.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    return raw.decode("utf-8", errors="replace")


# The page as data ------------------------------------------------------------------------------------------------------
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
                  "wbr", "keygen"})
BLOCK = frozenset({"address", "article", "aside", "blockquote", "body", "caption", "dd", "details", "dialog", "div", "dl",
                   "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
                   "header", "hgroup", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "summary", "ul", "br",
                   "legend", "label", "table", "tr", "center"})
HIDING = frozenset({"script", "style", "template", "noscript", "head", "object", "iframe", "button", "textarea"})
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
CLOSES = {"p": {"p"}, "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "option": {"option"},
          "td": {"td", "th"}, "th": {"td", "th"}, "tr": {"tr", "td", "th"},
          "thead": {"thead", "tbody", "tfoot", "tr", "td", "th"}, "tbody": {"thead", "tbody", "tfoot", "tr", "td", "th"},
          "tfoot": {"thead", "tbody", "tfoot", "tr", "td", "th"}}
LIBRARY_SRC = re.compile(r"plotly|echarts|chart(?:\.umd|\.min|\.js|js)|highcharts|vega|d3(?:\.v\d|\.min|\.js)|jquery|"
                         r"bootstrap|react|vue|lodash|moment|tailwind|mathjax|katex|require|polyfill|apexcharts|amcharts|"
                         r"datatables|ag-grid|leaflet|mapbox|font", re.I)
SPACE = re.compile(r"\s+")


def squash(text: str) -> str:
    return SPACE.sub(" ", text).strip()


class _Table:
    def __init__(self, label: str | None, heading: str | None):
        self.rows: list[list[tuple[str, int, int]]] = []
        self.header_rows: set[int] = set()  # rows inside <thead>, or made of <th> only
        self.th_rows: list[bool] = []
        self.row: list[tuple[str, int, int]] | None = None
        self.row_all_th = True
        self.cell: list[str] | None = None
        self.cell_span = (1, 1)
        self.in_head = False
        self.caption: list[str] | None = None
        self.caption_text = ""
        self.label = label
        self.heading = heading


class _PageParser(HTMLParser):
    def __init__(self, deadline: float, scripts: bool):
        super().__init__(convert_charrefs=True)
        self.deadline = deadline
        self.want_scripts = scripts
        self.stack: list[tuple[str, bool]] = []  # open element, whether it hides what is in it
        self.hidden = 0
        self.title: list[str] | None = None
        self.title_text = ""
        self.lines: list[str] = []
        self.parts: list[str] = []
        self.chars = 0
        self.headings: list[dict[str, Any]] = []  # level, text, line (index into lines)
        self.heading: tuple[int, list[str]] | None = None
        self.last_heading: str | None = None
        self.tables: list[tuple[_Table, int]] = []  # finished, with the line its placeholder is on
        self.open_tables: list[_Table] = []
        self.select: list[str] | None = None
        self.option: list[str] | None = None
        self.script: dict[str, Any] | None = None
        self.scripts: list[dict[str, Any]] = []
        self.meta: dict[str, str] = {}
        self.refs: list[str] = []
        self.libraries: list[str] = []
        self.attr_json: list[tuple[str, str]] = []  # where, value
        self.images = 0
        self.canvases = 0

    # Text ---------------------------------------------------------------------------------------------------------------
    def flush(self) -> None:
        if self.parts:
            text = squash(" ".join(self.parts))
            self.parts = []
            if text and self.chars < TEXT_CHARS:
                self.lines.append(text)
                self.chars += len(text) + 1

    def handle_data(self, data: str) -> None:
        if self.script is not None:
            self.script["parts"].append(data)
            return
        if self.title is not None:
            self.title.append(data)
            return
        if self.hidden:
            return
        if self.option is not None:
            self.option.append(data)
            return
        if self.open_tables:
            table = self.open_tables[-1]
            if table.cell is not None:
                table.cell.append(data)
            elif table.caption is not None:
                table.caption.append(data)
            return
        if self.heading is not None:
            self.heading[1].append(data)
            return
        self.parts.append(data)

    # Elements -----------------------------------------------------------------------------------------------------------
    def _hides(self, tag: str, attrs: dict[str, str]) -> bool:
        if tag in HIDING or "hidden" in attrs or attrs.get("aria-hidden") == "true":
            return True
        style = attrs.get("style", "").replace(" ", "").lower()
        return "display:none" in style or "visibility:hidden" in style

    def handle_starttag(self, tag: str, raw: list[tuple[str, str | None]]) -> None:
        if time.monotonic() > self.deadline:
            raise DashboardError("too_slow", "The dashboard took too long to read.")
        attrs = {k.lower(): (v or "") for k, v in raw}
        self._attributes(tag, attrs)
        if self.script is not None:
            return
        if tag == "body":
            while any(open_tag == "head" for open_tag, _ in self.stack):
                self._pop()
        closes = CLOSES.get(tag)
        if closes:
            while self.stack and self.stack[-1][0] in closes:
                self._pop()
        if tag in BLOCK and self.stack and self.stack[-1][0] == "p" and tag != "br":
            self._pop()
        if tag in VOID:
            if tag in ("br", "hr"):
                self._break()
            elif tag == "img":
                self.images += 1
            return
        hides = self._hides(tag, attrs)
        self.stack.append((tag, hides))
        if hides:
            self.hidden += 1
            if tag == "script":
                self._start_script(attrs)
            return
        if tag == "title" and not self.title_text:
            self.title = []
        elif tag in HEADINGS and not self.open_tables and not self.hidden:
            self.flush()
            self.heading = (HEADINGS[tag], [])
        elif tag == "table":
            if not self.open_tables:
                self.flush()
            self.open_tables.append(_Table(attrs.get("aria-label") or attrs.get("title") or None, self.last_heading))
        elif self.open_tables:
            self._table_start(tag, attrs)
        elif tag == "select":
            self.flush()
            self.select = []
        elif tag == "option" and self.select is not None:
            self.option = []
        elif tag == "canvas":
            self.canvases += 1
        elif tag in BLOCK:
            self._break()

    def _attributes(self, tag: str, attrs: dict[str, str]) -> None:
        if tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or attrs.get("itemprop") or "").lower()
            if key and attrs.get("content"):
                self.meta[key] = attrs["content"][:200]
        elif tag in ("iframe", "embed") and attrs.get("src"):
            self.refs.append(f"an embedded page or file ({attrs['src'][:200]})")
        elif tag == "object" and attrs.get("data"):
            self.refs.append(f"an embedded object ({attrs['data'][:200]})")
        elif tag == "link" and re.search(r"\.(json|csv|tsv|xml|txt)(\?|$)", attrs.get("href", ""), re.I):
            self.refs.append(f"a data file the page links to ({attrs['href'][:200]})")
        for key, value in attrs.items():
            if key.startswith("data-") and len(value) >= 12 and value.lstrip()[:1] in ("{", "["):
                self.attr_json.append((f"the {key} attribute of a {tag}" + (f" #{attrs['id'][:40]}" if attrs.get("id")
                                                                             else ""), value))

    def _start_script(self, attrs: dict[str, str]) -> None:
        source = attrs.get("src")
        if source:
            name = source.rsplit("/", 1)[-1][:120]
            if LIBRARY_SRC.search(name):
                self.libraries.append(name)
            else:
                self.refs.append(f"a script file ({source[:200]}), which may hold the data")
        if self.want_scripts:
            self.script = {"type": attrs.get("type", "").lower(), "id": attrs.get("id", ""), "src": source, "parts": []}

    def _table_start(self, tag: str, attrs: dict[str, str]) -> None:
        table = self.open_tables[-1]
        if tag == "caption":
            table.caption = []
        elif tag == "thead":
            table.in_head = True
        elif tag in ("tbody", "tfoot"):
            table.in_head = False
        elif tag == "tr":
            self._end_row(table)
            table.row, table.row_all_th = [], True
        elif tag in ("td", "th"):
            if table.row is None:
                table.row, table.row_all_th = [], True
            self._end_cell(table)

            def span(name: str) -> int:
                try:
                    return max(1, min(int(attrs.get(name, "1") or 1), 50))
                except ValueError:
                    return 1
            table.cell, table.cell_span = [], (span("colspan"), span("rowspan"))
            if tag == "td":
                table.row_all_th = False
        elif tag in BLOCK and table.cell is not None:
            table.cell.append(" ")

    def _end_cell(self, table: _Table) -> None:
        if table.cell is not None and table.row is not None:
            table.row.append((squash(" ".join(table.cell))[:CELL_CHARS], *table.cell_span))
        table.cell = None

    def _end_row(self, table: _Table) -> None:
        self._end_cell(table)
        if table.row:
            if table.in_head or table.row_all_th:
                table.header_rows.add(len(table.rows))
            table.rows.append(table.row)
        table.row = None

    def _break(self) -> None:
        if self.open_tables:
            table = self.open_tables[-1]
            if table.cell is not None:
                table.cell.append(" ")
            return
        if self.heading is None:
            self.flush()

    def _pop(self) -> None:
        tag, hides = self.stack.pop()
        if hides:
            self.hidden -= 1
            if tag == "script" and self.script is not None:
                self.script["text"] = "".join(self.script.pop("parts"))
                self.scripts.append(self.script)
                self.script = None
            return
        if tag == "title" and self.title is not None:
            self.title_text = squash("".join(self.title))[:300]
            self.title = None
        elif tag in HEADINGS and self.heading is not None and not self.open_tables:
            level, parts = self.heading
            self.heading = None
            text = squash(" ".join(parts))[:300]
            if text and self.chars < TEXT_CHARS:
                self.headings.append({"level": level, "text": text, "line": len(self.lines)})
                self.lines.append("#" * level + " " + text)
                self.chars += len(text) + level + 2
                self.last_heading = text
        elif tag == "table" and self.open_tables:
            table = self.open_tables.pop()
            self._end_row(table)
            if self.open_tables:
                outer = self.open_tables[-1]
                if outer.cell is not None:
                    outer.cell.append(" ")
            else:
                self.lines.append("")  # replaced by the table's placeholder
            self.tables.append((table, len(self.lines) - 1 if not self.open_tables else -1))
        elif self.open_tables:
            table = self.open_tables[-1]
            if tag == "caption" and table.caption is not None:
                table.caption_text = squash(" ".join(table.caption))[:200]
                table.caption = None
            elif tag in ("td", "th"):
                self._end_cell(table)
            elif tag == "tr":
                self._end_row(table)
            elif tag == "thead":
                self._end_row(table)
                table.in_head = False
        elif tag == "option" and self.option is not None and self.select is not None:
            text = squash(" ".join(self.option))
            if text:
                self.select.append(text[:60])
            self.option = None
        elif tag == "select" and self.select is not None:
            options, self.select = self.select, None
            if options:
                self.parts.append("[Choice: " + " | ".join(options[:15]) + (" …]" if len(options) > 15 else "]"))
                self.flush()
        elif tag in BLOCK:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if self.script is not None and tag != "script":
            return
        if any(open_tag == tag for open_tag, _ in self.stack):
            while self.stack:
                top = self.stack[-1][0]
                self._pop()
                if top == tag:
                    break
        elif tag in ("br", "p"):
            self._break()

    def finish(self) -> None:
        self.close()
        while self.stack:
            self._pop()
        self.flush()


def parse_page(html: str, deadline: float, scripts: bool = True) -> dict[str, Any]:
    """A page as data: title, the date it states, headings and visible text (tables shown as placeholders), tables as
    rows, the data in its scripts that parses as JSON, and what was not read. Nothing on the page is run or fetched."""
    parser = _PageParser(deadline, scripts)
    for start in range(0, len(html), 1 << 20):
        if time.monotonic() > deadline:
            raise DashboardError("too_slow", "The dashboard took too long to read.")
        parser.feed(html[start:start + (1 << 20)])
    parser.finish()
    tables: list[dict[str, Any]] = []
    for table, place in parser.tables:
        built = _table(table, len(tables) + 1)
        if built is None or len(tables) >= MAX_TABLES:
            continue
        tables.append(built)
        if place >= 0:
            parser.lines[place] = (f"[Table {built['id']}: {built['name']}, {built['total_rows']:,} row(s) × "
                                  f"{len(built['columns'])} column(s): read it with part '{built['id']}']")
    offsets: dict[int, int] = {}
    at = 0
    for index, line in enumerate(parser.lines):
        if line:
            offsets[index] = at
            at += len(line) + 1
    text = "\n".join(line for line in parser.lines if line)
    headings = [{"level": h["level"], "text": h["text"], "at": offsets.get(h["line"], 0)} for h in parser.headings]
    not_read: list[str] = list(dict.fromkeys(parser.refs))
    data: list[dict[str, Any]] = []
    found_dates: list[dict[str, Any]] = []
    if scripts:
        data, notes, found_dates = script_data(parser.scripts, parser.attr_json, deadline)
        not_read.extend(notes)
    if parser.images:
        not_read.append(f"{parser.images} picture(s): what an image shows is not read")
    if parser.canvases and not data:
        not_read.append(f"{parser.canvases} chart(s) drawn by the page's scripts whose data Wizard found no JSON for")
    if len(text) >= TEXT_CHARS:
        not_read.append(f"the visible text after its first {TEXT_CHARS:,} characters")
    title = parser.title_text or next((h["text"] for h in parser.headings if h["level"] <= 2), None) or (
        parser.headings[0]["text"] if parser.headings else None)
    return {"title": title, "headings": headings, "text": text, "tables": tables, "data": data,
            "libraries": sorted(set(parser.libraries))[:20], "not_read": not_read[:80],
            "as_of": stated_date(parser.title_text, text, parser.meta, found_dates)}


# Tables -----------------------------------------------------------------------------------------------------------------
NUMBER = re.compile(r"^(?P<prefix>[$€£¥₹]|[A-Z]{3}\s?)?(?P<number>\d{1,3}(?:[,\u00a0\u202f ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
                    r"\s*(?P<suffix>%|[kKmMbB]|bn|mn|BN|MN)?$")
EMPTY = {"", "-", "–", "—", "n/a", "na", "N/A", "NA", "..", "…"}


def number(text: str) -> tuple[float | int, str] | None:
    """A figure as a table shows it: 1,234 · -5.2% · (120) · $1.2M · AED 4,500. Returns (value, unit) or None."""
    value = text.strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    if value[:1] in ("-", "−", "–", "+"):
        negative, value = value[0] != "+", value[1:].strip()
    match = NUMBER.match(value)
    if not match:
        return None
    digits = match.group("number")
    plain = re.sub(r"[,\u00a0\u202f ]", "", digits)
    if len(plain) > 1 and plain.startswith("0") and not plain.startswith("0."):
        return None  # a code such as 00123, not a figure
    parsed: float | int = float(plain) if "." in plain else int(plain)
    if negative:
        parsed = -parsed
    unit = (match.group("prefix") or "").strip() + (match.group("suffix") or "")
    return parsed, unit


def column_key(label: str, taken: set[str], index: int) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")[:50] or f"column_{index}"
    if not key[0].isalpha():
        key = "c_" + key
    base, n = key, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    taken.add(key)
    return key


def typed_columns(labels: list[str], rows: list[list[Any]], parse_text: bool) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    """Columns with keys Check my data can name, and their figures as numbers where a column holds figures (its unit,
    such as % or $, kept on the column)."""
    taken: set[str] = set()
    columns = [{"key": column_key(label, taken, i + 1), "label": label or f"Column {i + 1}", "type": "string"}
               for i, label in enumerate(labels)]
    out = [list(row) for row in rows]
    for index, column in enumerate(columns):
        values = [row[index] for row in out if index < len(row)]
        filled = [v for v in values if v is not None and not (isinstance(v, str) and v.strip() in EMPTY)]
        if not filled:
            continue
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in filled):
            column["type"] = "number"
            continue
        if not parse_text:
            continue
        parsed = [number(v) if isinstance(v, str) else None for v in filled]
        units = {p[1] for p in parsed if p}
        if len(units) != 1 or sum(1 for p in parsed if p) < max(1, 0.8 * len(filled)):
            continue
        unit = units.pop()
        column["type"] = "percent" if unit == "%" else "number"
        if unit:
            column["unit"] = unit
        for row in out:
            if index < len(row):
                cell = row[index]
                found = number(cell) if isinstance(cell, str) else None
                row[index] = found[0] if found else (None if isinstance(cell, str) and cell.strip() in EMPTY else cell)
    return columns, out


def _grid(table: _Table) -> list[list[str]]:
    """Rows with colspan and rowspan laid out: a cell that spans rows (a market label over its products) is repeated on
    each; across columns, a header's text repeats and a value does not."""
    out: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # column -> (text, rows it still spans) from a rowspan above
    for index, row in enumerate(table.rows):
        header = index in table.header_rows
        line: list[str] = []
        cells = list(row)
        while cells or len(line) in pending:
            column = len(line)
            if column in pending:
                text, left = pending.pop(column)
                line.append(text)
                if left > 1:
                    pending[column] = (text, left - 1)
                continue
            text, colspan, rowspan = cells.pop(0)
            for k in range(colspan):
                if rowspan > 1:
                    pending[len(line)] = (text, rowspan - 1)
                line.append(text if k == 0 or header else "")
        out.append(line[:MAX_COLUMNS])
    return out


def _table(table: _Table, number_: int) -> dict[str, Any] | None:
    grid = _grid(table)
    if not grid:
        return None
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    heads = sorted(i for i in table.header_rows if i < len(grid))
    leading: list[int] = []
    for i in heads:
        if i == len(leading):
            leading.append(i)
    body = [r for i, r in enumerate(grid) if i not in leading and any(c for c in r)]
    if not leading and len(grid) > 1:
        first = grid[0]
        if all(c and number(c) is None for c in first) and any(number(c) for r in grid[1:] for c in r):
            leading, body = [0], [r for r in grid[1:] if any(c for c in r)]
    if not body or (width < 2 and len(body) < 2):
        return None
    labels = []
    for column in range(width):
        parts = list(dict.fromkeys(grid[i][column] for i in leading if grid[i][column]))
        labels.append(" / ".join(parts))
    columns, rows = typed_columns(labels, [list(r) for r in body[:MAX_ROWS]], parse_text=True)
    name = table.caption_text or table.label or table.heading or f"Table {number_}"
    return {"id": f"T{number_}", "name": name[:200], "columns": columns, "rows": rows, "total_rows": len(body)}


# Data in the page's scripts -------------------------------------------------------------------------------------------
STRUCT = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`|//[^\n]*|/\*.*?\*/|[{}\[\]()]', re.S)
ASSIGN = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*=(?![=>])\s*(?=[\[{]|JSON\.parse\s*\()")
CALL = re.compile(r"(?<![\w$])(Plotly\.(?:newPlot|react|plot|addTraces)|(?<=\.)setOption|new\s+Chart|"
                  r"Highcharts\.(?:chart|stockChart|mapChart|ganttChart)|vegaEmbed|JSON\.parse)\s*\(")
FETCHES = re.compile(r"(?<![\w$.])(fetch|d3\.(?:csv|tsv|json|text|xml|dsv)|Plotly\.d3\.(?:csv|json)|\$\.(?:getJSON|get|post|"
                     r"ajax)|axios\.(?:get|post)|import)\s*\(\s*(?:(['\"`])([^'\"`\n]{1,200})\2)?")
XHR = re.compile(r"\.open\(\s*['\"](?:GET|POST)['\"]\s*,\s*(?:(['\"`])([^'\"`\n]{1,200})\1)?")
BANNER = re.compile(r"/\*!|@license|\b(?:plotly\.js|echarts|chart\.js|highcharts|vega(?:-lite|-embed)?|d3js\.org|jquery|"
                    r"lodash|react)\b[^\n]{0,60}?v?\d+\.\d+", re.I)
JSON_TYPES = ("json",)
CODE_TYPES = ("", "text/javascript", "application/javascript", "module", "text/ecmascript", "application/ecmascript",
              "text/babel", "text/jsx")
ASOF_KEYS = re.compile(r"^(as_?of|as_?at|data_?as_?of|last_?updated?|updated(_?at|_?on)?|last_?refresh(ed)?|refreshed(_?at|_?on)?|"
                       r"report_?date|data_?date|snapshot_?date|generated(_?at|_?on)?|cut_?off(_?date)?)$", re.I)


class Code:
    """A value written as code in the page (a function, a call, a variable), not as data."""

    def __init__(self, what: str):
        self.what = what


class Ref(Code):
    """A variable the data refers to by name; resolved when the page sets that variable to data."""

    def __init__(self, name: str):
        super().__init__(f"the variable {name}")
        self.name = name


class NotData(ValueError):
    pass


def _close(text: str, start: int, pattern: re.Pattern[str] = STRUCT) -> int | None:
    """End of the bracketed literal or argument list opening at `start`, skipping strings and comments."""
    depth = 0
    for match in pattern.finditer(text, start):
        lexeme = match.group()
        if lexeme in ("{", "[", "("):
            depth += 1
        elif lexeme in ("}", "]", ")"):
            depth -= 1
            if depth == 0:
                return match.end()
    return None


def _arguments(text: str) -> list[str]:
    """A call's arguments (the text between its parentheses), split at the commas outside brackets and strings. Only
    brackets and strings are visited one by one; the commas inside a large data array are never looked at."""
    pieces: list[str] = []
    depth = start = last = 0

    def split(upto: int) -> None:
        nonlocal start
        found = text.find(",", max(start, last), upto)
        while found >= 0:
            pieces.append(text[start:found].strip())
            start = found + 1
            found = text.find(",", start, upto)

    for match in STRUCT.finditer(text):
        if depth == 0:
            split(match.start())
        token = match.group()
        if token in ("{", "[", "("):
            depth += 1
        elif token in ("}", "]", ")"):
            depth -= 1
        last = match.end()
    if depth == 0:
        split(len(text))
    pieces.append(text[start:].strip())
    return [p for p in pieces if p]


ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|.)", re.S)
SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_string(lexeme: str) -> str:
    if lexeme[0] == '"':
        try:
            return str(json.loads(lexeme))
        except ValueError:
            pass

    def unescape(match: re.Match[str]) -> str:
        code = match.group(1)
        if code.startswith("u{"):
            return chr(int(code[2:-1], 16))
        if code[0] in "ux" and len(code) > 1:
            return chr(int(code[1:], 16))
        if code in ("\n", "\r\n"):
            return ""
        return SIMPLE.get(code, code)
    return ESCAPE.sub(unescape, lexeme[1:-1])


LOOSE = re.compile(r"""
    (?P<space>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<string>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\$]|\\.|\$(?!\{))*`)
  | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?))
  | (?P<name>[A-Za-z_$][\w$]*)
  | (?P<punct>\.\.\.|=>|[{}\[\]():,.;=+\-*/?!<>&|%~^])
  | (?P<other>.)
""", re.S | re.X)
ENDS = {",", "}", "]", ")", ";", None}


class Loose:
    """A JavaScript value written as data (object and array literals with unquoted keys, single quotes, trailing commas
    and comments), read without running anything. A value written as code is kept as a Code marker and named."""

    def __init__(self, text: str):
        self.lexemes = [(m.lastgroup or "", m.group()) for m in LOOSE.finditer(text) if m.lastgroup != "space"]
        self.i = 0

    def peek(self, ahead: int = 0) -> tuple[str, str | None]:
        index = self.i + ahead
        return self.lexemes[index] if index < len(self.lexemes) else ("", None)

    def parse(self) -> Any:
        value = self.value()
        if self.peek()[1] not in (None, ";"):
            raise NotData("more follows the value")
        return value

    def value(self) -> Any:
        kind, lexeme = self.peek()
        if lexeme is None:
            raise NotData("the value ends early")
        if lexeme == "{":
            return self.object()
        if lexeme == "[":
            return self.array()
        if kind in ("string", "number") or lexeme in ("true", "false", "null", "undefined", "NaN", "Infinity"):
            if self.peek(1)[1] in ENDS:
                self.i += 1
                if kind == "string":
                    return js_string(lexeme)
                if kind == "number":
                    return int(lexeme, 16) if lexeme.lower().lstrip("-").startswith("0x") else (
                        float(lexeme) if any(c in lexeme for c in ".eE") else int(lexeme))
                return {"true": True, "false": False}.get(lexeme)
        return self.code()

    def code(self) -> Code:
        """Skip an expression up to the next comma or closing bracket, and say what it was."""
        start = self.i
        kind, lexeme = self.peek()
        depth = 0
        while True:
            _, current = self.peek()
            if current is None:
                break
            if current in ("(", "[", "{"):
                depth += 1
            elif current in (")", "]", "}"):
                if depth == 0:
                    break
                depth -= 1
            elif current in (",", ";") and depth == 0:
                break
            self.i += 1
        taken = [t for _, t in self.lexemes[start:self.i]]
        if kind == "name" and all(t == "." or re.match(r"^[A-Za-z_$][\w$]*$", t or "") for t in taken) and taken:
            return Ref("".join(t for t in taken if t))
        if "function" in taken or "=>" in taken:
            return Code("a function")
        if lexeme == "new" and len(taken) > 1:
            return Code(f"new {taken[1]}(...)")
        if kind == "name" and "(" in taken:
            return Code(f"a call to {''.join(taken[:taken.index('(')])}(...)")
        return Code("an expression")

    def object(self) -> dict[str, Any]:
        self.i += 1
        out: dict[str, Any] = {}
        while True:
            kind, lexeme = self.peek()
            if lexeme == "}":
                self.i += 1
                return out
            if lexeme == ",":
                self.i += 1
                continue
            if lexeme is None:
                raise NotData("an object is not closed")
            if lexeme == "...":
                self.i += 1
                self.code()
                continue
            if lexeme == "[":  # a computed key
                end = self._skip_brackets()
                if self.peek()[1] == ":":
                    self.i += 1
                    self.value()
                self.i = max(self.i, end)
                continue
            if kind not in ("name", "string", "number"):
                raise NotData(f"unexpected {lexeme!r} in an object")
            key = js_string(lexeme) if kind == "string" else lexeme
            self.i += 1
            following = self.peek()[1]
            if following == ":":
                self.i += 1
                out[key] = self.value()
            elif following in (",", "}"):
                out[key] = Ref(key)  # shorthand {sales}
            elif following == "(" or (kind == "name" and key in ("get", "set", "async")):
                self.code()  # a method
                if self.peek()[1] == "{":
                    self._skip_brackets()
                out[key] = Code("a function")
            else:
                raise NotData(f"unexpected {following!r} after a key")
            if self.peek()[1] not in (",", "}"):
                raise NotData("an object entry is not followed by , or }")

    def _skip_brackets(self) -> int:
        depth = 0
        while True:
            _, lexeme = self.peek()
            if lexeme is None:
                return self.i
            self.i += 1
            if lexeme in ("(", "[", "{"):
                depth += 1
            elif lexeme in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    return self.i

    def array(self) -> list[Any]:
        self.i += 1
        out: list[Any] = []
        while True:
            lexeme = self.peek()[1]
            if lexeme == "]":
                self.i += 1
                return out
            if lexeme is None:
                raise NotData("an array is not closed")
            if lexeme == ",":  # a hole
                self.i += 1
                out.append(None)
                continue
            out.append(self.value())
            following = self.peek()[1]
            if following == ",":
                self.i += 1
            elif following != "]":
                raise NotData("an array item is not followed by , or ]")


def literal(text: str) -> Any:
    """A value written in a page as data: strict JSON, else loosely (up to LOOSE_MAX). Raises NotData."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    if len(text) > LOOSE_MAX:
        raise NotData(f"{len(text) / 1024:,.0f} KB that is not strict JSON (too large to read loosely)")
    return Loose(text).parse()


def _arg(text: str, names: dict[str, Any]) -> Any:
    """One call argument: data, a string, a variable the page set to data, or Code."""
    head = text[:1]
    if head in ("{", "["):
        try:
            return literal(text)
        except NotData:
            return Code("data that is not JSON")
    if head in ("'", '"', "`") and len(text) >= 2 and text[-1] == head:
        return js_string(text)
    name = variable(text)
    if name:
        return Ref(name)  # resolved by _clean when the page sets it to data
    match = re.match(r"^JSON\.parse\s*\(\s*(['\"`].*['\"`])\s*\)$", text, re.S)
    if match:
        try:
            return json.loads(js_string(match.group(1)))
        except ValueError:
            return Code("JSON.parse of text that is not JSON")
    return Code("code")


def _typed_array(node: dict[str, Any]) -> Any:
    """Plotly's binary arrays ({"dtype": "f8", "bdata": "..."}, as plotly.py writes numpy data) as lists of numbers."""
    formats = {"f8": "d", "f4": "f", "i1": "b", "u1": "B", "u1c": "B", "i2": "h", "u2": "H", "i4": "i", "u4": "I",
               "i8": "q", "u8": "Q"}
    code = formats.get(str(node.get("dtype")))
    if code is None:
        return node
    try:
        raw = base64.b64decode(str(node["bdata"]))
        size = struct.calcsize("<" + code)
        values = list(struct.unpack(f"<{len(raw) // size}{code}", raw[:len(raw) - len(raw) % size]))
    except (ValueError, struct.error, KeyError):
        return node
    shape = node.get("shape")
    if isinstance(shape, str) and "," in shape:
        try:
            rows, cols = (int(p) for p in shape.split(",")[:2])
            return [values[r * cols:(r + 1) * cols] for r in range(rows)]
        except ValueError:
            return values
    return values


def variable(text: str) -> str | None:
    """The name a call argument or a value refers to (window.sales is sales), or None when it is not a plain name."""
    if not re.match(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$", text):
        return None
    return re.sub(r"^(?:window|self|globalThis|this)\.", "", text)


def _clean(value: Any, path: str, notes: list[str], names: dict[str, Any], used: set[int], depth: int = 0) -> Any:
    """Resolve variables the page set to data (marking them used), decode binary arrays, turn NaN into null, and name the
    code left out."""
    if isinstance(value, Ref):
        name = variable(value.name) or value.name
        if name in names and depth < 8:
            used.add(id(names[name]))
            return _clean(names[name], name, notes, names, used, depth + 1)
    if isinstance(value, Code):
        if len(notes) < 40:
            notes.append(f"{path or 'a value'}: {value.what}, not data")
        return None
    if isinstance(value, dict):
        if "bdata" in value and "dtype" in value:
            return _typed_array(value)
        return {k: _clean(v, f"{path}.{k}" if path else str(k), notes, names, used, depth) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v, f"{path}[{i}]", notes, names, used, depth) for i, v in enumerate(value)]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _first(node: Any) -> Any:
    return node[0] if isinstance(node, list) and node else node


def _title(node: Any) -> str | None:
    if isinstance(node, str):
        return squash(node)[:200] or None
    if isinstance(node, dict):
        return _title(node.get("text")) or _title(node.get("name"))
    if isinstance(node, list) and node:
        return _title(node[0])
    return None


def _items(node: Any, key: str) -> list[Any]:
    """node[key] when it is a list, else an empty list."""
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, list) else []


def _dig(node: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value[:CELL_CHARS] if isinstance(value, str) else value
    return json.dumps(value, ensure_ascii=False, default=str)[:CELL_CHARS]


def _point(item: Any, categories: list[Any] | None, position: int) -> tuple[Any, Any, Any]:
    """One point of a series as (x, y, value): a number with its category, [x, y] or [x, y, value], or an object."""
    def category() -> Any:
        return categories[position] if categories and position < len(categories) else position + 1
    if isinstance(item, list):
        if len(item) >= 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return item[0], item[1], None
        return category(), item[0] if item else None, None
    if isinstance(item, dict):
        y = item.get("y", item.get("value"))
        x = item.get("x", item.get("name", item.get("label", category())))
        if isinstance(y, list):
            return (y[0], y[1], y[2] if len(y) > 2 else None) if len(y) >= 2 else (x, y[0] if y else None, None)
        return x, y, None
    return category(), item, None


def _chart(name: str, library: str | None, chart: str | None, x_title: str | None, y_title: str | None,
           rows: list[list[Any]], where: str) -> dict[str, Any] | None:
    """Points of a chart as rows: series, x, y (and value for heat maps)."""
    if len(rows) < 1:
        return None
    third = any(len(r) > 3 and r[3] is not None for r in rows)
    labels = ["Series", x_title or "x", y_title or "y"] + (["Value"] if third else [])
    body = [[_cell(v) for v in (r if third else r[:3])] for r in rows[:MAX_ROWS]]
    columns, body = typed_columns(labels, body, parse_text=False)
    for column, key in zip(columns, ("series", "x", "y", "value"), strict=False):
        column["key"] = key  # fixed keys, whatever the axes are called, for Check my data
    return {"name": (chart or name)[:200], "library": library, "chart": chart, "x_title": x_title, "y_title": y_title,
            "columns": columns, "rows": body, "total_rows": len(rows), "where": where}


def _records(value: list[Any]) -> tuple[list[str], list[list[Any]]] | None:
    """An array of objects or of rows as a table: (labels, rows)."""
    items = [v for v in value if v is not None]
    if len(items) < 1:
        return None
    if all(isinstance(v, dict) for v in items):
        labels: list[str] = []
        for item in items[:2000]:
            for key in item:
                if key not in labels and len(labels) < MAX_COLUMNS:
                    labels.append(str(key))
        if not labels or not any(isinstance(v, int | float) or isinstance(v, str) for item in items[:50]
                                 for v in item.values()):
            return None
        return labels, [[_cell(item.get(k)) for k in labels] for item in items]
    if all(isinstance(v, list) for v in items) and len(items) >= 2:
        width = max(len(v) for v in items)
        if width < 1 or width > MAX_COLUMNS or any(isinstance(c, list | dict) for v in items[:50] for c in v):
            return None
        first = items[0]
        header = all(isinstance(c, str) for c in first) and any(isinstance(c, int | float) for v in items[1:5] for c in v)
        labels = [str(c) for c in first] + [""] * (width - len(first)) if header else [f"Column {i + 1}" for i in range(width)]
        body = items[1:] if header else items
        return labels, [[_cell(c) for c in v] + [None] * (width - len(v)) for v in body]
    numbers = [v for v in items if isinstance(v, int | float) and not isinstance(v, bool)]
    if len(items) >= 2 and len(numbers) >= max(2, 0.8 * len(items)):
        return ["Position", "Value"], [[i + 1, _cell(v)] for i, v in enumerate(value)]
    return None


def _table_data(name: str, labels: list[str], rows: list[list[Any]], where: str, chart: str | None = None,
                library: str | None = None) -> dict[str, Any]:
    columns, body = typed_columns(labels, rows[:MAX_ROWS], parse_text=False)
    return {"name": (chart or name)[:200], "library": library, "chart": chart, "x_title": None, "y_title": None,
            "columns": columns, "rows": body, "total_rows": len(rows), "where": where}


def _plotly(traces: Any, layout: Any, where: str, name: str) -> list[dict[str, Any]]:
    layout = layout if isinstance(layout, dict) else {}
    chart = _title(layout.get("title"))
    x_title, y_title = _title(_dig(layout, "xaxis", "title")), _title(_dig(layout, "yaxis", "title"))
    rows: list[list[Any]] = []
    for index, trace in enumerate(traces if isinstance(traces, list) else []):
        if not isinstance(trace, dict):
            continue
        label = str(trace.get("name") or f"Trace {index + 1}")
        xs, ys, z = _items(trace, "x"), _items(trace, "y"), _items(trace, "z")
        if isinstance(trace.get("values"), list):
            labels = _items(trace, "labels")
            rows += [[label, labels[i] if i < len(labels) else i + 1, v, None] for i, v in enumerate(trace["values"])]
        elif z and isinstance(z[0], list):
            for r, line in enumerate(z):
                rows += [[label, xs[c] if c < len(xs) else c + 1, ys[r] if r < len(ys) else r + 1, v]
                         for c, v in enumerate(line if isinstance(line, list) else [])]
        elif xs or ys:
            rows += [[label, xs[i] if i < len(xs) else (None if xs else i + 1), ys[i] if i < len(ys) else None, None]
                     for i in range(max(len(xs), len(ys)))]
    built = _chart(name, "Plotly", chart, x_title, y_title, rows, where)
    return [built] if built else []


def _series(option: dict[str, Any], library: str | None, where: str, name: str) -> list[dict[str, Any]]:
    """ECharts and Highcharts options (and charts shaped like them): series over category axes, and ECharts datasets."""
    chart = _title(option.get("title"))
    out: list[dict[str, Any]] = []
    for index, source in enumerate(_items(option, "dataset") or [option.get("dataset")]):
        if isinstance(source, dict) and isinstance(source.get("source"), list):
            table = _records(source["source"])
            if table:
                out.append(_table_data(f"{name} dataset {index + 1}", *table, where, chart, library))
    x_axis, y_axis = _first(option.get("xAxis")), _first(option.get("yAxis"))
    categories: list[Any] | None = None
    for axis in (x_axis, y_axis):
        if isinstance(axis, dict):
            found = axis.get("data") if isinstance(axis.get("data"), list) else axis.get("categories")
            if isinstance(found, list) and found:
                categories = [c.get("value") if isinstance(c, dict) else c for c in found]
                break
    if not categories and isinstance(_dig(option, "data", "labels"), list):
        categories = option["data"]["labels"]

    def axis_title(axis: Any) -> str | None:
        return (_title(axis.get("name")) or _title(axis.get("title"))) if isinstance(axis, dict) else None
    rows: list[list[Any]] = []
    for index, series in enumerate(_items(option, "series")):
        if not isinstance(series, dict) or not isinstance(series.get("data"), list):
            continue
        label = str(series.get("name") or f"Series {index + 1}")
        for position, item in enumerate(series["data"]):
            x, y, value = _point(item, categories, position)
            rows.append([label, x, y, value])
    built = _chart(name, library, chart, axis_title(x_axis), axis_title(y_axis), rows, where)
    return out + ([built] if built else [])


def _chartjs(config: dict[str, Any], where: str, name: str) -> list[dict[str, Any]]:
    found, given = config.get("data"), config.get("options")
    data: dict[str, Any] = found if isinstance(found, dict) else config
    options: dict[str, Any] = given if isinstance(given, dict) else {}
    labels = _items(data, "labels") or None
    chart = _title(_dig(options, "plugins", "title")) or _title(options.get("title"))
    x_title = _title(_dig(options, "scales", "x", "title")) or _title(_dig(_first(_dig(options, "scales", "xAxes")),
                                                                            "scaleLabel", "labelString"))
    y_title = _title(_dig(options, "scales", "y", "title")) or _title(_dig(_first(_dig(options, "scales", "yAxes")),
                                                                            "scaleLabel", "labelString"))
    rows: list[list[Any]] = []
    for index, series in enumerate(_items(data, "datasets")):
        if not isinstance(series, dict) or not isinstance(series.get("data"), list):
            continue
        label = str(series.get("label") or f"Dataset {index + 1}")
        for position, item in enumerate(series["data"]):
            x, y, value = _point(item, labels, position)
            rows.append([label, x, y, value])
    built = _chart(name, "Chart.js", chart, x_title, y_title, rows, where)
    return [built] if built else []


def _vega(spec: dict[str, Any], where: str, name: str, notes: list[str]) -> list[dict[str, Any]]:
    chart = _title(spec.get("title"))
    out: list[dict[str, Any]] = []
    sources: list[tuple[str, Any]] = []
    data = spec.get("data")
    for entry in data if isinstance(data, list) else [data]:
        if isinstance(entry, dict):
            if isinstance(entry.get("values"), list):
                sources.append((str(entry.get("name") or name), entry["values"]))
            elif entry.get("url"):
                notes.append(f"data the chart '{chart or name}' loads from {str(entry['url'])[:200]}")
    if isinstance(spec.get("datasets"), dict):
        sources += [(str(k), v) for k, v in spec["datasets"].items() if isinstance(v, list)]
    for label, values in sources:
        table = _records(values)
        if table:
            out.append(_table_data(label, *table, where, chart, "Vega"))
    for key in ("layer", "vconcat", "hconcat", "concat"):
        for sub in _items(spec, key):
            if isinstance(sub, dict):
                out += _vega(sub, where, name, notes)
    return out


def _detect(value: Any, where: str, name: str, notes: list[str], depth: int = 0) -> list[dict[str, Any]]:
    """Data sets in a value the page holds as data: a chart library's shape, else tables of records, rows or numbers."""
    if isinstance(value, list):
        if value and all(isinstance(t, dict) for t in value) and any(
                isinstance(t.get(k), list) for t in value for k in ("x", "y", "values", "z")):
            return _plotly(value, None, where, name)
        table = _records(value)
        return [_table_data(name, *table, where)] if table else []
    if not isinstance(value, dict) or depth > 4:
        return []
    if isinstance(value.get("data"), list) and isinstance(value.get("layout"), dict):
        return _plotly(value["data"], value["layout"], where, name)
    schema = str(value.get("$schema", ""))
    if "vega" in schema or ("mark" in value and ("encoding" in value or "data" in value)):
        return _vega(value, where, name, notes)
    if isinstance(_dig(value, "data", "datasets"), list) or isinstance(value.get("datasets"), list):
        return _chartjs(value, where, name)
    if isinstance(value.get("series"), list) or isinstance(_dig(value, "dataset", "source"), list):
        library = "Highcharts" if "chart" in value or isinstance(_dig(_first(value.get("xAxis")), "categories"), list) else (
            "ECharts" if any(k in value for k in ("xAxis", "yAxis", "grid", "tooltip", "legend", "dataset")) else None)
        return _series(value, library, where, name)
    out: list[dict[str, Any]] = []
    columns = {k: v for k, v in value.items() if isinstance(v, list) and v and not any(isinstance(c, dict | list) for c in v[:20])}
    lengths = {len(v) for v in columns.values()}
    if len(columns) >= 2 and len(lengths) == 1:
        labels = list(columns)[:MAX_COLUMNS]
        count = lengths.pop()
        out.append(_table_data(name, labels, [[_cell(columns[k][i]) for k in labels] for i in range(count)], where))
        rest = {k: v for k, v in value.items() if k not in columns}
    else:
        rest = value
    scalars = {k: v for k, v in rest.items() if isinstance(v, str | int | float | bool) or v is None}
    if len(scalars) >= 2 and any(isinstance(v, int | float) and not isinstance(v, bool) for v in scalars.values()):
        out.append(_table_data(name, ["Field", "Value"], [[k, _cell(v)] for k, v in scalars.items()], where))
    for key, child in rest.items():
        if isinstance(child, list | dict) and key not in scalars:
            out += _detect(child, where, f"{name}.{key}", notes, depth + 1)
    return out


def _call_data(kind: str, args: list[Any], where: str, notes: list[str]) -> list[dict[str, Any]]:
    if kind.startswith("Plotly."):
        if len(args) >= 2 and isinstance(args[1], dict) and "data" in args[1]:
            return _plotly(args[1].get("data"), args[1].get("layout"), where, "Plotly chart")
        return _plotly(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None, where, "Plotly chart")
    if kind == "setOption":
        return _series(args[0], "ECharts", where, "ECharts chart") if args and isinstance(args[0], dict) else []
    if kind.startswith("new"):
        return _chartjs(args[1], where, "Chart.js chart") if len(args) > 1 and isinstance(args[1], dict) else []
    if kind.startswith("Highcharts."):
        config = next((a for a in args if isinstance(a, dict)), None)
        return _series(config, "Highcharts", where, "Highcharts chart") if config else []
    if kind == "vegaEmbed":
        spec = args[1] if len(args) > 1 else None
        if isinstance(spec, str):
            notes.append(f"the chart spec the page loads from {spec[:200]}")
            return []
        return _vega(spec, where, "Vega chart", notes) if isinstance(spec, dict) else []
    return []


def _dates_in(value: Any, found: list[dict[str, Any]], depth: int = 0) -> None:
    if not isinstance(value, dict) or depth > 2 or len(found) >= 5:
        return
    for key, child in value.items():
        if isinstance(child, str) and ASOF_KEYS.match(str(key)):
            match = ANY_DATE.search(child)
            parsed = read_date(match) if match else None
            if parsed:
                found.append({"date": parsed[0], "from": "the page's data", "text": f"{key}: {child[:60]}",
                              **({"note": parsed[1]} if parsed[1] else {})})
        elif isinstance(child, dict):
            _dates_in(child, found, depth + 1)


def script_data(scripts: list[dict[str, Any]], attributes: list[tuple[str, str]], deadline: float
                ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """The data sets in a page's scripts and data attributes, what was not read, and dates the data states."""
    datasets: list[dict[str, Any]] = []
    notes: list[str] = []
    dates: list[dict[str, Any]] = []
    names: dict[str, Any] = {}
    assigned: list[tuple[str, Any, str]] = []
    calls: list[tuple[str, list[Any], str]] = []
    for number_, script in enumerate(scripts, 1):
        text = script.get("text") or ""
        kind = script.get("type") or ""
        where = f"script {number_}" + (f" #{script['id'][:40]}" if script.get("id") else "")
        if not text.strip():
            continue
        if time.monotonic() > deadline:
            raise DashboardError("too_slow", "The dashboard's scripts took too long to read.")
        if any(t in kind for t in JSON_TYPES) and "importmap" not in kind:
            try:
                assigned.append((script.get("id") or f"JSON data {number_}", _strict(text), where))
            except NotData:
                notes.append(f"{where}: marked as JSON but is not")
            continue
        if kind not in CODE_TYPES:
            continue  # a template, a shader or another language: not data
        if BANNER.search(text[:3000]) or (len(text) > 200_000 and text.count("function") > len(text) / 2000):
            continue  # a chart or utility library inlined in the page, not its data
        for match in FETCHES.finditer(text):
            notes.append(f"data the page loads with {match.group(1)}(" + (f"'{match.group(3)}'" if match.group(3) else
                                                                          "an address built in its script") + ")")
        for match in XHR.finditer(text):
            notes.append("data the page loads with XMLHttpRequest from " + (match.group(2) or "an address built in its script"))
        spans: list[tuple[int, int]] = []
        found_here = 0
        for match in CALL.finditer(text):
            if time.monotonic() > deadline:
                raise DashboardError("too_slow", "The dashboard's scripts took too long to read.")
            paren = match.end() - 1
            end = _close(text, paren)
            if end is None:
                continue
            spans.append((paren, end))
            kind_ = re.sub(r"\s+", " ", match.group(1))
            calls.append((kind_, [text[paren + 1:end - 1]], f"{where}, {kind_}"))
        for match in ASSIGN.finditer(text):
            if found_here >= 400 or time.monotonic() > deadline:
                break
            start = match.end()
            if any(a <= start < b for a, b in spans):
                continue
            name = re.sub(r"^(?:window|self|globalThis|this)\.", "", match.group(1))
            if text.startswith("JSON.parse", start):
                paren = text.index("(", start)
                end = _close(text, paren)
                if end is None:
                    continue
                raw = text[paren + 1:end - 1].strip()
                value = _arg(f"JSON.parse({raw})", names)
            else:
                end = _close(text, start)
                if end is None:
                    continue
                try:
                    value = literal(text[start:end])
                except NotData as error:
                    if end - start > 2000:
                        notes.append(f"{where}: {name} ({(end - start) / 1024:,.0f} KB) is script data that is not JSON "
                                     f"({error})")
                    continue
            found_here += 1
            spans.append((start, end))
            names[name] = value
            names.setdefault(name.rsplit(".", 1)[-1], value)
            assigned.append((name, value, f"{where}, {name}"))
    for where, raw in attributes:
        try:
            assigned.append((where, _strict(raw), where))
        except NotData:
            continue
    used: set[int] = set()
    for kind_, (raw,), where in calls:
        values: list[Any] = []
        element = kind_ not in ("setOption", "JSON.parse")  # the others take the chart's element first
        for index, piece in enumerate(_arguments(raw)):
            value = _arg(piece, names)
            if element and index == 0 and isinstance(value, Code):
                values.append(None)
                continue
            if isinstance(value, Ref) and value.name not in names:
                if not (element and index == 0):
                    notes.append(f"{where}: its data is {value.what}, which the page does not set as data")
                values.append(None)
                continue
            values.append(_clean(value, f"{kind_} argument {index + 1}", notes, names, used))
        datasets += _call_data(kind_, values, where, notes)
    # Variables that hold data, each read once: a chart or another variable that uses one reads it there.
    cleaned_values = []
    for name, value, where in assigned:
        if id(value) in used:
            continue
        own: list[str] = []
        cleaned_values.append((name, _clean(value, name, own, names, used), where, id(value), own))
    for name, cleaned, where, identity, own in cleaned_values:
        if identity in used:
            continue
        notes.extend(own)
        _dates_in(cleaned, dates)
        datasets += _detect(cleaned, where, name, notes)
    kept = [d for d in datasets if d and d.get("rows")]
    out = []
    for index, item in enumerate(kept[:MAX_DATASETS], 1):
        out.append({"id": f"D{index}", **item})
    if len(kept) > MAX_DATASETS:
        notes.append(f"{len(kept) - MAX_DATASETS} more data sets after the first {MAX_DATASETS}")
    return out, list(dict.fromkeys(notes)), dates


def _strict(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        raise NotData("not JSON") from None


# The date a page states -----------------------------------------------------------------------------------------------
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}
MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE = (r"(?P<iso>\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)"
        r"|(?P<ymd>\d{4}/\d{1,2}/\d{1,2})"
        r"|(?P<dmy>\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2}))"
        rf"|(?P<dmony>\d{{1,2}}(?:st|nd|rd|th)?[\s\-]+{MONTH}\.?[\s\-,]+\d{{4}})"
        rf"|(?P<mondy>{MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})"
        rf"|(?P<mony>{MONTH}\.?[\s\-]+\d{{4}})")
ANY_DATE = re.compile(rf"(?<![\w/.-])(?:{DATE})(?![\d/])", re.I)
STATED = re.compile(r"\b(?:data\s+)?(?:as\s+(?:of|at|on)|(?:last\s+)?updated(?:\s+(?:on|at))?|(?:last\s+)?refresh(?:ed)?"
                    r"(?:\s+(?:on|at))?|data\s+(?:up\s+)?(?:to|until|through|thru)|(?:report(?:ing)?|data|snapshot|"
                    r"extract(?:ion)?|cut-?off)\s+date|generated(?:\s+(?:on|at))?|valid\s+(?:as\s+)?(?:of|on))\b"
                    r"\s*[:\-–—]?\s*", re.I)
META_KEYS = ("as-of", "asof", "data-as-of", "report-date", "date", "last-modified", "dcterms.modified", "dc.date",
             "article:modified_time", "revised")


def read_date(match: re.Match[str]) -> tuple[str, str | None] | None:
    """(ISO date, a note on how it was read) for a date as pages write it; None when it is not a real date."""
    groups = match.groupdict()
    note = None
    try:
        if groups.get("iso"):
            text = groups["iso"]
            day_part, _, clock = text.replace("T", " ").partition(" ")
            y, m, d = (int(p) for p in day_part.split("-"))
            found = date(y, m, d).isoformat()
            if clock:
                hours, minutes = (int(p) for p in clock.split(":")[:2])
                if hours < 24 and minutes < 60:
                    found += f"T{hours:02d}:{minutes:02d}"
            return found, None
        if groups.get("ymd"):
            y, m, d = (int(p) for p in groups["ymd"].split("/"))
            return date(y, m, d).isoformat(), None
        if groups.get("dmy"):
            a, b, c = (int(p) for p in re.split(r"[/.\-]", groups["dmy"]))
            year = c + 2000 if c < 100 else c
            if a > 12:
                d, m = a, b
            elif b > 12:
                m, d = a, b
                note = "read as month/day/year"
            else:
                d, m = a, b
                note = "read as day/month/year" if a != b else None
            return date(year, m, d).isoformat(), note
        words = re.findall(r"[A-Za-z]+|\d+", groups.get("dmony") or groups.get("mondy") or groups.get("mony") or "")
        numbers = [int(w) for w in words if w.isdigit()]
        month = next((MONTHS[w[:3].lower()] for w in words if w[:3].lower() in MONTHS), None)
        if month is None or not numbers:
            return None
        year = max(numbers)
        if groups.get("mony"):
            date(year, month, 1)
            return f"{year:04d}-{month:02d}", None
        day = min(numbers)
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None


def stated_date(title: str, text: str, meta: dict[str, str], data_dates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The date the page says its figures are as of: words such as "as of", "updated", "data to" before a date in its
    title or text, else its metadata, else its data, else a date in its title. None when it states none."""
    for where, body in (("the page's title", title), ("the page", text[:200_000])):
        for words in STATED.finditer(body or ""):
            match = ANY_DATE.match(body, words.end())
            parsed = read_date(match) if match else None
            if parsed:
                snippet = squash(body[words.start():match.end()])[:120] if match else ""
                return {"date": parsed[0], "from": where, "text": snippet, **({"note": parsed[1]} if parsed[1] else {})}
    for key in META_KEYS:
        if meta.get(key):
            match = ANY_DATE.search(meta[key])
            parsed = read_date(match) if match else None
            if parsed:
                return {"date": parsed[0], "from": "the page's metadata", "text": f"{key}: {meta[key][:60]}"}
    if data_dates:
        return data_dates[0]
    match = ANY_DATE.search(title or "")
    parsed = read_date(match) if match else None
    if parsed and match:
        return {"date": parsed[0], "from": "the page's title", "text": squash(title)[:120],
                **({"note": parsed[1]} if parsed[1] else {})}
    return None


# One part of a read dashboard -----------------------------------------------------------------------------------------
TEXT_PAGE = 12_000  # characters of text a read returns
ROWS_PAGE = 500  # rows of a table or data set a read returns (an evidence item holds at most 500)
PART_BYTES = 200_000  # and at most about this much of them
PART = re.compile(r"^[TD][0-9]{1,4}$")


def _sha(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parts_of(page: dict[str, Any]) -> str:
    names = ["text", *(t["id"] for t in page.get("tables", [])[:30]), *(d["id"] for d in page.get("data", [])[:30])]
    headings = [h["text"] for h in page.get("headings", [])[:20]]
    return ", ".join(names) + ("; or a heading: " + "; ".join(headings) if headings else "")


def find_part(page: dict[str, Any], part: str) -> tuple[str, Any]:
    """("text", None), ("section", heading index), ("table" | "data", the item) for a part's name."""
    key = squash(part)
    if key.casefold() in ("text", "all text", "page", "visible text"):
        return "text", None
    if PART.match(key.upper()):
        pool = page.get("tables", []) if key.upper()[0] == "T" else page.get("data", [])
        item = next((x for x in pool if x["id"] == key.upper()), None)
        if item is None:
            raise DashboardError("unknown_part", f"This dashboard has no part {key.upper()}. Parts: {parts_of(page)}.")
        return ("table" if key.upper()[0] == "T" else "data"), item
    wanted = key.casefold()
    headings = page.get("headings", [])
    index = next((i for i, h in enumerate(headings) if squash(h["text"]).casefold().startswith(wanted)), None)
    if index is None:
        index = next((i for i, h in enumerate(headings) if wanted in h["text"].casefold()), None)
    if index is None:
        raise DashboardError("unknown_part", f"No part '{part}' in this dashboard. Parts: {parts_of(page)}.")
    return "section", index


def read_part(page: dict[str, Any], part: str, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    """One part of a read dashboard from `offset` (characters of text, or rows): the visible text, the text under a
    heading, or a table's or data set's rows. `limit` repeats an earlier read exactly (Check my data)."""
    kind, found = find_part(page, part)
    if kind in ("text", "section"):
        text = page.get("text", "")
        if kind == "text":
            start, end, name = 0, len(text), "Visible text"
        else:
            heading = page["headings"][found]
            start, name = heading["at"], heading["text"]
            end = next((h["at"] for h in page["headings"][found + 1:] if h["level"] <= heading["level"]), len(text))
        size = limit or TEXT_PAGE
        position = start + offset
        chunk = text[position:min(end, position + size)]
        following = offset + len(chunk) if position + len(chunk) < end else None
        return {"kind": "text", "part": "text" if kind == "text" else name, "name": name, "content": chunk,
                "offset": offset, "limit": size, "next_offset": following, "digest": _sha(chunk)}
    rows = found.get("rows", [])
    if limit is not None:
        chosen = rows[offset:offset + limit]
    else:
        chosen, used = [], 0
        for row in rows[offset:offset + ROWS_PAGE]:
            used += len(json.dumps(row, ensure_ascii=False, default=str))
            if chosen and used > PART_BYTES:
                break
            chosen.append(row)
    following = offset + len(chosen) if offset + len(chosen) < len(rows) else None
    return {"kind": kind, "part": found["id"], "name": found["name"], "item": found, "columns": found["columns"],
            "rows": chosen, "offset": offset, "limit": len(chosen), "next_offset": following,
            "total_rows": found.get("total_rows", len(rows)), "kept_rows": len(rows),
            "digest": _sha({"columns": found["columns"], "rows": chosen})}


def replay(folder: Dashboards, request: dict[str, Any], digest: str) -> tuple[str, str]:
    """Read the same part of the same dashboard again (Check my data): UNCHANGED, CHANGED or UNAVAILABLE."""
    try:
        item = folder.find(str(request.get("path") or request.get("dashboard") or ""))
        again = read_part(folder.page(item), str(request.get("part") or "text"), int(request.get("offset") or 0),
                          int(request.get("limit") or 0) or None)
    except DashboardError as error:
        return "UNAVAILABLE", error.message
    if again["digest"] == digest:
        return "UNCHANGED", "the dashboard shows the same figures today"
    return "CHANGED", "the dashboard now shows different figures than when the answer was prepared"

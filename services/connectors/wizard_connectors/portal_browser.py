"""Wizard's own browser for the company portals (GSCM, ASAP, the Big Data Portal): decision 2026-10-20-portal-browser.

Gemini explores a portal one step per tool call, the way a person does: open the portal, read the numbered list of what
can be clicked, click a folder, answer a prompt, read the table that comes back. The browser is this PC's Microsoft Edge
(Chromium elsewhere) driven by Playwright, with a browser profile that belongs to Wizard and to this person. They sign in
to each portal themselves, in a visible window (`start_signin`); the session stays in that profile. Nothing is copied
from their everyday browser, and no one else's sign-in is ever used.

The boundary is enforced here, not in Gemini's instructions:
- pages load only from the portal's own hosts and the configured sign-in hosts; any other page is stopped before it loads;
- no downloads, uploads, printing or dialogs; a pop-up on another host is closed;
- a click on a control whose name says it changes or sends something (save, delete, export, share, subscribe...) is
  refused, and text goes only into plain text, search and select fields: never passwords, code editors or rich text;
- every step has a time limit and a run takes at most MAX_STEPS steps.
Each step shows the person a screenshot with its target outlined (`show`), and returns the page's text and controls to
Gemini as untrusted data."""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .fixture_source import SourceError

log = logging.getLogger("wizard.portal")

PAGE_JS = (Path(__file__).with_name("portal_page.js")).read_text(encoding="utf-8")
VIEWPORT = {"width": 1280, "height": 800}
MAX_STEPS = 60  # per run: a backstop against a run that wanders, far above a normal exploration
ELEMENT_LIMIT = 150
TEXT_LIMIT = 9000
NAVIGATION_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
CALL_TIMEOUT_S = 150
IDLE_CLOSE_S = 15 * 60
# Company sign-in pages a portal may pass through when its session is renewed. Anything else is added per portal.
DEFAULT_SIGNIN_HOSTS = ("login.microsoftonline.com", "login.microsoft.com", "login.live.com", "login.windows.net",
                        "*.okta.com", "*.oktapreview.com", "*.pingone.com", "*.pingidentity.com", "*.duosecurity.com")
# A control whose name starts with one of these changes, sends or exports something: Wizard never clicks it.
REFUSED_VERBS = re.compile(
    r"^(delete|remove|save|export|download|share|send|e-?mail|subscribe|unsubscribe|schedule|publish|upload|import|"
    r"edit|rename|move|duplicate|copy to|certify|approve|reject|print|sign ?out|log ?out|logout|request access|"
    r"reset|discard|archive|restore|submit for|favou?rite|unfavou?rite|add to|remove from|bookmark)\b", re.IGNORECASE)
# Only refused on buttons and menu items ("New Zealand" is a market, "New dossier" creates one).
REFUSED_BUTTON_VERBS = re.compile(r"^(new|create|add|insert|clone|copy)\b", re.IGNORECASE)
# A link whose address names an export or a sign-out as a whole path segment or parameter ("/folders/market-share" is fine).
REFUSED_HREF = re.compile(r"(?:^|[/?&=])(export|download|delete|subscribe|upload|logout|signout|sign-out)(?:$|[/?&=.])",
                          re.IGNORECASE)
BUTTON_KINDS = {"button", "menuitem", "menuitemcheckbox", "menuitemradio", "clickable", "switch"}
TYPEABLE = {"text", "combobox", "searchbox", "textbox", "select"}
PORTAL_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

DESCRIBE_JS = """el => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const form = el.closest('form');
  return {tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
          role: el.getAttribute('role') || '', href: el.getAttribute('href') || '', download: el.hasAttribute('download'),
          editable: el.isContentEditable,
          editor: !!el.closest('.ace_editor, .monaco-editor, .CodeMirror, .cm-editor, [data-mode="sql"]'),
          name: clean(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.value || '').slice(0, 100),
          form_action: form ? (form.getAttribute('action') || '') : ''};
}"""

TABLE_JS = """(el, maxRows) => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  let rows;
  if (el.tagName === 'TABLE') {
    rows = [...el.rows].map(r => ({head: r.parentElement.tagName === 'THEAD' || [...r.cells].every(c => c.tagName === 'TH'),
                                   cells: [...r.cells].map(c => clean(c.innerText))}));
  } else {
    rows = [...el.querySelectorAll('[role=row]')].map(r => {
      const cells = [...r.querySelectorAll('[role=columnheader], [role=rowheader], [role=gridcell], [role=cell]')]
        .filter(c => c.closest('[role=row]') === r);
      return {head: cells.length > 0 && cells.every(c => c.getAttribute('role') === 'columnheader'),
              cells: cells.map(c => clean(c.innerText))};
    });
  }
  rows = rows.filter(r => r.cells.some(Boolean));
  const head = rows.filter(r => r.head);
  const body = rows.filter(r => !r.head);
  return {header: head.length ? head[head.length - 1].cells : [], rows: body.slice(0, maxRows).map(r => r.cells),
          rows_drawn: body.length, rows_declared: Number(el.getAttribute('aria-rowcount') || 0) || null,
          caption: clean(el.querySelector('caption')?.innerText || el.getAttribute('aria-label') || '').slice(0, 100)};
}"""


class PortalError(SourceError):
    """A portal step that could not run; the code and message go back to Gemini (and the person) as a tool error."""


@dataclass(frozen=True)
class Portal:
    id: str
    name: str
    start_url: str
    hosts: frozenset[str]

    @classmethod
    def make(cls, portal_id: str, start_url: str, name: str | None = None, extra_hosts: list[str] | None = None) -> Portal:
        if not PORTAL_ID.match(portal_id):
            raise ValueError(f"portal id {portal_id!r} must be lower-case letters, digits or '-'")
        parts = urlsplit(start_url)
        loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")  # a test or demo portal on this PC
        if not parts.hostname or not (parts.scheme == "https" or (parts.scheme == "http" and loopback)):
            raise ValueError(f"{portal_id}: the portal address must start with https:// (got {start_url!r})")
        hosts = {parts.hostname.lower(), *(h.strip().lower() for h in (extra_hosts or []) if h.strip())}
        return cls(portal_id, name or portal_id.upper(), start_url, frozenset(hosts))

    def allows(self, host: str | None) -> bool:
        return bool(host) and host_matches(host or "", self.hosts)


def host_matches(host: str, patterns: frozenset[str] | tuple[str, ...]) -> bool:
    host = host.lower()
    return any(host == p or (p.startswith("*.") and host.endswith(p[1:])) for p in patterns)


@dataclass(frozen=True)
class BrowserOptions:
    browser: str = "auto"  # auto | msedge | chrome | chromium | a path to a Chromium-based browser
    visible: bool = False  # show the browser window during runs too (troubleshooting); the preview works either way
    signin_hosts: tuple[str, ...] = DEFAULT_SIGNIN_HOSTS


@dataclass
class Frame:
    """One screenshot for the person: what the page looked like and what Wizard was about to do on it."""
    image: bytes
    portal: str
    phase: str  # "before" an action (target outlined) or "after" it
    action: str
    url: str
    title: str
    target: dict[str, float] | None = None
    viewport: dict[str, int] = field(default_factory=lambda: dict(VIEWPORT))


Show = Callable[[Frame], None]


@dataclass
class _Session:
    """One person's browser: a persistent context on their Wizard profile, one tab per portal."""
    context: Any = None
    signin: Any = None  # the visible sign-in window's context while it is open
    pages: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, dict[int, Any]] = field(default_factory=dict)  # portal -> element/table number -> frame
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    names: dict[str, dict[int, str]] = field(default_factory=dict)  # portal -> element/table number -> its name
    trail: dict[str, list[str]] = field(default_factory=dict)
    steps: dict[str, int] = field(default_factory=dict)
    state: dict[str, str] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)
    popups: list[Any] = field(default_factory=list)
    loading: dict[int, int] = field(default_factory=dict)  # page -> navigation requests in flight in its main frame
    last_used: float = 0.0


class PortalBrowser:
    """All portal browsing for this Wizard service. Playwright's sync API is bound to one thread, so every step runs on
    a single worker thread; tool calls wait for their step (they run one at a time per run anyway)."""

    def __init__(self, portals: list[Portal], options: BrowserOptions, profile_dir: Callable[[str], Path]):
        self.portals = {p.id: p for p in portals}
        self.options = options
        self.profile_dir = profile_dir
        self._sessions: dict[str, _Session] = {}
        self._jobs: queue.Queue[tuple[Callable[[], Any], Future[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._playwright: Any = None
        self._lock = threading.Lock()

    # Worker thread ----------------------------------------------------------------------------------------------------
    def _call(self, job: Callable[[], Any], timeout: float = CALL_TIMEOUT_S) -> Any:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, name="wizard-portal-browser", daemon=True)
                self._thread.start()
        future: Future[Any] = Future()
        self._jobs.put((job, future))
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            raise PortalError("portal_timeout", "The portal did not respond in time. Try again, or open a smaller page.") from None

    def _work(self) -> None:
        while True:
            try:
                item = self._jobs.get(timeout=60)
            except queue.Empty:
                self._close_idle()
                continue
            if item is None:
                self._shutdown()
                return
            job, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(job())
            except PortalError as error:
                future.set_exception(error)
            except Exception as error:  # noqa: BLE001 - every failure reaches the tool as a readable error
                log.warning("portal step failed: %s: %s", type(error).__name__, error)
                future.set_exception(PortalError("portal_error", _short(error)))
            self._close_idle()

    def _pw(self) -> Any:
        if self._playwright is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise PortalError("browser_unavailable", "Wizard's portal browser is not installed in this copy of Wizard "
                                                         "(the playwright package is missing).") from None
            self._playwright = sync_playwright().start()
        return self._playwright

    def _close_idle(self) -> None:
        now = time.monotonic()
        for session in self._sessions.values():
            if session.context is not None and now - session.last_used > IDLE_CLOSE_S:
                self._close_context(session)

    def _close_context(self, session: _Session) -> None:
        context, session.context = session.context, None
        session.pages.clear()
        session.refs.clear()
        session.tables.clear()
        session.popups.clear()
        if context is not None:
            try:
                context.close()
            except Exception:  # noqa: BLE001, S110 - the browser may already be gone
                pass

    def _shutdown(self) -> None:
        for session in self._sessions.values():
            self._close_context(session)
            if session.signin is not None:
                try:
                    session.signin.close()
                except Exception:  # noqa: BLE001, S110
                    pass
                session.signin = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001, S110
                pass
            self._playwright = None

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._jobs.put(None)
            self._thread.join(timeout=20)

    # Launching --------------------------------------------------------------------------------------------------------
    def _launch_options(self, headless: bool) -> dict[str, Any]:
        choice = self.options.browser.strip() or "auto"
        options: dict[str, Any] = {"headless": headless, "accept_downloads": False, "service_workers": "block",
                                   "args": ["--disable-features=Translate", "--no-first-run", "--no-default-browser-check"]}
        if choice == "auto":
            if sys.platform == "win32":
                options["channel"] = "msedge"
        elif choice in ("msedge", "chrome"):
            options["channel"] = choice
        elif choice != "chromium":
            options["executable_path"] = choice
        return options

    def _browser_name(self) -> str:
        choice = self.options.browser.strip() or "auto"
        return {"auto": "Microsoft Edge" if sys.platform == "win32" else "Chromium", "msedge": "Microsoft Edge",
                "chrome": "Google Chrome", "chromium": "Chromium"}.get(choice, choice)

    def _session(self, user_id: str) -> _Session:
        return self._sessions.setdefault(user_id, _Session())

    def _context(self, user_id: str) -> Any:
        session = self._session(user_id)
        session.last_used = time.monotonic()
        if session.signin is not None:
            if _closed(session.signin):
                session.signin = None
            else:
                raise PortalError("signin_open", "The portal sign-in window is still open. Finish signing in and close it "
                                                 "(or press Done in Wizard), then ask again.")
        if session.context is not None and not _closed(session.context):
            return session.context
        session.context = None
        profile = self.profile_dir(user_id)
        profile.mkdir(parents=True, exist_ok=True)
        try:
            context = self._pw().chromium.launch_persistent_context(
                str(profile), viewport=VIEWPORT, **self._launch_options(headless=not self.options.visible))
        except PortalError:
            raise
        except Exception as error:  # noqa: BLE001
            raise PortalError("browser_unavailable", f"Wizard could not start {self._browser_name()} for the portals: "
                                                     f"{_short(error)}") from None
        context.set_default_timeout(ACTION_TIMEOUT_MS)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        context.add_init_script("window.print = () => {};")
        context.route("**/*", lambda route, request: self._route(session, route, request))
        context.on("page", lambda page: self._new_page(session, page))
        for page in list(context.pages):  # a persistent context opens with a blank tab
            page.close()
        session.context = context
        return context

    def _allowed_document(self, host: str | None) -> bool:
        if not host:
            return False
        return any(p.allows(host) for p in self.portals.values()) or host_matches(host, self.options.signin_hosts)

    def _route(self, session: _Session, route: Any, request: Any) -> None:
        url = request.url
        if (request.resource_type == "document" or request.is_navigation_request()) and url.startswith(("http:", "https:")):
            host = urlsplit(url).hostname
            if not self._allowed_document(host):
                session.notices.append(f"Stopped a page on {host} from loading: it is not one of the portals' hosts. If it "
                                       "is the company sign-in page, add it to WIZARD_PORTAL_SIGNIN_HOSTS (Settings → "
                                       "Portals).")
                route.abort("blockedbyclient")
                return
        route.continue_()

    def _new_page(self, session: _Session, page: Any) -> None:
        page.on("dialog", lambda dialog: self._dialog(session, dialog))
        page.on("download", lambda download: self._download(session, download))
        page.on("request", lambda request: self._navigating(session, page, request, 1))
        page.on("requestfinished", lambda request: self._navigating(session, page, request, -1))
        page.on("requestfailed", lambda request: self._navigating(session, page, request, -1))
        session.popups.append(page)

    @staticmethod
    def _navigating(session: _Session, page: Any, request: Any, delta: int) -> None:
        try:
            if not (request.is_navigation_request() and request.frame == page.main_frame):
                return
        except Exception:  # noqa: BLE001 - a request without a frame (a worker's) is not a navigation
            return
        session.loading[id(page)] = max(0, session.loading.get(id(page), 0) + delta)

    @staticmethod
    def _dialog(session: _Session, dialog: Any) -> None:
        session.notices.append(f"The page showed a message box ({_short(dialog.message, 120)}); Wizard dismissed it.")
        try:
            dialog.dismiss()
        except Exception:  # noqa: BLE001, S110
            pass

    @staticmethod
    def _download(session: _Session, download: Any) -> None:
        session.notices.append("The page tried to download a file; Wizard does not download files.")
        try:
            download.cancel()
        except Exception:  # noqa: BLE001, S110
            pass

    def _page(self, user_id: str, portal: Portal, create: bool) -> Any:
        session = self._session(user_id)
        context = self._context(user_id)
        page = session.pages.get(portal.id)
        if page is not None and not page.is_closed():
            return page
        if not create:
            raise PortalError("portal_not_open", f"{portal.name} is not open yet. Start with wizard_portal_open.")
        session.popups.clear()
        page = context.new_page()
        if page in session.popups:
            session.popups.remove(page)
        session.pages[portal.id] = page
        session.trail[portal.id] = []
        return page

    # Steps ------------------------------------------------------------------------------------------------------------
    def portal(self, portal_id: str) -> Portal:
        portal = self.portals.get(portal_id)
        if portal is None:
            known = ", ".join(sorted(self.portals)) or "none configured"
            raise PortalError("unknown_portal", f"There is no portal '{portal_id}'. Portals: {known}.")
        return portal

    def _count(self, user_id: str, run_id: str) -> int:
        session = self._session(user_id)
        session.steps[run_id] = used = session.steps.get(run_id, 0) + 1
        if used > MAX_STEPS:
            raise PortalError("step_limit", f"This run has taken {MAX_STEPS} portal steps. Answer with what you have read "
                                            "and say what is missing.")
        return used

    def open(self, user_id: str, run_id: str, portal_id: str, path: str | None, show: Show) -> dict[str, Any]:
        portal = self.portal(portal_id)
        target = portal.start_url if not path else urljoin(portal.start_url, path)
        if path and (not path.startswith("/") or path.startswith("//") or not portal.allows(urlsplit(target).hostname)):
            raise PortalError("not_on_portal", f"'{path}' is not a page on {portal.name}. Give a path that starts with /.")

        def job() -> dict[str, Any]:
            step = self._count(user_id, run_id)
            page = self._page(user_id, portal, create=True)
            try:
                page.goto(target, wait_until="domcontentloaded")
            except Exception as error:  # noqa: BLE001
                self._settle(page)
                self._snap(page, portal, show, "after", f"Could not open {portal.name}")
                raise PortalError("portal_unreachable", f"{portal.name} did not open: {_short(error)}") from None
            return self._after(user_id, portal, page, show, step, f"Opened {portal.name}")
        return dict(self._call(job))

    def click(self, user_id: str, run_id: str, portal_id: str, ref: int, show: Show) -> dict[str, Any]:
        portal = self.portal(portal_id)

        def job() -> dict[str, Any]:
            step = self._count(user_id, run_id)
            page = self._page(user_id, portal, create=False)
            locator, info = self._element(user_id, portal, ref)
            refuse_click(info)
            locator.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            action = f"Clicking “{info['name'] or 'element ' + str(ref)}”"
            self._snap(page, portal, show, "before", action, locator.bounding_box())
            self._session(user_id).popups.clear()
            locator.click(timeout=ACTION_TIMEOUT_MS)
            result = self._after(user_id, portal, page, show, step, f"Clicked “{info['name'] or ref}”", popups=True)
            return {**result, "clicked": info["name"]}
        return dict(self._call(job))

    def type(self, user_id: str, run_id: str, portal_id: str, ref: int, text: str, enter: bool, show: Show) -> dict[str, Any]:
        portal = self.portal(portal_id)

        def job() -> dict[str, Any]:
            step = self._count(user_id, run_id)
            page = self._page(user_id, portal, create=False)
            locator, info = self._element(user_id, portal, ref)
            kind = refuse_typing(info)
            locator.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            field_name = info["name"] or f"field {ref}"
            action = f"Choosing “{text}” in “{field_name}”" if kind == "select" else f"Typing “{text}” into “{field_name}”"
            self._snap(page, portal, show, "before", action, locator.bounding_box())
            if kind == "select":
                try:
                    locator.select_option(label=text, timeout=ACTION_TIMEOUT_MS)
                except Exception:  # noqa: BLE001 - fall back to the option's value
                    locator.select_option(value=text, timeout=ACTION_TIMEOUT_MS)
            else:
                locator.fill(text, timeout=ACTION_TIMEOUT_MS)
                if enter:
                    self._session(user_id).popups.clear()
                    locator.press("Enter", timeout=ACTION_TIMEOUT_MS)
            done = action.replace("Typing", "Typed").replace("Choosing", "Chose")
            return {**self._after(user_id, portal, page, show, step, done, popups=enter), "field": field_name}
        return dict(self._call(job))

    def page_action(self, user_id: str, run_id: str, portal_id: str, action: str, show: Show) -> dict[str, Any]:
        portal = self.portal(portal_id)

        def job() -> dict[str, Any]:
            step = self._count(user_id, run_id)
            page = self._page(user_id, portal, create=False)
            note = None
            if action in ("scroll_down", "scroll_up"):
                page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
                page.mouse.wheel(0, 650 if action == "scroll_down" else -650)
                label = "Scrolled down" if action == "scroll_down" else "Scrolled up"
            elif action == "back":
                if page.go_back(wait_until="domcontentloaded") is None:
                    note = "There is no earlier page in this tab."
                label = "Went back"
            else:
                label = "Looked at the page again"
            result = self._after(user_id, portal, page, show, step, label)
            if note:
                result["notices"] = [note, *result.get("notices", [])]
            return result
        return dict(self._call(job))

    def read_table(self, user_id: str, run_id: str, portal_id: str, ref: int | None, max_rows: int,
                   show: Show) -> dict[str, Any]:
        portal = self.portal(portal_id)

        def job() -> dict[str, Any]:
            self._count(user_id, run_id)
            session = self._session(user_id)
            page = self._page(user_id, portal, create=False)
            tables = session.tables.get(portal.id, [])
            if not tables:
                raise PortalError("no_table", "The current page view lists no tables. Open the report first, or look at "
                                              "the page again once it has loaded.")
            chosen = ref if ref is not None else max(tables, key=lambda t: t.get("rows_drawn", 0))["ref"]
            frame = session.refs.get(portal.id, {}).get(chosen)
            if frame is None or chosen not in {t["ref"] for t in tables}:
                raise PortalError("unknown_table", f"There is no table {chosen} on the current page view. Tables: "
                                                   f"{', '.join(str(t['ref']) for t in tables)}.")
            locator = frame.locator(f'[data-wizard-table="{chosen}"]')
            if locator.count() == 0:
                raise PortalError("element_gone", "That table is no longer on the page. Look at the page again.")
            raw = locator.evaluate(TABLE_JS, max_rows)
            self._snap(page, portal, show, "before", f"Reading the table “{raw['caption'] or 'on this page'}”",
                       locator.bounding_box())
            columns, rows = shape_table(raw["header"], raw["rows"])
            title = page.title()
            warnings = []
            if raw["rows_drawn"] > len(rows):
                warnings.append(f"Only the first {len(rows)} of the {raw['rows_drawn']} rows drawn were read.")
            if raw["rows_declared"] and raw["rows_declared"] - 1 > raw["rows_drawn"]:
                warnings.append(f"The table says it has {raw['rows_declared'] - 1} rows but the page drew {raw['rows_drawn']}: "
                                "scroll and read again for the rest, or narrow the report's prompts.")
            digest = hashlib.sha256(json.dumps([columns, rows], sort_keys=True, default=str).encode("utf-8")).hexdigest()
            return {"portal": portal.id, "portal_name": portal.name, "url": page.url, "title": title,
                    "caption": raw["caption"], "columns": columns, "rows": rows, "rows_drawn": raw["rows_drawn"],
                    "truncated": raw["rows_drawn"] > len(rows), "warnings": warnings, "digest": digest,
                    "trail": list(session.trail.get(portal.id, []))[-6:]}
        return dict(self._call(job))

    # Sign-in and status -------------------------------------------------------------------------------------------------
    def start_signin(self, user_id: str, portal_id: str) -> None:
        """Open a visible window on this person's Wizard profile at the portal, for them to sign in themselves."""
        portal = self.portal(portal_id)

        def job() -> None:
            session = self._session(user_id)
            self._close_context(session)
            if session.signin is not None and not _closed(session.signin):
                session.signin.close()
            profile = self.profile_dir(user_id)
            profile.mkdir(parents=True, exist_ok=True)
            options = {**self._launch_options(headless=False), "no_viewport": True}
            options["args"] = [*options["args"], "--start-maximized"]
            try:
                session.signin = self._pw().chromium.launch_persistent_context(str(profile), **options)
            except Exception as error:  # noqa: BLE001
                raise PortalError("browser_unavailable", f"Wizard could not open {self._browser_name()}: {_short(error)}") from None
            page = session.signin.pages[0] if session.signin.pages else session.signin.new_page()
            session.state[portal.id] = "signing_in"
            try:
                page.goto(portal.start_url, wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS)
            except Exception as error:  # noqa: BLE001 - the window stays open; the person can retry in it
                log.info("sign-in window for %s: %s", portal.id, _short(error))
        self._call(job)

    def finish_signin(self, user_id: str) -> None:
        def job() -> None:
            session = self._session(user_id)
            if session.signin is not None:
                try:
                    session.signin.close()
                except Exception:  # noqa: BLE001, S110
                    pass
                session.signin = None
            for portal_id, state in list(session.state.items()):
                if state == "signing_in":
                    session.state[portal_id] = "unknown"
        self._call(job)

    def check(self, user_id: str, portal_id: str, show: Show | None = None) -> dict[str, Any]:
        """Open the portal's start page in the background and say whether this person's session is signed in."""
        portal = self.portal(portal_id)

        def job() -> dict[str, Any]:
            page = self._page(user_id, portal, create=True)
            try:
                page.goto(portal.start_url, wait_until="domcontentloaded")
            except Exception as error:  # noqa: BLE001
                self._session(user_id).state[portal.id] = "unreachable"
                return {"portal": portal.id, "state": "unreachable", "detail": _short(error)}
            self._settle(page)
            view = self._look(user_id, portal, page)
            state = "signin_required" if self._needs_signin(portal, page, view) else "ready"
            self._session(user_id).state[portal.id] = state
            if show:
                self._snap(page, portal, show, "after", f"Checked {portal.name}")
            return {"portal": portal.id, "state": state, "title": view["title"]}
        return dict(self._call(job))

    def element_name(self, user_id: str, portal_id: str, ref: int | None, table: bool = False) -> str | None:
        """What an element or table of the latest page view is called, for naming a step before it runs (no table
        number: the largest table, which read_table picks)."""
        session = self._sessions.get(user_id)
        if session is None:
            return None
        if ref is None and table and session.tables.get(portal_id):
            ref = max(session.tables[portal_id], key=lambda t: t.get("rows_drawn", 0))["ref"]
        return (session.names.get(portal_id, {}).get(ref) if ref is not None else None) or None

    def status(self, user_id: str) -> list[dict[str, Any]]:
        session = self._sessions.get(user_id)
        signin_open = bool(session and session.signin is not None)
        return [{"id": p.id, "name": p.name, "host": urlsplit(p.start_url).hostname,
                 "state": (session.state.get(p.id) if session else None) or "unknown", "signin_open": signin_open}
                for p in self.portals.values()]

    # Page helpers -----------------------------------------------------------------------------------------------------
    def _settle(self, page: Any) -> None:
        """Wait for what a step started: a click's navigation can begin after the click returns, and a load state that
        the old page already reached would otherwise end the wait at once."""
        page.wait_for_timeout(300)
        loading = next((s.loading for s in self._sessions.values() if id(page) in s.loading), {})
        deadline = time.monotonic() + NAVIGATION_TIMEOUT_MS / 1000
        while loading.get(id(page), 0) > 0 and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        for state, timeout in (("load", 15_000), ("networkidle", 5_000)):
            try:
                page.wait_for_load_state(state, timeout=timeout)
            except Exception:  # noqa: BLE001, S110 - a busy portal never goes idle; the page is read as it is
                pass
        page.wait_for_timeout(250)

    def _adopt_popup(self, user_id: str, portal: Portal, page: Any) -> Any:
        session = self._session(user_id)
        for popup in list(session.popups):
            session.popups.remove(popup)
            if popup in session.pages.values():
                continue
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            except Exception:  # noqa: BLE001, S110
                pass
            if portal.allows(urlsplit(popup.url).hostname):
                session.notices.append(f"{portal.name} opened that in a new tab; Wizard followed it.")
                session.pages[portal.id] = popup
                page = popup
            else:
                session.notices.append(f"A new window on {urlsplit(popup.url).hostname or popup.url} was closed: it is not "
                                       f"part of {portal.name}.")
                popup.close()
        return page

    def _element(self, user_id: str, portal: Portal, ref: int) -> tuple[Any, dict[str, Any]]:
        frame = self._session(user_id).refs.get(portal.id, {}).get(ref)
        if frame is None:
            raise PortalError("unknown_element", f"Element {ref} is not on the latest page view of {portal.name}. Use a "
                                                 "number from the latest view, or wizard_portal_page(action='look').")
        locator = frame.locator(f'[data-wizard-ref="{ref}"]')
        try:
            found = locator.count()
        except Exception:  # noqa: BLE001 - the frame went away
            found = 0
        if not found:
            raise PortalError("element_gone", f"Element {ref} is no longer on the page (it changed). Look at the page again.")
        locator = locator.first
        return locator, dict(locator.evaluate(DESCRIBE_JS))

    def _look(self, user_id: str, portal: Portal, page: Any) -> dict[str, Any]:
        session = self._session(user_id)
        refs: dict[int, Any] = {}
        elements: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        texts: list[str] = []
        password = more = False
        scroll: dict[str, Any] = {}
        start = 1
        for frame in [page.main_frame, *[f for f in page.frames if f != page.main_frame]]:
            if frame != page.main_frame and not (frame.url.startswith("http") and self._allowed_document(urlsplit(frame.url).hostname)):
                continue
            budget = TEXT_LIMIT - sum(len(t) for t in texts)
            try:
                data = frame.evaluate(PAGE_JS, {"start": start, "limit": max(0, ELEMENT_LIMIT - len(elements)),
                                                "textLimit": max(0, budget if frame == page.main_frame else min(budget, 2500))})
            except Exception:  # noqa: BLE001, S112 - a frame that navigates or detaches while being read is skipped
                continue
            for item in [*data["elements"], *data["tables"]]:
                refs[item["ref"]] = frame
            elements += data["elements"]
            tables += data["tables"]
            if data["text"]:
                texts.append(data["text"])
            password = password or data["password_field"]
            more = more or data["more"]
            if frame == page.main_frame:
                scroll = data["scroll"]
            start = data["next"]
        session.refs[portal.id] = refs
        session.tables[portal.id] = tables
        session.names[portal.id] = {**{e["ref"]: e["name"] for e in elements}, **{t["ref"]: t["caption"] for t in tables}}
        return {"title": page.title(), "text": "\n---\n".join(texts), "elements": elements, "tables": tables,
                "more_elements": more, "password_field": password, "scroll": scroll}

    def _needs_signin(self, portal: Portal, page: Any, view: dict[str, Any]) -> bool:
        host = urlsplit(page.url).hostname
        return bool(view["password_field"]) or (not portal.allows(host) and host_matches(host or "", self.options.signin_hosts))

    def _snap(self, page: Any, portal: Portal, show: Show, phase: str, action: str, box: dict[str, float] | None = None) -> None:
        try:
            image = page.screenshot(type="jpeg", quality=62, timeout=ACTION_TIMEOUT_MS)
            title = page.title()
        except Exception as error:  # noqa: BLE001 - a missing picture never fails the step
            log.info("portal screenshot failed: %s", _short(error))
            return
        target = {k: round(float(v), 1) for k, v in box.items()} if box else None
        show(Frame(image=image, portal=portal.id, phase=phase, action=action, url=page.url, title=title, target=target))

    def _after(self, user_id: str, portal: Portal, page: Any, show: Show, step: int, action: str,
               popups: bool = False) -> dict[str, Any]:
        session = self._session(user_id)
        self._settle(page)
        if popups:
            followed = self._adopt_popup(user_id, portal, page)
            if followed is not page:
                page = followed
                self._settle(page)
        if page.url.startswith("chrome-error:") and any("Stopped a page" in n for n in session.notices):
            # The step tried to leave the portals; the tab shows the browser's error page, so return to where it was.
            try:
                page.go_back(wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001, S110
                pass
            self._settle(page)
        view = self._look(user_id, portal, page)
        self._snap(page, portal, show, "after", action)
        notices, session.notices = session.notices, []
        if self._needs_signin(portal, page, view):
            session.state[portal.id] = "signin_required"
            where = urlsplit(page.url).hostname or page.url
            raise PortalError("signin_required", f"{portal.name} is asking you to sign in (the page is on {where}). Open "
                                                 f"Sources → Portals → {portal.name} → Sign in, sign in in the window "
                                                 "that opens, then ask again." + (" " + " ".join(notices) if notices else ""))
        session.state[portal.id] = "ready"
        trail = session.trail.setdefault(portal.id, [])
        if not trail or trail[-1] != view["title"]:
            trail.append(view["title"])
        parts = urlsplit(page.url)
        return {"portal": portal.id, "portal_name": portal.name, "page_title": view["title"],
                "address": parts.path + (f"?{parts.query}" if parts.query else ""), "text": view["text"],
                "elements": view["elements"], "tables": [{k: v for k, v in t.items()} for t in view["tables"]],
                "more_elements_below": view["more_elements"], "scroll": view["scroll"], "notices": notices,
                "step": step, "steps_left": MAX_STEPS - step}


def refuse_click(info: dict[str, Any]) -> None:
    name = info.get("name") or ""
    kind = info.get("role") or info.get("tag") or ""
    if info.get("download") or info.get("type") == "file":
        raise PortalError("refused", "Wizard does not download or upload files.")
    if REFUSED_VERBS.match(name):
        raise PortalError("refused", f"“{name}” looks like it changes, sends or exports something; Wizard only reads. "
                                     "Find the data on the page instead, or tell the person where to look.")
    if REFUSED_BUTTON_VERBS.match(name) and (info.get("tag") == "button" or kind in BUTTON_KINDS):
        raise PortalError("refused", f"“{name}” looks like it creates something; Wizard only reads.")
    if info.get("tag") == "a" and REFUSED_HREF.search(info.get("href") or ""):
        raise PortalError("refused", f"The link “{name}” goes to an export, share or delete page; Wizard only reads.")


def refuse_typing(info: dict[str, Any]) -> str:
    tag, kind_type, role = info.get("tag"), info.get("type") or "", info.get("role") or ""
    if kind_type == "password":
        raise PortalError("refused", "Wizard never types into password fields. The person signs in themselves.")
    if info.get("editor"):
        raise PortalError("refused", "Wizard does not write into code or SQL editors on a portal.")
    if tag == "select":
        return "select"
    if tag == "textarea":
        return "text"
    if tag == "input" and kind_type in ("", "text", "search", "number", "date", "month", "week", "tel"):
        return "text"
    if role in ("combobox", "searchbox", "textbox") and not info.get("editable"):
        return "text"
    if role in ("combobox", "searchbox", "textbox") and info.get("editable"):
        raise PortalError("refused", "Wizard does not type into rich-text editors on a portal.")
    raise PortalError("not_a_field", "That element is not a text, search or choice field. Click it instead.")


NUMBER = re.compile(r"^\(?-?[$€£¥₹]?\s?-?[0-9][0-9,]*(\.[0-9]+)?\)?\s?(%|[KMB])?$")


def to_number(text: str) -> float | int | None:
    value = text.strip().replace(" ", "")
    if not NUMBER.match(value):
        return None
    negative = value.startswith("(") and value.endswith(")") or value.lstrip("($€£¥₹ ").startswith("-")
    digits = re.sub(r"[^0-9.]", "", value)
    if not digits or digits.count(".") > 1:
        return None
    number = float(digits) * {"K": 1e3, "M": 1e6, "B": 1e9}.get(value[-1:], 1)
    number = -number if negative else number
    return int(number) if number.is_integer() and "." not in digits and value[-1:] not in "KMB" else number


def shape_table(header: list[str], rows: list[list[str]]) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    """Columns with unique keys and a type, and rows with numbers parsed ("1,234" → 1234, "12.5%" → 12.5)."""
    width = max([len(header), *(len(r) for r in rows)] or [0])
    labels = [(header[i] if i < len(header) else "") or f"Column {i + 1}" for i in range(width)]
    keys: list[str] = []
    for label in labels:
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60] or "column"
        key = key if key[0].isalpha() else f"c_{key}"
        candidate, n = key, 2
        while candidate in keys:
            candidate, n = f"{key}_{n}", n + 1
        keys.append(candidate)
    padded = [[*r, *[""] * (width - len(r))][:width] for r in rows]
    columns: list[dict[str, Any]] = []
    out: list[list[Any]] = [list(r) for r in padded]
    for i, (key, label) in enumerate(zip(keys, labels, strict=True)):
        values = [r[i] for r in padded if r[i] not in ("", "-", "—")]
        parsed = [to_number(v) for v in values]
        numeric = bool(values) and all(p is not None for p in parsed)
        kind = "percent" if numeric and all(v.strip().endswith("%") for v in values) else "number" if numeric else "string"
        columns.append({"key": key, "label": label, "type": kind})
        if numeric:
            for row in out:
                row[i] = to_number(row[i]) if row[i] not in ("", "-", "—") else None
    return columns, out


def _closed(context: Any) -> bool:
    """A context whose window the person closed: one round trip to the browser tells (a persistent context has no
    Browser object to ask, and Playwright reports the close only during a later call)."""
    try:
        context.cookies("https://wizard.invalid/")
        return False
    except Exception:  # noqa: BLE001
        return True


def _short(error: object, limit: int = 300) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return text[:limit]

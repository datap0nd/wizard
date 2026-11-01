"""The person's Wizard browser: Google Chrome (or Edge) driven by Playwright, with its own profile, where Gemini's
portal scripts run in the background (headless), the person signs in once in a visible window, and an access request
form opens visibly, filled from the person's saved answers, for them to check and submit, one prepared request after
another.

One PortalBrowser per person. Playwright's synchronous objects belong to the thread that made them, so each browser has
one thread that owns Playwright and runs every job in turn; tool calls hand it work and wait. The profile is Wizard's
own folder under the person's Wizard home, never their everyday Chrome profile, and Wizard stores no password. The profile
keeps the sign-in's lasting cookies like any browser does. Chrome drops session-only cookies when it closes, and most
portal and sign-in sessions are session-only, so the sign-in ended with its window (owner, 28 October 2026). Wizard
keeps those cookies of its own browser, protected by the secret store (DPAPI on Windows), and puts them back whenever the
browser starts, as Metronome's Flows keep their browser's sign-in (data_governance app/flow_browser_state.py).

While Gemini drives (headless) every request goes through HostPolicy and write_reason, every click through
click_refusal, downloads and service workers are off, and the data requests the page makes are kept so Gemini can call
them again itself. While the person signs in (headed) nothing is filtered: the hosts their sign-in goes through are
remembered so a later background session can renew it. The access request window is the person's too, unfiltered so
they can submit; Wizard only fills the form's empty fields on the portals' own pages (portal_fill.js), clicking only to
open one of the form's own drop-downs and choose the person's saved option in it (portal_pick.js), and Gemini's steps
wait until the window is closed."""
from __future__ import annotations

import contextlib
import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import access_requests, portals
from .portals import HostPolicy, Portal, PortalSettings

log = logging.getLogger("wizard.portals")

HELPERS = Path(__file__).with_name("portal_helpers.js").read_text(encoding="utf-8")
CAPTURE = Path(__file__).with_name("portal_capture.js").read_text(encoding="utf-8")
FILL = Path(__file__).with_name("portal_fill.js").read_text(encoding="utf-8")
PICK = Path(__file__).with_name("portal_pick.js").read_text(encoding="utf-8")
CLICKS = Path(__file__).with_name("portal_clicks.js").read_text(encoding="utf-8")
SEND_WAIT_S = 60            # a request Wizard sends must have its whole form filled within this long, or sending stops
SUBMIT_WAIT_MS = 20_000     # how long the request Wizard's Submit sends may take to be answered
SUBMISSION_WINDOW_S = 8     # the person's Submit and the request it sends: at most this far apart
CLICK_SLACK_S = 1.5         # the note of the person's press can reach Wizard a moment after what it set off
# A question the page asks when a request is submitted ("Do you want to submit the request?"): answered OK only right
# after the person's own press (or Wizard's, when sending), and only with these words; any other question is Cancel.
SUBMITTISH = re.compile(r"(?i)(submit|request|apply|send|proceed|continue|register|신청|제출|요청|등록|진행)")
PICK_WAIT_MS = 2500         # how long a drop-down's list may take to show the option after it opens or is searched
OPEN_GUARD_S = 4.0          # after Wizard presses the control that opens a request form, the portal's writes stop this long
FILL_EVERY_S = 1.5          # the access request window looks for its form's fields this often
IDLE_CLOSE_S = 600          # a background browser nobody used for this long is closed
SIGN_IN_LIMIT_S = 20 * 60   # a sign-in window left open this long is closed
CALL_LIMIT_S = 170          # one tool call's steps together (under the Gemini CLI tool bridge's 180 s)
MAX_PAGES = 6
DATA_TYPES = ("xhr", "fetch", "document")
TEXT_TYPES = ("json", "xml", "text", "javascript", "csv", "x-www-form-urlencoded", "ssv")
MAX_CAPTURED = 60
# Text a sign-in page shows (Metronome's markers, data_governance app/flow_download_security.py), when no password field
# is visible yet (an account picker, a code prompt).
SIGN_IN_MARKERS = ("single sign on", "single sign-on", "please enter your password", "verification code", "session expired",
                   "sign in to continue", "login required")


class SecretStore(Protocol):
    """Where the sign-in's session cookies are kept: wizard_agent's SecretBox (DPAPI on Windows)."""

    def write(self, path: Path, value: str) -> None: ...

    def read(self, path: Path) -> str | None: ...


class PortalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Captured:
    method: str
    url: str
    resource: str
    body: str | None
    status: int | None = None
    content_type: str = ""
    size: int | None = None
    preview: str = ""
    response: Any = None


@dataclass
class AccessWindow:
    """The access request window: what it fills, and what it filled and saw, per page."""
    portal: Portal
    address: str
    answers: list[dict[str, str]]
    queued: str | None = None  # the prepared request this window shows, when it walks through them
    tables: list[str] = field(default_factory=list)
    open_steps: list[dict[str, Any]] = field(default_factory=list)  # from address to the table's page (Gemini's, proved)
    form_button: str = ""  # the control that opens the request form there
    pressed: bool = False  # Wizard pressed it (once)
    form_seen: bool = False  # an answer found its field: the form is open
    note: str | None = None  # what the window says about reaching the table and opening its form
    stopped: list[str] = field(default_factory=list)  # writes Wizard stopped while the form opened
    kept: list[str] = field(default_factory=list)  # answers whose field already had a value
    form_page: Any = None  # the page the form is on
    shown_at: float = field(default_factory=time.monotonic)
    done: dict[str, list[str]] = field(default_factory=dict)  # per page: the fields handled (filled, kept or tried)
    page_filled: dict[str, list[str]] = field(default_factory=dict)  # per page: the fields Wizard filled
    filled: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unpicked: list[str] = field(default_factory=list)  # drop-downs whose saved option Wizard could not find
    seen: list[str] = field(default_factory=list)
    last: float = 0.0


@dataclass
class CallLog:
    """What one tool call's steps did in the browser, for Gemini and the evidence."""
    requests: list[Captured] = field(default_factory=list)
    blocked: list[dict[str, str]] = field(default_factory=list)
    dialogs: list[str] = field(default_factory=list)
    console: list[str] = field(default_factory=list)


class PortalBrowser:
    def __init__(self, settings: PortalSettings, root: Path, launcher: Callable[..., Any] | None = None,
                 secrets: SecretStore | None = None):
        self.settings = settings
        self.root = root
        self.profile = root / settings.channel
        self.state_file = root / "sign-in.json"
        self.policy = HostPolicy(settings, set(self._state().get("learned_hosts", [])))
        self._launcher = launcher
        self._jobs: queue.Queue[tuple[Callable[[], Any], Future[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None
        self._headed = False
        self._headed_since = 0.0
        self._window: str | None = None  # the visible window: "sign_in" or "access_request"
        self._request: AccessWindow | None = None
        self.show_windows = True  # tests run the person's windows headless
        self._last_used = time.monotonic()
        self._log: CallLog | None = None
        self._sign_in_hosts: set[str] = set()
        self._secrets = secrets
        self.session_file = root / "session.bin"
        self._session: list[dict[str, Any]] = self._load_session()
        self._seen: list[dict[str, Any]] | None = None  # the sign-in window's cookies, the last time Wizard looked
        self.audit: Callable[..., None] | None = None  # the audit log: (action, system=..., detail=...)
        self._guard_until = 0.0  # the portal's writes stop until then, while a request form Wizard opened appears
        self._guarded: Any = None  # the page whose requests the guard sees
        self._guard_allow: dict[str, str] | None = None  # while Wizard sends: the one request its Submit may send
        self._acting: str | None = None  # Wizard's own clicks in the person's window ("pick", "open", "submit")
        self._person_click: dict[str, Any] | None = None  # the control the person last pressed in the request window
        self._writes: list[dict[str, Any]] = []  # requests that could change something, sent from the request window
        self._last_dialog: tuple[float, str] | None = None
        self._batch: list[str] = []  # prepared requests the person approved, Wizard sending them one after another
        self._batch_sent = 0

    # State without secrets: the hosts sign-in went through and when it last happened --------------------------------
    def _state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self, **changes: Any) -> None:
        state = {**self._state(), **changes}
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # The sign-in's session-only cookies, which Chrome drops when it closes ---------------------------------------------
    def _load_session(self) -> list[dict[str, Any]]:
        text = self._secrets.read(self.session_file) if self._secrets is not None else None
        try:
            cookies = json.loads(text) if text else []
        except ValueError:
            return []
        return [c for c in cookies if isinstance(c, dict)] if isinstance(cookies, list) else []

    def _keep_session(self, cookies: list[dict[str, Any]]) -> None:
        """Keep the session-only cookies the portals and the person's sign-in hosts receive (Chrome keeps the lasting
        ones in the profile itself)."""
        hosts = {host for portal in self.settings.portals for host in portal.hosts} | self.policy.learned

        def reaches(domain: str) -> bool:
            domain = domain.lstrip(".").lower()
            return self.policy.allowed(domain) or any(h == domain or h.endswith("." + domain) for h in hosts)

        kept = [c for c in cookies if float(c.get("expires", -1)) < 0 and reaches(str(c.get("domain") or ""))]
        if kept == self._session:
            return
        self._session = kept
        if self._secrets is not None:
            try:
                self._secrets.write(self.session_file, json.dumps(kept))
            except OSError as error:
                log.warning("portal browser: could not keep the sign-in: %s", error)

    def _note_session(self) -> None:
        """Note the browser's cookies as they are now: the sign-in window's are kept when the person closes it (the
        browser may be gone by then), the background browser's at once (a portal may renew its session)."""
        try:
            # Once its last window has closed, Chrome has already dropped them: what was noted before stays.
            if self._context is None or not self._context.pages:
                return
            cookies = self._context.cookies()
        except Exception:  # noqa: BLE001 - the browser has exited; what was noted stays
            return
        if self._headed:
            self._seen = cookies
        else:
            self._keep_session(cookies)

    def _restore_session(self, context: Any) -> None:
        if not self._session:
            return
        try:
            context.add_cookies(self._session)
        except Exception as error:  # noqa: BLE001 - the portals then ask for a sign-in, which the person gives again
            log.warning("portal browser: the kept sign-in could not be restored: %s", _first_line(error))

    # The browser thread ----------------------------------------------------------------------------------------------
    def run(self, job: Callable[[], Any], timeout: float = CALL_LIMIT_S) -> Any:
        """Run `job` on the browser thread and return its result (its exception is raised here)."""
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="wizard-portal-browser", daemon=True)
                self._thread.start()
        future: Future[Any] = Future()
        self._jobs.put((job, future))
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            raise PortalError("browser_timeout", f"The browser did not finish within {int(timeout)} seconds. Split the "
                                                 "work into smaller steps or wait for a shorter condition.") from None

    def shutdown(self) -> None:
        if self._thread and self._thread.is_alive():
            self._jobs.put(None)
            self._thread.join(timeout=15)

    def _loop(self) -> None:
        while True:
            try:
                item = self._jobs.get(timeout=0.5)
            except queue.Empty:
                self._idle()
                continue
            if item is None:
                self._close()
                if self._pw is not None:
                    with contextlib.suppress(Exception):  # already gone
                        self._pw.stop()
                    self._pw = None
                return
            job, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(job())
            except BaseException as error:  # noqa: BLE001 - handed to the caller
                future.set_exception(error)
            finally:
                self._last_used = time.monotonic()
                self._note_session()
            if self._request is not None and self._headed and time.monotonic() - self._request.last >= FILL_EVERY_S:
                self._idle()  # a steady stream of jobs never starves the person's request window

    def _idle(self) -> None:
        if self._context is None:
            return
        if self._headed:
            # The person's window: keep its events flowing, fill a request form as it appears, and finish when they
            # close the window or forget it.
            try:
                pages = self._context.pages
                if not pages:
                    raise RuntimeError("closed")
                pages[0].wait_for_timeout(250)
            except Exception:  # noqa: BLE001 - the window was closed
                self._finish_window()
                return
            self._note_session()
            if self._guarded is not None and time.monotonic() > self._guard_until:
                self._unguard()
            if self._request is not None and time.monotonic() - self._request.last >= FILL_EVERY_S:
                self._fill_request()
                self._drive_batch()
            if time.monotonic() - self._headed_since > SIGN_IN_LIMIT_S:
                self._finish_window()
        elif time.monotonic() - self._last_used > IDLE_CLOSE_S:
            self._close()

    def _close(self) -> None:
        if not self._headed:
            self._note_session()
        context, self._context, self._page = self._context, None, None
        if context is not None:
            with contextlib.suppress(Exception):  # the browser may already have exited
                context.close()

    def _playwright(self) -> Any:
        if self._pw is None:
            if self._launcher is not None:
                self._pw = self._launcher()
            else:
                try:
                    from playwright.sync_api import sync_playwright
                except ImportError:
                    raise PortalError("browser_unavailable", "Playwright is not installed in this Wizard. Update Wizard; "
                                                             "the desktop app includes it.") from None
                self._pw = sync_playwright().start()
        return self._pw

    def _launch(self, headed: bool, window: str = "sign_in") -> Any:
        self._close()
        self.profile.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {"headless": not (headed and self.show_windows), "accept_downloads": False,
                                   "service_workers": "block",
                                   "viewport": {"width": 1440, "height": 900}}
        if self.settings.executable:
            options["executable_path"] = self.settings.executable
        else:
            options["channel"] = self.settings.channel
        try:
            context = self._playwright().chromium.launch_persistent_context(str(self.profile), **options)
        except PortalError:
            raise
        except Exception as error:  # noqa: BLE001 - reported in words
            text = str(error)
            if "ProcessSingleton" in text or "already in use" in text or "SingletonLock" in text:
                raise PortalError("browser_busy", "Wizard's browser profile is open in another window. Close the Wizard "
                                                  "sign-in window and try again.") from None
            raise PortalError("browser_unavailable",
                              f"Could not start {portals.CHANNELS[self.settings.channel]} for Wizard: {text.splitlines()[0][:300]}. "
                              "Check that it is installed on this PC (Settings → Portals chooses Chrome or Edge).") from None
        context.set_default_timeout(30_000)
        self._restore_session(context)
        context.on("dialog", self._dialog)
        if headed:
            if window == "sign_in":
                context.on("request", self._remember_sign_in_host)
            elif window == "access_request":  # which control the person pressed, and what it sent
                self._writes, self._person_click = [], None
                with contextlib.suppress(Exception):  # a test launcher without bindings
                    context.expose_binding("__wizardClicked", self._clicked)
                    context.add_init_script(CLICKS)
                context.on("request", self._watch_write)
                context.on("response", self._watch_response)
        else:
            context.add_init_script(CAPTURE)
            context.route("**/*", self._route)
            if hasattr(context, "route_web_socket"):
                context.route_web_socket("**/*", self._route_socket)
            context.on("request", self._capture_request)
            context.on("response", self._capture_response)
            context.on("page", self._watch_page)
        self._context, self._headed = context, headed
        self._window = window if headed else None
        if window != "access_request":
            self._request = None
        for page in context.pages:
            self._watch_page(page)
        return context

    # Guards (headless only) ------------------------------------------------------------------------------------------
    def _route(self, route: Any) -> None:
        request = route.request
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            route.continue_()
            return
        host = urlsplit(url).hostname
        reason = None
        if not self.policy.allowed(host):
            reason = f"{host} is not one of the portal hosts"
        else:
            try:
                body = request.post_data
            except Exception:  # noqa: BLE001 - binary body
                body = None
            reason = portals.write_reason(request.method, url, body)
        if reason:
            if self._log is not None and len(self._log.blocked) < 40:
                self._log.blocked.append({"method": request.method, "url": portals.redact_url(url)[:300], "why": reason})
            log.info("portal browser refused %s %s: %s", request.method, portals.redact_url(url)[:200], reason)
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _route_socket(self, socket: Any) -> None:
        if self.policy.allowed(urlsplit(socket.url).hostname):
            socket.connect_to_server()
        else:
            socket.close()

    def _dialog(self, dialog: Any) -> None:
        if self._headed and self._window == "access_request" and dialog.type in ("confirm", "prompt"):
            self._request_dialog(dialog)
            return
        if self._log is not None:
            self._log.dialogs.append(f"{dialog.type}: {dialog.message[:300]}")
        with contextlib.suppress(Exception):  # already handled
            # Alerts are acknowledged; a confirmation ("Are you sure?") is always answered No.
            dialog.accept() if dialog.type in ("alert", "beforeunload") else dialog.dismiss()

    def _request_dialog(self, dialog: Any) -> None:
        """A question in the request window: OK only for a submit question set off by the person (Wizard is not pressing
        anything) or by Wizard's Submit when it sends; otherwise Cancel, and the note says so."""
        message = " ".join(str(dialog.message or "").split())[:300]
        self._last_dialog = (time.monotonic(), message)
        person = not self._acting
        proof = (access_requests.sending(self.root, self._request.portal.id)["proof"] or {}) if self._request else {}
        sending = self._acting == "submit" and (SUBMITTISH.search(message) or message == proof.get("dialog"))
        answer = dialog.type == "confirm" and (sending or (person and SUBMITTISH.search(message)))
        with contextlib.suppress(Exception):  # already handled
            dialog.accept() if answer else dialog.dismiss()
        if self._request is not None:
            self._request.note = (f"The page asked \"{message[:120]}\" and Wizard answered OK"
                                  + (" for you." if not self._acting else ".") if answer else
                                  f"The page asked \"{message[:120]}\" and Wizard answered Cancel: it answers OK only "
                                  "to a submit question right after Submit.")

    def _clicked(self, source: Any, info: Any) -> None:
        """The person pressed a control in the request window (portal_clicks.js); Wizard's own presses are not theirs."""
        if self._acting or not isinstance(info, dict):
            return
        request = self._request
        self._person_click = {"at": time.monotonic(), "text": str(info.get("text") or "")[:80],
                              "in_form": bool(info.get("inForm")), "form_seen": bool(request and request.form_seen)}

    def _watch_write(self, request: Any) -> None:
        """A request from the request window that could change something (any method but GET) on the portal's pages."""
        current = self._request
        if current is None or request.method.upper() in ("GET", "HEAD", "OPTIONS") or \
                request.resource_type not in DATA_TYPES or \
                not access_requests.on_portal(current.portal, (urlsplit(request.url).hostname or "").lower()):
            return
        try:
            body = request.post_data
        except Exception:  # noqa: BLE001 - a binary body
            body = None
        self._writes = [*self._writes[-29:], {"request": request, "method": request.method.upper(), "url": request.url,
                                              "body": (body or "")[:20_000], "at": time.monotonic(),
                                              "acting": self._acting, "status": None, "response": None}]

    def _watch_response(self, response: Any) -> None:
        for write in reversed(self._writes):
            if write["request"] is response.request and write["status"] is None:
                write["status"], write["response"] = response.status, response
                return

    def _observe(self, request: AccessWindow) -> None:
        """After the person pressed a control in the filled form, the request it sent: kept as their last submission
        (the proof sending copies, once they say it worked), and a prepared request is marked sent by them."""
        click = self._person_click
        if click is None or not click["form_seen"]:
            return
        after = [w for w in self._writes if not w.get("seen") and not w["acting"] and w["status"] is not None
                 and -CLICK_SLACK_S <= w["at"] - click["at"] <= SUBMISSION_WINDOW_S]
        if not after:
            if time.monotonic() - click["at"] > SUBMISSION_WINDOW_S + 5:
                self._person_click = None
            return
        # A Submit's own request is the first it sends (a draft cleared or a list refreshed comes after); after another
        # control, only a request whose address names a change.
        flagged = [w for w in after if portals.write_reason(w["method"], w["url"], w["body"])]
        chosen = after[0] if SUBMITTISH.search(click["text"]) else (flagged[0] if flagged else None)
        for write in after:
            write["seen"] = True
        if chosen is None:
            return
        self._person_click = None
        try:
            reply = chosen["response"].text()[:20_000]
        except Exception:  # noqa: BLE001 - the page moved on and its body is gone
            reply = ""
        dialog = self._last_dialog[1] if self._last_dialog and abs(self._last_dialog[0] - click["at"]) <= 10 else None
        path = urlsplit(chosen["url"]).path
        submission = {"tables": request.tables, "button": click["text"], "method": chosen["method"],
                      "match": access_requests.path_pattern(chosen["url"]), "path": path[:200],
                      "status": chosen["status"], "expect": access_requests.expect_fields(reply),
                      **({"dialog": dialog} if dialog else {}), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "request_id": request.queued}
        access_requests.remember_submission(self.root, request.portal.id, submission)
        went = 200 <= int(chosen["status"]) < 300
        if went and request.queued:
            access_requests.mark_sent(self.root, request.portal.id, request.queued, "you", int(chosen["status"]), path)
        if self.audit is not None:
            with contextlib.suppress(Exception):
                self.audit("portals:access_submitted", system=request.portal.id,
                           detail={"tables": request.tables, "by": "you", "method": chosen["method"], "path": path[:200],
                                   "status": chosen["status"]})
        enabled = access_requests.sending(self.root, request.portal.id)["enabled"]
        request.note = (f"Wizard saw this request go out when you pressed {click['text'] or 'the button'} "
                        f"({chosen['method']} {path[:80]}, answered {chosen['status']})."
                        + ("" if enabled or not went else " If the catalog confirms it, press 'It worked: let Wizard "
                           "send the requests I approve' in Settings → Portals."))

    def _watch_page(self, page: Any) -> None:
        if not self._headed:
            page.on("console", lambda message: self._log.console.append(f"{message.type}: {message.text[:300]}")
                    if self._log is not None and message.type in ("error", "warning") and len(self._log.console) < 20
                    else None)
            self._page = page

    def _capture_request(self, request: Any) -> None:
        if self._log is None or request.resource_type not in DATA_TYPES or len(self._log.requests) >= MAX_CAPTURED:
            return
        try:
            body = request.post_data
        except Exception:  # noqa: BLE001 - binary body
            body = "<binary>"
        self._log.requests.append(Captured(request.method, request.url, request.resource_type, body))

    def _capture_response(self, response: Any) -> None:
        if self._log is None:
            return
        request = response.request
        for item in reversed(self._log.requests):
            if item.url == request.url and item.method == request.method and item.status is None:
                item.status = response.status
                item.content_type = (response.headers.get("content-type") or "").split(";")[0]
                length = response.headers.get("content-length")
                item.size = int(length) if length and length.isdigit() else None
                item.response = response
                break

    def _remember_sign_in_host(self, request: Any) -> None:
        if request.resource_type == "document":
            host = urlsplit(request.url).hostname
            if host:
                self._sign_in_hosts.add(host.lower())

    # Sign-in -----------------------------------------------------------------------------------------------------------
    def begin_sign_in(self) -> dict[str, Any]:
        """Open a visible window with one tab per portal (per application: the Big Data Portal's information catalog
        and Superset each get one) for the person to sign in. Wizard waits for them to close it."""
        def job() -> dict[str, Any]:
            context = self._launch(headed=True, window="sign_in")
            self._headed_since = time.monotonic()
            self._sign_in_hosts = set()
            first = context.pages[0] if context.pages else context.new_page()
            addresses = [url for portal in self.settings.portals for _, _, url in portal.pages]
            for index, url in enumerate(addresses):
                page = first if index == 0 else context.new_page()
                with contextlib.suppress(Exception):  # the person sees the page and its error
                    page.goto(url, wait_until="commit", timeout=30_000)
            with contextlib.suppress(Exception):
                first.bring_to_front()
            return self.status_now()
        return self.run(job, timeout=90)

    def finish_sign_in(self) -> dict[str, Any]:
        """Done: close the person's window (sign-in or access request)."""
        def job() -> dict[str, Any]:
            if self._headed:
                self._finish_window()
            return self.status_now()
        return self.run(job, timeout=60)

    def _finish_window(self) -> None:
        self._note_session()
        if self._window == "access_request" and self._request is not None:
            with contextlib.suppress(Exception):  # the window may be gone; what was seen is already kept
                self._fill_request(closing=True)
            access_requests.remember_seen(self.root, self._request.portal.id, self._request.seen)
        elif self._window == "sign_in":
            hosts = {h for h in self._sign_in_hosts if "." in h and not h.replace(".", "").isdigit()}
            learned = sorted(self.policy.learned | hosts)[:50]
            self.policy.learned = set(learned)
            self._save_state(learned_hosts=learned, last_sign_in=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if self._seen is not None:  # a sign-in in either window outlives it
            self._keep_session(self._seen)
            self._seen = None
        self._unguard()
        self._batch = []
        self._close()
        self._headed, self._window, self._request = False, None, None

    # The access request window ---------------------------------------------------------------------------------------
    def open_access_request(self, portal: Portal, address: str, answers: list[dict[str, str]],
                            queued: str | None = None, route: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open the portal's request page in a visible window, reach the table's page (route: open_steps Gemini proved,
        for a catalog that keeps one address), press the control that opens its request form (route's form_button, or
        a usual name) with the portal's writes stopped, and fill the person's answers into the form's empty fields as it
        appears; they check it and submit it themselves. An open request window is reused. queued: the prepared
        request this is, so the window's note offers the next."""
        def job() -> dict[str, Any]:
            if self._headed and self._window == "sign_in":
                raise PortalError("signing_in", "Finish signing in first: close the Wizard sign-in window, then open the "
                                                "request form again.")
            page = self._request_page()
            if page is None:
                context = self._launch(headed=True, window="access_request")
                page = context.pages[0] if context.pages else context.new_page()
            self._show_request(page, AccessWindow(portal, address, answers, queued=queued, **_route(route)))
            with contextlib.suppress(Exception):
                page.bring_to_front()
            return self.status_now()
        return self.run(job, timeout=90)

    def _request_page(self) -> Any:
        """The open access request window's page, to show the next request in."""
        if not (self._headed and self._window == "access_request" and self._context is not None):
            return None
        try:
            pages = [p for p in self._context.pages if not p.is_closed()]
        except Exception:  # noqa: BLE001 - the window was closed
            return None
        return pages[0] if pages else None

    def _show_request(self, page: Any, request: AccessWindow) -> None:
        if self._request is not None:
            access_requests.remember_seen(self.root, self._request.portal.id, self._request.seen)
        self._request = request
        self._headed_since = time.monotonic()  # each request has the window's full time, so a long list is not cut short
        with contextlib.suppress(Exception):  # the person sees the page and its error
            page.goto(request.address, wait_until="domcontentloaded", timeout=45_000)
        if request.open_steps:
            self._follow(page, request)
        elif request.tables and access_requests.start_page(request.portal, request.address):
            request.note = (f"This request opens only the catalog's start page, not {', '.join(request.tables)}'s page "
                            "(it was prepared before Wizard took the way to the table): find it yourself, and Wizard "
                            "fills the form when it opens, or ask Gemini to prepare it again.")
        self._fill_request()
        if not request.form_seen and request.tables and request.note is None:
            self._open_form(page, request)
            self._fill_request()

    def _follow(self, page: Any, request: AccessWindow) -> None:
        """Reach the table's page from the request's address with the steps Gemini proved (search, open the result), in
        the person's window: the same click refusals as Gemini's own steps, only this portal's pages."""
        what = ", ".join(request.tables) or "the table"
        self._acting = "follow"
        try:
            self._follow_steps(page, request, what)
        finally:
            self._acting = None
        with contextlib.suppress(Exception):
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
            page.wait_for_timeout(800)

    def _follow_steps(self, page: Any, request: AccessWindow, what: str) -> None:
        for number, step in enumerate(request.open_steps, 1):
            try:
                if step["action"] == "goto":
                    target = _address(request.portal, str(step.get("url") or ""), page.url)
                    if not access_requests.on_portal(request.portal, (urlsplit(target).hostname or "").lower()):
                        raise PortalError("host_not_allowed", f"{urlsplit(target).hostname} is not {request.portal.name}")
                self._step(page, request.portal, {**step, "timeout_ms": min(int(step.get("timeout_ms") or
                                                                                access_requests.STEP_TIMEOUT_MS),
                                                                            access_requests.STEP_TIMEOUT_MS)}, {})
            except Exception as error:  # noqa: BLE001 - the page changed since Gemini proved the steps
                reason = error.message if isinstance(error, PortalError) else _first_line(error)
                request.note = (f"Wizard could not reach {what} in the catalog (step {number}, {step['action']}: "
                                f"{reason[:160]}). Find it yourself: Wizard fills the request form when it opens.")
                return

    def _open_form(self, page: Any, request: AccessWindow) -> None:
        """Press the control that opens the table's request form, once, with the portal's writes stopped for a few
        seconds: if pressing it would file the request itself, what it sends is stopped and the person is told."""
        if request.pressed or not access_requests.on_portal(request.portal, (urlsplit(page.url).hostname or "").lower()):
            return
        request.pressed = True
        try:
            found = page.evaluate(PICK, {"mode": "opener", "value": request.form_button}) or {}
        except Exception as error:  # noqa: BLE001 - navigating
            log.debug("request form opener not looked for: %s", _first_line(error))
            found = {}
        if found.get("count") != 1:
            named = f"'{request.form_button}'" if request.form_button else "Request access"
            request.note = (f"Press {named} (or the control that opens the request form) on this page: Wizard "
                            + ("found several." if (found.get("count") or 0) > 1 else "did not find it.")
                            + " It fills the form when it opens.")
            return
        self._guard(page)
        self._acting = "open"
        try:
            page.locator("[data-wizard-open]").first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception as error:  # noqa: BLE001 - the control went away
            request.note = f"Press {found.get('text') or 'Request access'} on this page: Wizard could not ({_first_line(error)[:120]})."
            return
        finally:
            self._acting = None
        if request.stopped:
            request.note = (f"Wizard pressed {found.get('text')} and stopped what the page sent then "
                            f"({'; '.join(request.stopped[:2])}), in case that filed the request. If the form did not "
                            "open, press it yourself.")
        else:
            request.note = f"Wizard pressed {found.get('text')} to open the request form."

    def _guard(self, page: Any, seconds: float = OPEN_GUARD_S, allow: dict[str, str] | None = None) -> None:
        self._unguard()
        self._guard_until = time.monotonic() + seconds
        self._guarded, self._guard_allow = page, allow
        page.route("**/*", self._guard_route)

    def _unguard(self) -> None:
        page, self._guarded, self._guard_allow = self._guarded, None, None
        if page is not None:
            with contextlib.suppress(Exception):  # the page is gone
                page.unroute("**/*", self._guard_route)

    def _guard_route(self, route: Any) -> None:
        """While a request form Wizard opened appears, a request that would change something in the portal is stopped
        (the person's own Submit comes later, when the guard is gone)."""
        request = route.request
        reason = None
        allowed = self._guard_allow is not None and access_requests.path_matches(self._guard_allow, request.url)
        if time.monotonic() <= self._guard_until and request.method.upper() != "GET" and not allowed:
            try:
                body = request.post_data
            except Exception:  # noqa: BLE001 - a binary body
                body = None
            reason = portals.write_reason(request.method, request.url, body)
        if reason:
            if self._request is not None:
                self._request.stopped.append(f"{request.method} {urlsplit(request.url).path[:80]}")
            route.abort()
        else:
            route.continue_()

    def _next_request(self, page: Any) -> None:
        """The person pressed Next request in the window's note: show the next prepared request that is not opened."""
        request = self._request
        if request is None:
            return
        item = access_requests.next_waiting(self.root, request.portal.id, after=request.queued)
        if item is not None:
            self._open_item(page, request.portal, item, "next")

    def _open_item(self, page: Any, portal: Portal, item: dict[str, Any], by: str) -> bool:
        """Show a prepared request in the window (Next request, or Wizard sending the approved ones)."""
        try:
            address = access_requests.check_address(portal, str(item["address"]))
        except access_requests.AccessFormError:
            access_requests.remove(self.root, portal.id, [item["id"]])
            return False
        access_requests.mark_opened(self.root, portal.id, item["id"])
        saved = access_requests.form(self.root, portal)["fields"]
        answers = access_requests.answers(saved, item.get("answers") or [], item.get("tables") or [])
        if self.audit is not None:
            with contextlib.suppress(Exception):  # the audit never stops the person's window
                self.audit("portals:access_request", system=portal.id, detail={"tables": item.get("tables") or [],
                                                                              "queued": item["id"], "by": by})
        self._show_request(page, AccessWindow(portal, address, answers, queued=item["id"], **_route(item)))
        return True

    # Sending the requests the person approved -----------------------------------------------------------------------
    def send_requests(self, portal: Portal, ids: list[str]) -> dict[str, Any]:
        """Send the prepared requests the person approved, one after another in the visible request window, the way their
        own proven request went: reach the table, open its form, fill it, press the same Submit, and check the portal
        answers the same request the same way. The first that does not go through stops the rest."""
        def job() -> dict[str, Any]:
            if self._headed and self._window == "sign_in":
                raise PortalError("signing_in", "Finish signing in first: close the Wizard sign-in window, then send again.")
            if not access_requests.sending(self.root, portal.id)["enabled"]:
                raise PortalError("sending_off", "Sending is off: submit one request yourself first, then turn it on.")
            items = {i["id"]: i for i in access_requests.to_send(self.root, portal.id, ids)}
            self._batch = [i for i in ids if i in items]
            self._batch_sent = 0
            if not self._batch:
                raise PortalError("nothing_to_send", "These requests are sent or no longer prepared.")
            page = self._request_page()
            if page is None:
                context = self._launch(headed=True, window="access_request")
                page = context.pages[0] if context.pages else context.new_page()
            if not self._open_item(page, portal, items[self._batch[0]], "send"):
                self._batch = []
                raise PortalError("invalid_request", "The first request's page is not an address of this portal.")
            with contextlib.suppress(Exception):
                page.bring_to_front()
            self._drive_batch()
            return self.status_now()
        return self.run(job, timeout=150)

    def stop_sending(self) -> dict[str, Any]:
        def job() -> dict[str, Any]:
            if self._batch and self._request is not None:
                self._request.note = f"Sending stopped by you after {self._batch_sent} request(s)."
            self._batch = []
            return self.status_now()
        return self.run(job, timeout=30)

    def _complete(self, request: AccessWindow) -> list[str]:
        """What is still missing before Wizard may press Submit: every saved answer filled or already there."""
        handled = set(request.filled) | set(request.kept)
        missing = [access_requests.name(a) for a in request.answers if not a.get("auto")
                   and access_requests.name(a) not in handled]
        return [*missing, *[u for u in request.unpicked if u not in missing]] if request.form_seen else ["the form"]

    def _drive_batch(self) -> None:
        """One step of sending: when the shown request's form is complete, submit it and show the next one."""
        request = self._request
        if not self._batch or request is None or request.queued != self._batch[0]:
            return
        missing = self._complete(request)
        if missing:
            if time.monotonic() - request.shown_at > SEND_WAIT_S:
                self._stop_batch(request, f"its form was not complete after {SEND_WAIT_S} seconds "
                                          f"({', '.join(missing[:4])} missing)")
            return
        page = request.form_page
        went, detail = self._submit(page, request)
        if not went:
            self._stop_batch(request, detail)
            return
        self._batch.pop(0)
        self._batch_sent += 1
        while self._batch:
            item = next((i for i in access_requests.to_send(self.root, request.portal.id, [self._batch[0]])), None)
            if item is not None and self._open_item(page, request.portal, item, "send"):
                return
            self._batch.pop(0)
        request.note = f"Wizard sent {self._batch_sent} request(s) you approved. {detail}"

    def _stop_batch(self, request: AccessWindow, reason: str) -> None:
        if request.queued:
            access_requests.mark_failed(self.root, request.portal.id, request.queued, reason)
        left = len(self._batch) - 1
        self._batch = []
        request.note = (f"Wizard stopped sending: this request did not go through ({reason}). Check it and submit it "
                        f"yourself, or remove it; {left} other approved request(s) were not sent.")
        if self.audit is not None:
            with contextlib.suppress(Exception):
                self.audit("portals:access_submitted", system=request.portal.id, outcome="failed",
                           detail={"tables": request.tables, "by": "wizard", "reason": reason[:300]})

    def _submit(self, page: Any, request: AccessWindow) -> tuple[bool, str]:
        """Press the Submit the person pressed on their own proven request, letting through only the request it sent
        then (same method, host and path) and stopping any other change; then check the portal's answer is the same."""
        proof = access_requests.sending(self.root, request.portal.id)["proof"]
        if not proof or page is None:
            return False, "sending is off"
        try:
            found = page.evaluate(PICK, {"mode": "submit", "value": proof["button"]}) or {}
        except Exception as error:  # noqa: BLE001 - navigating
            return False, f"the form moved ({_first_line(error)[:100]})"
        if found.get("count") != 1:
            return False, f"Wizard found {found.get('count') or 0} controls named '{proof['button']}' on the form"
        match = proof.get("match") or {}
        self._guard(page, seconds=SUBMIT_WAIT_MS / 1000 + 5, allow=match)
        self._acting = "submit"
        try:
            with page.expect_response(lambda r: r.request.method.upper() == proof["method"]
                                      and access_requests.path_matches(match, r.url), timeout=SUBMIT_WAIT_MS) as answer:
                page.locator("[data-wizard-submit]").first.click(timeout=5000)
            response = answer.value
            status = int(response.status)
            try:
                reply = response.text()[:20_000]
            except Exception:  # noqa: BLE001 - the page moved on
                reply = ""
        except Exception as error:  # noqa: BLE001 - no answer: a check on the form, a question answered Cancel...
            return False, f"no {proof['method']} {proof.get('path') or ''} went out after {proof['button']} ({_first_line(error)[:120]})"
        finally:
            self._acting = None
            self._unguard()
        path = urlsplit(response.url).path
        if not 200 <= status < 300:
            return False, f"the portal answered {status}"
        got = access_requests.expect_fields(reply)
        for key, value in (proof.get("expect") or {}).items():
            if got.get(key) != value:
                return False, f"the portal answered {key} = {got.get(key)!r} where your own request had {value!r}"
        if request.queued:
            access_requests.mark_sent(self.root, request.portal.id, request.queued, "wizard", status, path)
        if self.audit is not None:
            with contextlib.suppress(Exception):
                self.audit("portals:access_submitted", system=request.portal.id,
                           detail={"tables": request.tables, "by": "wizard", "method": proof["method"],
                                   "path": path[:200], "status": status})
        page.wait_for_timeout(800)
        return True, f"The last: {', '.join(request.tables) or 'the request'} ({proof['method']} {path[:60]}, {status})."

    def _fill_request(self, closing: bool = False) -> None:
        request = self._request
        if request is None or self._context is None:
            return
        request.last = time.monotonic()
        place = access_requests.place(self.root, request.portal.id, request.queued) if request.queued else None
        queue = {**place, "tables": ", ".join(next((i.get("tables") or [] for i in access_requests.queue(
            self.root, request.portal.id) if i["id"] == request.queued), []))[:300]} if place else None
        for page in list(self._context.pages):
            if not access_requests.on_portal(request.portal, (urlsplit(page.url).hostname or "").lower()):
                continue  # only this portal's own pages: never another site's form
            done = request.done.setdefault(page.url.split("#")[0], [])
            page_filled = request.page_filled.setdefault(page.url.split("#")[0], [])
            try:
                result = page.evaluate(FILL, {"answers": request.answers, "done": done, "queue": queue,
                                              "filled_before": len(page_filled), "note": request.note})
            except Exception as error:  # noqa: BLE001 - navigating, or the page closed: the next round fills it
                log.debug("access request fill skipped a page: %s", _first_line(error))
                continue
            if not isinstance(result, dict):
                continue
            for label in [*result.get("filled", []), *result.get("kept", [])]:
                if label not in done:
                    done.append(label)
            request.kept = list(dict.fromkeys([*request.kept, *[str(k) for k in result.get("kept", [])]]))
            if result.get("filled") or result.get("kept") or result.get("picks"):
                request.form_page = page
            if not request.form_seen and (result.get("filled") or result.get("kept") or result.get("picks")):
                request.form_seen = True
                with contextlib.suppress(OSError):
                    access_requests.remember_page(self.root, request.portal.id, request.tables, page.url)
            if not closing:
                for pick in result.get("picks") or []:
                    if not isinstance(pick, dict) or pick.get("name") in done:
                        continue
                    done.append(str(pick.get("name")))  # one try per field and page: never a tug of war with the person
                    if self._pick(page, pick):
                        result.setdefault("filled", []).append(pick["name"])
                    elif pick["name"] not in request.unpicked:
                        request.unpicked.append(str(pick["name"]))
            page_filled.extend(n for n in result.get("filled", []) if n not in page_filled)
            request.filled = list(dict.fromkeys([*request.filled, *result.get("filled", [])]))
            request.missing = list(dict.fromkeys([*[str(m) for m in result.get("missing", [])], *request.unpicked]))[:20]
            for label in result.get("seen", []):
                if isinstance(label, str) and label not in request.seen and len(request.seen) < access_requests.MAX_SEEN:
                    request.seen.append(label[:access_requests.MAX_LABEL])
            if result.get("next") and not closing:
                self._next_request(page)
                return
        if not closing and self._writes:
            self._observe(request)

    def _pick(self, page: Any, pick: dict[str, Any]) -> bool:
        """Choose the saved option in one of the form's own drop-downs: click it open, type the answer into the list's
        search box when the option is not shown, click the option that matches. Only the drop-down portal_fill.js marked
        and an option of the list it opened are clicked (portal_pick.js refuses buttons, links and submits); nothing is
        pressed. When no option matches, what Wizard typed is cleared and the list it opened is closed again."""
        mark, value = str(pick.get("mark") or ""), str(pick.get("value") or "")
        control = page.locator(f'[data-wizard-pick="{mark}"]').first
        opened = typed = False
        acting, self._acting = self._acting, self._acting or "pick"
        try:
            page.evaluate(PICK, {"mode": "before", "mark": mark})
            if not pick.get("typing"):
                control.click(timeout=3000)
                opened = True
                if self._choose(page, mark, value, wait_ms=600):
                    return True
            for text in access_requests.search_texts(value):
                if not page.evaluate(PICK, {"mode": "search", "mark": mark}):
                    break
                page.locator("[data-wizard-search]").first.fill(text, timeout=3000)
                typed = True
                if self._choose(page, mark, value, wait_ms=PICK_WAIT_MS):
                    return True
            if typed:
                with contextlib.suppress(Exception):
                    page.locator("[data-wizard-search]").first.fill("", timeout=2000)
            if opened and (page.evaluate(PICK, {"mode": "options", "mark": mark, "value": ""}) or {}).get("open"):
                with contextlib.suppress(Exception):
                    control.click(timeout=2000)
            return False
        except Exception as error:  # noqa: BLE001 - the drop-down moved or went: the person chooses it
            log.debug("access request pick failed: %s", _first_line(error))
            return False
        finally:
            self._acting = acting
            with contextlib.suppress(Exception):
                page.evaluate(PICK, {"mode": "clear"})

    def _choose(self, page: Any, mark: str, value: str, wait_ms: int) -> bool:
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            found = page.evaluate(PICK, {"mode": "options", "mark": mark, "value": value}) or {}
            if found.get("found"):
                page.locator("[data-wizard-option]").first.click(timeout=3000)
                page.wait_for_timeout(250)
                state = page.evaluate(PICK, {"mode": "state", "mark": mark}) or {}
                if not state.get("empty", True):
                    with contextlib.suppress(Exception):
                        page.evaluate("m => { const e = document.querySelector(`[data-wizard-pick=\"${m}\"]`); if (e) {"
                                      " e.setAttribute('data-wizard-filled', ''); e.style.outline = '2px solid #6d4aff'; e.style.outlineOffset = '1px';"
                                      " e.title = e.title || 'Chosen by Wizard from your saved answers'; } }", mark)
                    return True
                return False
            if found.get("several") or time.monotonic() >= deadline:
                return False
            page.wait_for_timeout(200)

    def status_now(self) -> dict[str, Any]:
        state = self._state()
        request = self._request if self._headed else None
        place = access_requests.place(self.root, request.portal.id, request.queued) if request and request.queued else None
        return {"browser": portals.CHANNELS[self.settings.channel], "signing_in": self._headed,
                "window": self._window if self._headed else None,
                **({"access_request": {"system": request.portal.id, "filled": request.filled, "missing": request.missing,
                                       **({"note": request.note} if request.note else {}),
                                       **({"sending": {"left": len(self._batch), "sent": self._batch_sent}}
                                          if self._batch else {}),
                                       **({"queued": {"id": request.queued, **place}} if place else {})}}
                   if request else {}),
                "running": self._context is not None, "last_sign_in": state.get("last_sign_in"),
                "portals": [{"id": p.id, "name": p.name, "host": p.host,
                             **({"parts": [{"id": part.id, "name": part.label, "host": part.host} for part in p.parts]}
                                if p.parts else {}),
                             **({"access_requests": True} if p.id in access_requests.REQUEST_PORTALS else {})}
                            for p in self.settings.portals]}

    def status(self) -> dict[str, Any]:
        return self.status_now()

    def check(self) -> dict[str, Any]:
        """Open each portal (each application of one that has several) in the background and say whether it is
        signed in (the page stays on the portal's host and asks for no password)."""
        pages = [(portal, *page) for portal in self.settings.portals for page in portal.pages]

        def job() -> dict[str, Any]:
            if self._headed:
                raise PortalError("signing_in", "Close Wizard's browser window first (sign-in or access request).")
            results = []
            for portal, page_id, name, url in pages:
                page = self._ready_page()
                self._log = CallLog()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(1500)
                    results.append({"id": page_id, "name": name, "signed_in": not self._signs_in(page, portal),
                                    "title": (page.title() or "")[:120], "host": urlsplit(page.url).hostname or ""})
                except Exception as error:  # noqa: BLE001 - reported per portal
                    results.append({"id": page_id, "name": name, "signed_in": False,
                                    "error": str(error).splitlines()[0][:200]})
                finally:
                    self._log = None
            return {"portals": results}
        return self.run(job, timeout=60 + 60 * len(pages))

    def _signs_in(self, page: Any, portal: Portal) -> bool:
        """The page asks for a sign-in: it left the reachable hosts, it is an identity provider's page (a host the
        person's sign-in went through outside the portals' domains), or it shows a password field or sign-in text."""
        host = (urlsplit(page.url).hostname or "").lower()
        if host and not self.policy.allowed(host):
            return True
        if host and host in self.policy.learned and not self.policy.portal_domain(host):
            return True
        try:
            # As Metronome reads GSCM: a visible password field, two sign-in phrases, or one beside an email field (a
            # phrase alone in a portal's footer is not a sign-in page).
            return bool(page.evaluate(
                "markers => { const shown = s => [...document.querySelectorAll(s)].some(e => e.offsetParent !== null);"
                " const text = document.body ? document.body.innerText.slice(0, 5000).toLowerCase() : '';"
                " const found = markers.filter(m => text.includes(m)).length;"
                " return shown('input[type=password]') || found >= 2 || (found >= 1 && shown('input[type=email]')); }",
                list(SIGN_IN_MARKERS)))
        except Exception:  # noqa: BLE001 - navigating
            return False

    # Gemini's steps ----------------------------------------------------------------------------------------------------
    def _ready_page(self) -> Any:
        if self._headed and self._window == "access_request":
            raise PortalError("signing_in", "The person has an access request form open in Wizard's browser window. Ask "
                                            "them to submit it (or not) and close that window, then try again.")
        if self._headed:
            raise PortalError("signing_in", "The person is signing in to the portals in Wizard's browser window. Ask them "
                                            "to finish and close that window, then try again.")
        if self._context is None:
            self._launch(headed=False)
        pages = [p for p in self._context.pages if not p.is_closed()]
        if self._page is None or self._page.is_closed():
            self._page = pages[-1] if pages else self._context.new_page()
        for extra in pages[:-MAX_PAGES]:
            if extra is not self._page:
                extra.close()
        return self._page

    def execute(self, portal: Portal, steps: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
        """Run Gemini's steps on the browser thread; see portal_tools.Step for what each step does."""
        def job() -> dict[str, Any]:
            page = self._ready_page()
            self._log = CallLog()
            outputs: list[dict[str, Any]] = []
            stopped: PortalError | None = None
            started = time.monotonic()
            try:
                if page.url in ("", "about:blank") and steps and steps[0].get("action") not in ("goto", "request"):
                    page.goto(portal.url, wait_until="domcontentloaded", timeout=60_000)
                for index, step in enumerate(steps):
                    if time.monotonic() - started > CALL_LIMIT_S - 20:
                        stopped = PortalError("browser_timeout", f"Stopped before step {index + 1}: the steps took too long.")
                        break
                    page = self._page or page
                    refused_before = len(self._log.blocked)
                    try:
                        result = self._step(page, portal, step, params)
                    except PortalError as error:
                        stopped = PortalError(error.code, f"Step {index + 1} ({step.get('action')}): {error.message}")
                        break
                    except Exception as error:  # noqa: BLE001 - Playwright's own errors, in words
                        refused = self._log.blocked[refused_before:]
                        code = "request_refused" if refused else "step_failed"
                        stopped = PortalError(code, f"Step {index + 1} ({step.get('action')}) failed: {_first_line(error)}.")
                        break
                    if result is not None:
                        outputs.append({"step": index + 1, "action": step.get("action"),
                                        "name": step.get("save_as") or None, **result})
                page = self._page or page
                if self._signs_in(page, portal):
                    raise PortalError("sign_in_required",
                                      f"{portal.name} asks for a sign-in in Wizard's browser. Tell the user to open "
                                      f"Settings → Portals and press 'Sign in to the portals', sign in to {portal.name} "
                                      "in the window that opens, then close it and ask again.")
                if stopped is not None and not outputs:
                    raise stopped
                result = {"outputs": outputs, **self._page_state(page), "log": self._finish_log()}
                if stopped is not None:
                    result["stopped"] = {"code": stopped.code, "message": stopped.message,
                                         "note": "The steps before this one ran; their results are above."}
                return result
            except PortalError as error:
                error.message += self._log_note()
                raise
            finally:
                self._log = None
        return self.run(job)

    def _page_state(self, page: Any) -> dict[str, Any]:
        try:
            title = page.title()
        except Exception:  # noqa: BLE001 - navigating
            title = ""
        frames = [{"name": f.name, "url": portals.redact_url(f.url)[:200]} for f in page.frames[1:12] if f.url
                  not in ("", "about:blank")]
        return {"page": {"url": portals.redact_url(page.url)[:300], "title": title[:200], "frames": frames}}

    def _finish_log(self) -> dict[str, Any]:
        assert self._log is not None
        shown = []
        for item in [r for r in self._log.requests if r.resource != "document" or r.method != "GET"][-15:]:
            preview = ""
            if item.response is not None and any(t in item.content_type for t in TEXT_TYPES):
                try:
                    preview = portals.redact_text(item.response.text(), 800)
                except Exception:  # noqa: BLE001 - body no longer available
                    preview = "(body not available)"
            shown.append({"method": item.method, "url": portals.redact_url(item.url)[:400], "type": item.resource,
                          "status": item.status, "content_type": item.content_type, "size": item.size,
                          "body": portals.redact_text(item.body, 1500) if item.body else None, "response": preview})
        return {"requests": shown, "blocked": self._log.blocked[-20:], "dialogs": self._log.dialogs[-10:],
                "console_errors": self._log.console[-10:]}

    def _log_note(self) -> str:
        if self._log is None:
            return ""
        notes = []
        if self._log.blocked:
            notes.append("Refused by Wizard's read-only rules: " + "; ".join(
                f"{b['method']} {b['url'][:120]} ({b['why']})" for b in self._log.blocked[-5:]))
        if self._log.dialogs:
            notes.append("Dialogs: " + " | ".join(self._log.dialogs[-3:]))
        return (" " + " ".join(notes)) if notes else ""

    def _frame(self, page: Any, name: str | None) -> Any:
        if not name:
            return page.main_frame
        for frame in page.frames:
            if frame.name == name:
                return frame
        for frame in page.frames:
            if name in frame.url:
                return frame
        names = [f.name or portals.redact_url(f.url)[:80] for f in page.frames[1:12]]
        raise PortalError("frame_not_found", f"No frame named or addressed '{name}'. Frames now: {', '.join(names) or 'none'}.")

    def _locator(self, page: Any, step: dict[str, Any]) -> Any:
        frame = self._frame(page, step.get("frame"))
        if step.get("selector"):
            locator = frame.locator(step["selector"])
        elif step.get("role"):
            locator = frame.get_by_role(step["role"], name=step.get("name"), exact=True) if step.get("name") \
                else frame.get_by_role(step["role"])
        elif step.get("text"):
            locator = frame.get_by_text(step["text"], exact=True)
        else:
            raise PortalError("invalid_step", "Name the element with selector, role (+ name) or text.")
        count = locator.count()
        if count == 0:
            locator.first.wait_for(state="attached", timeout=step.get("timeout_ms") or 30_000)
            count = locator.count()
        index = step.get("nth") or 0
        if index >= count:
            raise PortalError("element_not_found", f"Only {count} element(s) match; nth {index} does not exist.")
        return locator.nth(index), count

    def _step(self, page: Any, portal: Portal, step: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
        action = step["action"]
        timeout = step.get("timeout_ms") or 30_000
        if action == "goto":
            target = _address(portal, step["url"], page.url)
            if not self.policy.allowed(urlsplit(target).hostname):
                raise PortalError("host_not_allowed", f"{urlsplit(target).hostname} is not a portal address.")
            response = page.goto(target, wait_until="domcontentloaded", timeout=max(timeout, 45_000))
            return {"status": response.status if response else None, "url": portals.redact_url(page.url)[:300]}
        if action == "back":
            page.go_back(wait_until="domcontentloaded", timeout=timeout)
            return None
        if action == "use_page":
            pages = [p for p in self._context.pages if not p.is_closed()]
            index = step.get("nth") or 0
            if index >= len(pages):
                raise PortalError("page_not_found", f"{len(pages)} page(s) are open.")
            self._page = pages[index]
            self._page.bring_to_front()
            return {"pages": [portals.redact_url(p.url)[:200] for p in pages]}
        targeted = bool(step.get("selector") or step.get("role") or step.get("text"))
        if action in ("click", "fill", "select") or (action == "press" and targeted):
            element, count = self._locator(page, step)
            if action == "click":
                descriptor = element.evaluate(
                    "el => { const own = el.closest('[id]'); return {text: (el.innerText || el.textContent || '').slice(0, 200),"
                    " aria: el.getAttribute('aria-label'), title: el.getAttribute('title'), value: el.value,"
                    " name: el.getAttribute('name'), alt: el.getAttribute('alt'), id: el.id || (own && own.id) || ''} }")
                refusal = portals.click_refusal(descriptor)
                if refusal:
                    raise PortalError("click_refused", f"Wizard does not click this control because {refusal}: portal "
                                                       "scripts only read.")
                element.click(timeout=timeout)
            elif action == "fill":
                element.fill(str(step.get("value") or ""), timeout=timeout)
            elif action == "select":
                element.select_option(str(step.get("value") or ""), timeout=timeout)
            else:
                element.press(str(step.get("value") or "Enter"), timeout=timeout)
            return {"matched": count} if count > 1 else None
        if action == "press":
            page.keyboard.press(str(step.get("value") or "Enter"))
            return None
        if action == "wait":
            if step.get("selector") or step.get("text") or step.get("role"):
                element, _ = self._locator(page, step)
                element.wait_for(state=step.get("value") or "visible", timeout=timeout)
            elif step.get("value") in ("load", "domcontentloaded", "networkidle"):
                page.wait_for_load_state(step["value"], timeout=timeout)
            else:
                page.wait_for_timeout(min(timeout, 30_000))
            return None
        if action == "evaluate":
            frame = self._frame(page, step.get("frame"))
            value = frame.evaluate(_script(step["script"], params, timeout))
            return {"value": value}
        if action == "request":
            return self._send(page, portal, step, params, timeout)
        if action == "read_table":
            frame = self._frame(page, step.get("frame"))
            target = step.get("selector") or (f"text={step['text']}" if step.get("text") else "table")
            value = frame.evaluate(_script("return W.readTable(P.__target, P.__nth);",
                                           {**params, "__target": target, "__nth": step.get("nth") or 0}, timeout))
            return {"value": value}
        if action == "look":
            looks = []
            for frame in page.frames[:10]:
                if frame.url in ("", "about:blank") and frame is not page.main_frame:
                    continue
                try:
                    found = frame.evaluate(_script("return W.look(P.__limit);", {"__limit": step.get("limit") or 60}, 15_000))
                except Exception as error:  # noqa: BLE001 - cross-origin or detached frame
                    found = {"error": _first_line(error)}
                looks.append({"frame": frame.name or ("main" if frame is page.main_frame else ""),
                              "url": portals.redact_url(frame.url)[:200], **(found if isinstance(found, dict) else {})})
            return {"value": {"frames": looks}}
        raise PortalError("invalid_step", f"Unknown action {action}.")

    def _send(self, page: Any, portal: Portal, step: dict[str, Any], params: dict[str, Any], timeout: int) -> dict[str, Any]:
        """One data request from the browser itself, with the person's session: fetch() in a page on the request's own
        origin, so Chrome's network stack (proxy, certificates, single sign-on) and every rule on page requests apply.
        The page the browser is on is used when it is on that origin (GSCM's client keeps running); otherwise a light
        page of that origin opens first, never the portal's heavy start page."""
        target = _address(portal, step["url"], page.url)
        parts = urlsplit(target)
        if not self.policy.allowed(parts.hostname):
            raise PortalError("host_not_allowed", f"{parts.hostname} is not a portal address.")
        method = str(step.get("method") or ("POST" if step.get("body") is not None else "GET")).upper()
        body = step.get("body")
        reason = portals.write_reason(method, target, body)
        if reason:
            if self._log is not None and len(self._log.blocked) < 40:
                self._log.blocked.append({"method": method, "url": portals.redact_url(target)[:300], "why": reason})
            raise PortalError("request_refused", f"Wizard refused {method} {portals.redact_url(target)[:200]}: {reason}.")
        here = urlsplit(page.url)
        if (here.scheme, here.netloc) != (parts.scheme, parts.netloc):
            page.goto(f"{parts.scheme}://{parts.netloc}/robots.txt", wait_until="commit", timeout=max(timeout, 30_000))
            if urlsplit(page.url).netloc != parts.netloc:
                raise PortalError("session_needed", f"{portal.name} sent the browser to {urlsplit(page.url).hostname}: its "
                                                    "session needs renewing. Open the portal first (goto its start page, "
                                                    "which signs in again through single sign-on), then send the request.")
        headers = {k: str(v) for k, v in (step.get("headers") or {}).items()
                   if k.lower() not in ("cookie", "host", "content-length")}
        request = {"url": target, "method": method, "headers": headers, "body": body}
        script = step.get("script") or DEFAULT_REPLY
        value = page.main_frame.evaluate(_script(script, params, timeout, prelude=SEND), request)
        return {"value": value}


# The request step: send it from the page, keep the reply as R ({status, contentType, text, data}) for the script.
SEND = """const __q = __arg;
const __reply = await fetch(__q.url, {method: __q.method, headers: __q.headers, credentials: 'include', redirect: 'manual',
  body: __q.method === 'GET' ? undefined : __q.body});
if (__reply.type === 'opaqueredirect') throw new Error('the portal answered with a redirect: its session needs renewing (goto its start page, then send the request again)');
const __text = await __reply.text();
const R = {status: __reply.status, contentType: (__reply.headers.get('content-type') || '').split(';')[0], text: __text};
R.data = W.parse(__text);
"""
# Without a script: one dataset with rows comes back as a table (evidence); otherwise an outline to write a script from.
DEFAULT_REPLY = """const sets = (R.data && R.data.datasets) || null;
if (sets) {
  const full = Object.keys(sets).filter(name => sets[name].rows.length);
  const code = Number((R.data.parameters || {}).ErrorCode || 0);
  if (R.status < 400 && code >= 0 && full.length === 1) return {...sets[full[0]], total_rows: sets[full[0]].rows.length, dataset: full[0]};
  return {status: R.status, parameters: R.data.parameters, datasets: Object.fromEntries(Object.entries(sets).map(
    ([name, d]) => [name, {columns: d.columns, total_rows: d.rows.length, first_rows: d.rows.slice(0, 5)}]))};
}
if (R.data && R.data.json !== undefined && R.status < 400) return R.data.json;
return {status: R.status, contentType: R.contentType, text: R.text.slice(0, 4000)};"""


def _route(route: dict[str, Any] | None) -> dict[str, Any]:
    """A request's way to its table's form, as the window keeps it: tables, open_steps, form_button."""
    route = route or {}
    return {"tables": [str(t) for t in route.get("tables") or []][:20],
            "open_steps": [s for s in route.get("open_steps") or [] if isinstance(s, dict)][:access_requests.MAX_STEPS],
            "form_button": str(route.get("form_button") or "")[:80]}


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    for marker in ("Call log:", "==========", "\n    at ", " at window.", " at __run"):
        text = text.split(marker)[0]
    return " ".join(text.split())[:400] or type(error).__name__


def _address(portal: Portal, url: str, current: str = "") -> str:
    """A step's address: absolute, or a path on the portal application the page is on (the Big Data Portal's
    information catalog or Superset), else on the portal's start page."""
    if url.startswith(("http://", "https://")):
        return url
    if not url.startswith("/"):
        url = "/" + url
    here = urlsplit(current)
    if here.scheme in ("http", "https") and (here.hostname or "").lower() in portal.hosts:
        return f"{here.scheme}://{here.netloc}" + url
    return portal.origin + url


def _script(body: str, params: dict[str, Any], timeout_ms: int, prelude: str = "") -> str:
    """Gemini's JavaScript as the body of an async function, with Wizard's helpers (W) and the parameters (P), and a
    time limit so a script that never settles cannot hold the browser. `prelude` runs first, inside the time limit,
    with the evaluate argument as __arg."""
    return (
        "async (__arg) => {\n" + HELPERS + "\nconst P = " + json.dumps(params, ensure_ascii=False) + ";\n"
        "const __run = async () => {\n" + prelude + body + "\n};\n"
        f"const __limit = new Promise((_, reject) => setTimeout(() => reject(new Error('the script did not finish within "
        f"{timeout_ms // 1000} s')), {timeout_ms}));\n"
        "const __value = await Promise.race([__run(), __limit]);\n"
        "return W.plain(__value);\n}"
    )


class PortalBrowsers:
    """One browser per person, made when first needed."""

    def __init__(self, settings: PortalSettings, home_for: Callable[[str], Path],
                 launcher: Callable[..., Any] | None = None, secrets: SecretStore | None = None,
                 audit: Callable[..., None] | None = None):
        self.settings = settings
        self.home_for = home_for
        self.launcher = launcher
        self.secrets = secrets
        self.audit = audit  # (user_id, action, system=..., detail=...): what the person's windows do on their own
        self._browsers: dict[str, PortalBrowser] = {}
        self._lock = threading.Lock()

    def for_user(self, user_id: str) -> PortalBrowser:
        with self._lock:
            browser = self._browsers.get(user_id)
            if browser is None:
                browser = PortalBrowser(self.settings, self.home_for(user_id) / "portal-browser", self.launcher,
                                        self.secrets)
                if self.audit is not None:
                    audit = self.audit
                    browser.audit = lambda action, _user=user_id, **detail: audit(_user, action, **detail)
                self._browsers[user_id] = browser
            return browser

    def shutdown(self) -> None:
        for browser in list(self._browsers.values()):
            browser.shutdown()

"""The person's Wizard browser: Google Chrome (or Edge) driven by Playwright, with its own profile, where Gemini's
portal scripts run in the background (headless) and the person signs in once in a visible window.

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
remembered so a later background session can renew it."""
from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import portals
from .portals import HostPolicy, Portal, PortalSettings

log = logging.getLogger("wizard.portals")

HELPERS = Path(__file__).with_name("portal_helpers.js").read_text(encoding="utf-8")
CAPTURE = Path(__file__).with_name("portal_capture.js").read_text(encoding="utf-8")
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
        self._last_used = time.monotonic()
        self._log: CallLog | None = None
        self._sign_in_hosts: set[str] = set()
        self._secrets = secrets
        self.session_file = root / "session.bin"
        self._session: list[dict[str, Any]] = self._load_session()
        self._seen: list[dict[str, Any]] | None = None  # the sign-in window's cookies, the last time Wizard looked

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

    def _idle(self) -> None:
        if self._context is None:
            return
        if self._headed:
            # The person's sign-in window: keep its events flowing, and finish when they close it or forget it.
            try:
                pages = self._context.pages
                if not pages:
                    raise RuntimeError("closed")
                pages[0].wait_for_timeout(250)
            except Exception:  # noqa: BLE001 - the window was closed
                self._finish_sign_in()
                return
            self._note_session()
            if time.monotonic() - self._headed_since > SIGN_IN_LIMIT_S:
                self._finish_sign_in()
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

    def _launch(self, headed: bool) -> Any:
        self._close()
        self.profile.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {"headless": not headed, "accept_downloads": False, "service_workers": "block",
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
            context.on("request", self._remember_sign_in_host)
        else:
            context.add_init_script(CAPTURE)
            context.route("**/*", self._route)
            if hasattr(context, "route_web_socket"):
                context.route_web_socket("**/*", self._route_socket)
            context.on("request", self._capture_request)
            context.on("response", self._capture_response)
            context.on("page", self._watch_page)
        self._context, self._headed = context, headed
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
        if self._log is not None:
            self._log.dialogs.append(f"{dialog.type}: {dialog.message[:300]}")
        with contextlib.suppress(Exception):  # already handled
            # Alerts are acknowledged; a confirmation ("Are you sure?") is always answered No.
            dialog.accept() if dialog.type in ("alert", "beforeunload") else dialog.dismiss()

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
            context = self._launch(headed=True)
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
        def job() -> dict[str, Any]:
            if self._headed:
                self._finish_sign_in()
            return self.status_now()
        return self.run(job, timeout=60)

    def _finish_sign_in(self) -> None:
        self._note_session()
        hosts = {h for h in self._sign_in_hosts if "." in h and not h.replace(".", "").isdigit()}
        learned = sorted(self.policy.learned | hosts)[:50]
        self.policy.learned = set(learned)
        if self._seen is not None:
            self._keep_session(self._seen)
            self._seen = None
        self._save_state(learned_hosts=learned, last_sign_in=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._close()
        self._headed = False

    def status_now(self) -> dict[str, Any]:
        state = self._state()
        return {"browser": portals.CHANNELS[self.settings.channel], "signing_in": self._headed,
                "running": self._context is not None, "last_sign_in": state.get("last_sign_in"),
                "portals": [{"id": p.id, "name": p.name, "host": p.host,
                             **({"parts": [{"id": part.id, "name": part.label, "host": part.host} for part in p.parts]}
                                if p.parts else {})} for p in self.settings.portals]}

    def status(self) -> dict[str, Any]:
        return self.status_now()

    def check(self) -> dict[str, Any]:
        """Open each portal (each application of one that has several) in the background and say whether it is
        signed in (the page stays on the portal's host and asks for no password)."""
        pages = [(portal, *page) for portal in self.settings.portals for page in portal.pages]

        def job() -> dict[str, Any]:
            if self._headed:
                raise PortalError("signing_in", "Finish signing in first: close the Wizard sign-in window.")
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
                if page.url in ("", "about:blank") and steps and steps[0].get("action") != "goto":
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


def _script(body: str, params: dict[str, Any], timeout_ms: int) -> str:
    """Gemini's JavaScript as the body of an async function, with Wizard's helpers (W) and the parameters (P), and a
    time limit so a script that never settles cannot hold the browser."""
    return (
        "async () => {\n" + HELPERS + "\nconst P = " + json.dumps(params, ensure_ascii=False) + ";\n"
        "const __run = async () => {\n" + body + "\n};\n"
        f"const __limit = new Promise((_, reject) => setTimeout(() => reject(new Error('the script did not finish within "
        f"{timeout_ms // 1000} s')), {timeout_ms}));\n"
        "const __value = await Promise.race([__run(), __limit]);\n"
        "return W.plain(__value);\n}"
    )


class PortalBrowsers:
    """One browser per person, made when first needed."""

    def __init__(self, settings: PortalSettings, home_for: Callable[[str], Path],
                 launcher: Callable[..., Any] | None = None, secrets: SecretStore | None = None):
        self.settings = settings
        self.home_for = home_for
        self.launcher = launcher
        self.secrets = secrets
        self._browsers: dict[str, PortalBrowser] = {}
        self._lock = threading.Lock()

    def for_user(self, user_id: str) -> PortalBrowser:
        with self._lock:
            browser = self._browsers.get(user_id)
            if browser is None:
                browser = PortalBrowser(self.settings, self.home_for(user_id) / "portal-browser", self.launcher,
                                        self.secrets)
                self._browsers[user_id] = browser
            return browser

    def shutdown(self) -> None:
        for browser in list(self._browsers.values()):
            browser.shutdown()

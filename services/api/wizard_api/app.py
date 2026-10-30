"""HTTP surface. Public API under /api/v1 (browser), loopback-only tool API under /internal/v1 (MCP shims)."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from wizard_agent import google_oauth, outbound
from wizard_agent.code_assist import CodeAssistRuntime, summarize_quota
from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, inherited_project, resolve_cli_js
from wizard_agent.prompting import correction_question, recurring_question
from wizard_agent.replay import ReplayRuntime
from wizard_agent.runtime import AgentFailure, AgentRuntime
from wizard_agent.secret_box import SecretBox
from wizard_connectors import access_requests, metronome
from wizard_connectors.content import errors, validate_content
from wizard_connectors.entitlements import Identity, IdentityDirectory, SystemRights
from wizard_connectors.paths import ROOT
from wizard_connectors.portal_browser import PortalBrowser, PortalBrowsers, PortalError
from wizard_connectors.portal_map import PortalMaps, Published
from wizard_connectors.tools import build_registry, build_services
from wizard_connectors.tools.systems import SystemChoice

from . import __version__, brain, knowledge_sync, settings_pane, systems
from .attachments import AttachmentError, public
from .config import Settings, kb_source, load_settings
from .metronome_client import MetronomeClient, MetronomeError
from .outlook import DraftError, open_outlook_draft
from .runs import Busy, RunManager, decode_systems, entitled_to, evidence_summary, public_schedule, step_about
from .security import REQUEST_HEADER, SECURITY_HEADERS, SESSION_COOKIE, session_token, verify
from .store import Store

OWNER_ID = "local-owner"
DOWNLOAD_TYPES = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12", ".xls": "application/vnd.ms-excel",
                  ".xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12"}
KB_IDLE_RESTART_S = 600  # restart for a new knowledge base only after 10 minutes without a request from the user
# Requests a page or a probe makes on its own (the quota ring polls every 5 minutes): not a sign someone is using Wizard.
BACKGROUND_PATHS = {"/api/v1/health", "/api/v1/ready", "/api/v1/account/gemini/quota"}
# A session in use is signed again once it is this old, so a Wizard left open (WizardBar keeps the page for days) is
# never signed out between two questions. It still lapses session_hours after the page last reached Wizard.
SESSION_RENEW_S = 3600
log = logging.getLogger("wizard.api")


class LogBuffer(logging.Handler):
    """The most recent server log records, shown in the UI's Log view in dev mode (WIZARD_DIAGNOSTICS)."""

    def __init__(self, size: int = 400):
        super().__init__(logging.INFO)
        self.lines: deque[str] = deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never break a request
            self.handleError(record)


LOG_BUFFER = LogBuffer()


def capture_logs() -> None:
    """Attach the buffer to the root logger (Wizard and libraries) and to uvicorn's own logger (it does not propagate;
    request tracebacks land there). Called at start-up because uvicorn replaces handlers when it configures logging."""
    for name in ("", "uvicorn"):
        logger = logging.getLogger(name)
        if LOG_BUFFER not in logger.handlers:
            logger.addHandler(LOG_BUFFER)
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/ready", "/api/v1/bootstrap", "/api/v1/session/login",
                "/api/v1/session/logout", "/api/v1/session/identities"}
TIMELINE_EVENTS = {"run_started", "status", "agent_session", "note", "tool_started", "tool_finished", "visual_added",
                   "check_result", "schedule_proposed", "access_request_proposed", "file_made", "warning", "run_failed",
                   "run_finished", "steer", "steer_read", "systems_changed", "system_requested"}
TERMINAL = {"run_finished", "run_failed"}
SUGGESTIONS = [
    {"story": "Executive", "question": "Which market gave us the best return on marketing investment last quarter — tie NERP "
                                       "spend to sell-through, share gain, and competitive switching, and rank them."},
    {"story": "Planner", "question": "Flag any model where sell-in is outpacing sell-out and installed-base growth is stalling — "
                                     "then check Smart Switch and app usage to tell me if it's a demand problem or a "
                                     "channel-stuffing problem."},
    {"story": "Conquest", "question": "Where are we winning switchers from Apple and Xiaomi according to Smart Switch, and does "
                                      "our investment and sell-out data support doubling down there?"},
]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(Body):
    user_id: str = Field(min_length=1, max_length=64)


class RunBody(Body):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    # The systems picker: the ids of the systems this question may use; None (or absent) is Auto.
    systems: list[str] | None = Field(default=None, max_length=30)


class SteerBody(Body):
    text: str = Field(default="", max_length=2000)
    call_id: str | None = Field(default=None, max_length=20, pattern=r"^c\d{1,4}$")  # a step of the run (Not this)
    reason: Literal["table", "filter", "period", "other"] | None = None


class SystemsBody(Body):
    systems: list[str] | None = Field(default=None, max_length=30)


class MemoryBody(Body):
    text: str = Field(min_length=1, max_length=500)
    run_id: str | None = Field(default=None, max_length=64)


class LocalFileBody(Body):
    path: str = Field(min_length=3, max_length=1000)


class DropBody(Body):
    paths: list[str] = Field(min_length=1, max_length=5)


class TitleBody(Body):
    title: str = Field(min_length=1, max_length=120)


class FeedbackBody(Body):
    category: Literal["wrong_source", "mismatched_period", "wrong_arithmetic", "omitted_contrary_signal",
                      "unsupported_certainty", "poor_chart", "access_problem", "helpful", "other"]
    note: str = Field(default="", max_length=2000)


class EmailDraftBody(Body):
    subject: str = Field(min_length=1, max_length=300)
    html: str = Field(min_length=1, max_length=3_000_000)


class RecurringBody(Body):
    # The Make recurring menu's choice; None: Gemini asks how often.
    cadence: Literal["daily", "weekly", "monthly"] | None = None


class SettingsBody(Body):
    # KEY -> new value; "" returns to the company value or the default; null keeps a secret unchanged.
    values: dict[str, str | None] = Field(max_length=40)


class SettingsTestBody(Body):
    section: Literal["postgres", "knowledge", "metronome"]
    values: dict[str, str | None] = Field(default_factory=dict, max_length=40)


class LinkCompleteBody(Body):
    state: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: str = Field(min_length=4, max_length=1024)


class AnswerBody(Body):
    label: str = Field(max_length=200)
    value: str = Field(default="", max_length=2000)


class AccessFormBody(Body):
    # The request page (optional) and the answers given on every access request.
    page: str = Field(default="", max_length=2000)
    fields: list[AnswerBody] = Field(default_factory=list, max_length=40)


class AccessRequestBody(Body):
    # Empty: the saved request page, else the catalog's start page, with the saved answers only.
    address: str | None = Field(default=None, max_length=2000)
    tables: list[str] = Field(default_factory=list, max_length=20)
    answers: list[AnswerBody] = Field(default_factory=list, max_length=20)


class InternalCall(Body):
    arguments: dict[str, Any] = Field(default_factory=dict)
    scope: str | None = Field(default=None, max_length=32)


def gemini_project(settings: Settings) -> str | None:
    """Wizard's GOOGLE_CLOUD_PROJECT, else the one the person's own Gemini CLI uses (~/.gemini/.env, ~/.env)."""
    return settings.google_cloud_project or inherited_project()[0]


def build_runtime(settings: Settings, secret_box: SecretBox, scopes: list[str]) -> AgentRuntime:
    if settings.runtime == "gemini-cli":
        cli_js = resolve_cli_js(settings.gemini_cli_js, ROOT)
        return GeminiCliRuntime(GeminiCliConfig(
            model=settings.model, internal_url=settings.internal_url, cli_js=cli_js, node=settings.node, scopes=scopes,
            google_cloud_project=gemini_project(settings), timeout_s=settings.run_timeout_s,
            fake_responses=Path(settings.gemini_fake_responses).resolve() if settings.gemini_fake_responses else None,
            shim_command=[str(ROOT / "wizard_mcp_shim.py")], proxy=settings.proxy, diagnostics=settings.diagnostics))
    if settings.runtime == "code-assist":
        return CodeAssistRuntime(settings.model, secret_box, gemini_project(settings), settings.thinking,
                                 proxy=settings.proxy, fallback_model=settings.fallback_model)
    return ReplayRuntime(settings.transcripts_dir, settings.replay_delay_s)


def _is_loopback(host: str | None) -> bool:
    try:
        return bool(host) and ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return host == "testclient"


def map_writer(settings: Settings) -> Any:
    """Commits a portal map to the knowledge-base repository with this PC's write token (Settings → Knowledge base)."""
    from wizard_documents import kb

    def write(files: dict[str, bytes], message: str) -> Published:
        assert settings.kb_repo and settings.kb_write_token
        try:
            commit = kb.write_files(settings.kb_repo, settings.kb_write_token, files, branch=settings.kb_ref,
                                    message=message, proxy=settings.proxy)
        except kb.PublishError as error:
            return Published("failed", str(error))
        except httpx.HTTPError as error:
            return Published("failed", outbound.explain(error, kb.API, settings.proxy))
        if commit is None:
            return Published("unchanged", f"{settings.kb_repo} already has this map.")
        return Published("published", f"Committed to {settings.kb_repo} ({settings.kb_ref}).", commit)
    return write


def create_app(settings: Settings | None = None, runtime: AgentRuntime | None = None,
               google_transport: httpx.AsyncBaseTransport | None = None,
               metronome_transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or load_settings()
    loaded_content = settings.content_dir
    if settings.content_dir:
        # Company content never stops Wizard: a file with an error is left out (and logged), and catalogs load as
        # navigation only whatever they claim (owner, 23 Oct 2026: Wizard stopped on a catalog marked ROWS_VERIFIED).
        problems = validate_content(settings.content_dir)
        for problem in problems:
            (log.error if problem.level == "error" else log.warning)("content: %s", problem)
        left_out = frozenset(p.where.split(" › ")[0] for p in errors(problems))
        if left_out:
            log.error("content: %d file(s) left out for errors: %s", len(left_out), ", ".join(sorted(left_out))[:500])
        services = build_services(contracts=settings.content_dir / "contracts" / "sources",
                                  knowledge=settings.content_dir / "knowledge", postgres=settings.postgres,
                                  postgres_name=settings.pg_name, real_content=True, skip=left_out)
    elif settings.kb_repo:
        # A knowledge base is configured but has never synced: load nothing rather than the synthetic examples.
        empty = settings.data_dir / "knowledge" / "none"
        services = build_services(contracts=empty / "contracts" / "sources", knowledge=empty / "knowledge",
                                  postgres=settings.postgres, postgres_name=settings.pg_name)
    else:
        services = build_services(postgres=settings.postgres, postgres_name=settings.pg_name)
    services.metronome, services.mail_domains = settings.metronome, settings.google_domains
    secret_box = SecretBox()
    if settings.portals:
        services.portals = PortalBrowsers(settings.portals, settings.user_home, secrets=secret_box)
        writer = map_writer(settings) if settings.kb_repo and settings.kb_write_token else None
        services.portal_maps = PortalMaps(settings.data_dir / "portal-maps",
                                          settings.content_dir / "portal-maps" if settings.content_dir else None, writer,
                                          {p.id: p.name for p in settings.portals.portals}, repo_prefix=settings.kb_path)
    portal_ids = [p.id for p in settings.portals.portals] if settings.portals else []
    registry = build_registry(services)
    identities = IdentityDirectory.load(settings.identities_file)
    store = Store(settings.data_dir / "wizard.sqlite3")
    if settings.install_mode or settings.local_user_email:
        # The person at this PC, with every platform right. Their email is the Google account they link (so `whoami
        # /upn` returning nothing, or a different domain, never blocks them); until then the configured one, if any.
        linked = store.link(OWNER_ID)
        email = (linked["google_email"] if linked else settings.local_user_email) or ""
        owner = Identity(id=OWNER_ID, email=email.lower(), name=settings.local_user_name or "You", role="Owner (local test)",
                         entitlements={system: SystemRights(reports=["*"], markets=["*"]) for system in
                                       [*(s.id for s in services.catalog.systems), *(["postgresql"] if services.postgres else []),
                                        *portal_ids]})
        others = [] if settings.desktop else [i for i in identities.all() if not owner.email or i.email != owner.email]
        identities = IdentityDirectory([owner, *others])
    interrupted = store.mark_interrupted()
    runtime = runtime or build_runtime(settings, secret_box, registry.scopes())
    manager = RunManager(settings, store, registry, services, runtime)
    kb = kb_source(settings)
    activity = {"last": time.monotonic()}

    def knowledge_status() -> dict[str, Any]:
        return knowledge_sync.status(settings.data_dir, kb, loaded_content)

    def restart_if_idle(quiet_s: float) -> bool:
        """Desktop app only: exit so WizardBar restarts the service on the newer knowledge base, when nobody is using it."""
        request_restart = getattr(app.state, "request_restart", None)
        if (request_restart is None or manager.active or time.monotonic() - activity["last"] < quiet_s
                or not knowledge_status().get("restart_pending")):
            return False
        log.info("restarting to load the new knowledge-base version")
        request_restart()
        return True

    async def sync_knowledge_forever() -> None:
        while True:
            await asyncio.sleep(settings.kb_sync_minutes * 60)
            result = await asyncio.to_thread(knowledge_sync.sync, kb, settings.data_dir, proxy=settings.proxy)
            if not result.ok:
                log.warning("knowledge base: %s", result.message)
            restart_if_idle(KB_IDLE_RESTART_S)

    async def restart_when_idle() -> None:
        while not restart_if_idle(KB_IDLE_RESTART_S):
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.diagnostics:
            capture_logs()
            build = settings_pane.installed_build()
            log.info("Wizard %s (build %s, commit %s, code in %s) started: runtime %s (%s), model %s, data %s, proxy %s",
                     __version__, build.get("version") or "development", str(build.get("commit") or "")[:12] or "-", ROOT,
                     runtime.kind, runtime.label(), settings.model, settings.data_dir, settings.proxy or "resolved per request")
        if interrupted:
            log.warning("%d run(s) were interrupted by a restart and marked failed", interrupted)
        background = []
        if kb and settings.desktop and settings.kb_sync_minutes:
            background.append(asyncio.create_task(sync_knowledge_forever()))
        if kb and settings.desktop:
            background.append(asyncio.create_task(restart_when_idle()))
        yield
        for task in background:
            task.cancel()
        await manager.shutdown()
        if services.portals is not None:
            await asyncio.to_thread(services.portals.shutdown)

    app = FastAPI(title="Wizard", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/v1/openapi.json")
    app.state.settings, app.state.store, app.state.manager, app.state.registry = settings, store, manager, registry
    app.state.restart_if_idle = restart_if_idle

    def identity_of(request: Request) -> Identity | None:
        if settings.auth_mode == "trusted-header":
            client = request.client.host if request.client else None
            email = request.headers.get(settings.identity_header, "").strip()
            if client not in settings.trusted_proxies or not email:
                return None
            return identities.by_login(email) or Identity(id=f"sso:{email.lower()}", email=email.lower(), name=email,
                                                           role="Unassigned", entitlements={})
        claims = verify(settings.session_secret, "session", request.cookies.get(SESSION_COOKIE))
        request.state.session_issued = float(claims.get("iat", 0)) if claims else None
        return identities.get(str(claims["u"])) if claims else None

    def start_session(response: Response, user_id: str) -> None:
        response.set_cookie(SESSION_COOKIE, session_token(settings.session_secret, user_id, settings.session_hours),
                            httponly=True, samesite="strict", secure=settings.secure_cookies, max_age=settings.session_hours * 3600)

    def me(request: Request) -> Identity:
        identity: Identity | None = request.state.identity
        if identity is None:
            raise HTTPException(401, "Sign in to use Wizard.")
        return identity

    def on_this_pc(request: Request) -> bool:
        """The browser and Wizard share a PC (a local install, signed in as its person): Wizard may open Outlook, save to
        Downloads and open files there. Behind a proxy that would happen on the server."""
        return settings.auth_mode == "fixture" and _is_loopback(request.client.host if request.client else None)

    def same_origin(origin: str, request: Request) -> bool:
        allowed = {settings.public_origin.rstrip("/")} if settings.public_origin else set()
        host = request.headers.get("host", "")
        allowed |= {f"http://{host}", f"https://{host}"}
        parts = urlsplit(origin)
        return f"{parts.scheme}://{parts.netloc}" in allowed

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get(REQUEST_HEADER) != "1" or (origin and not same_origin(origin, request)):
                return _secure(JSONResponse({"error": "Request blocked: missing Wizard request header or foreign origin."},
                                            status_code=403))
        if path.startswith("/api/") and path not in BACKGROUND_PATHS:
            activity["last"] = time.monotonic()
        request.state.identity = identity_of(request) if path.startswith("/api/") else None
        if path.startswith("/api/") and path not in PUBLIC_PATHS and request.state.identity is None:
            return _secure(JSONResponse({"error": "Sign in to use Wizard.", "login_required": True}, status_code=401))
        response = await call_next(request)
        if path.startswith(("/api/", "/internal/")):
            response.headers["Cache-Control"] = "no-store"
        issued = getattr(request.state, "session_issued", None)
        if (issued is not None and request.state.identity is not None and not path.startswith("/api/v1/session/")
                and time.time() - issued > SESSION_RENEW_S):
            start_session(response, request.state.identity.id)
        return _secure(response)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        body = error.detail if isinstance(error.detail, dict) else {"error": error.detail}
        return JSONResponse(body, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "Invalid request.", "details": [e.get("msg") for e in error.errors()[:5]]}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=error)
        return JSONResponse({"error": "Wizard hit an internal error. It was logged."}, status_code=500)

    # Health and bootstrap ----------------------------------------------------------------------------------------------
    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, Any]:
        # Real content may hold knowledge notes only; the synthetic examples must always have platforms.
        checks = {"store": True, "catalog": bool(services.catalog.systems) or bool(settings.content_dir or kb),
                  "runtime": runtime.kind,
                  "content": str(settings.content_dir) if settings.content_dir else
                  ("knowledge base not synced yet" if kb else "synthetic (built-in)"),
                  "knowledge_base": knowledge_status(), "provision": settings.provision,
                  "runtime_label": runtime.label(), "secret_store": secret_box.kind, "auth_mode": settings.auth_mode,
                  "frontend_built": (settings.web_dist / "index.html").is_file()}
        return {"ready": all(v for k, v in checks.items() if isinstance(v, bool) and k != "frontend_built"), "checks": checks}

    async def account_status(identity: Identity) -> dict[str, Any]:
        home = settings.user_home(identity.id)
        link = store.link(identity.id)
        cli_present = any((GeminiCliRuntime.gemini_home(home) / ".gemini" / name).is_file()
                          for name in ("gemini-credentials.json", "oauth_creds.json"))
        owner = identities.get(OWNER_ID)
        note = None
        if owner and identity.id != OWNER_ID and settings.require_google_email_match:
            note = (f"{identity.name} is a synthetic test identity, so no real Google account can be linked to it. Sign "
                    f"out and choose {owner.name} (Owner) to ask questions with your own Gemini account.")
        return {"linked": bool(link) or cli_present, "google_email": link["google_email"] if link else None,
                "link_note": note, "adopts_google_email": identity.id == OWNER_ID,
                "linked_at": link["linked_at"] if link else None, "method": link["method"] if link else
                ("gemini-cli (host sign-in)" if cli_present else None), "cli_credentials_present": cli_present,
                "secret_store": secret_box.kind, "needs_link": runtime.kind != "replay"}

    def systems_for(identity: Identity) -> list[dict[str, Any]]:
        """The systems this person's Wizard can draw on, for the systems stage and the systems picker."""
        return systems.available(settings, services, identity)

    def can_schedule(identity: Identity) -> bool:
        return systems.can_schedule(settings, services, identity)

    def chosen(identity: Identity, ids: list[str] | None) -> SystemChoice | None:
        """The person's systems for a question (None: Auto); a system they cannot choose is a clear refusal."""
        try:
            return systems.choice(settings, services, identity, ids)
        except systems.UnknownSystem as error:
            raise HTTPException(400, str(error)) from None

    def inherited(identity: Identity, parent: dict[str, Any]) -> SystemChoice | None:
        """A Check my data or Make recurring run uses the systems of the answer it follows (those still available)."""
        ids = decode_systems(parent.get("systems"))
        if ids is None:
            return None
        usable = systems.choosable(settings, services, identity)
        kept = [s for s in ids if s in usable]
        return systems.choice(settings, services, identity, kept) if kept else None

    @app.get("/api/v1/bootstrap")
    async def bootstrap(request: Request) -> dict[str, Any]:
        identity: Identity | None = request.state.identity
        base: dict[str, Any] = {"version": __version__, "auth": {"mode": settings.auth_mode, "login_required": identity is None},
                                "suggestions": [] if settings.content_dir or kb else SUGGESTIONS}
        if identity is None:
            return base
        store.touch_user(identity.id, identity.email, identity.name, identity.role)
        readiness = await runtime.readiness(settings.user_home(identity.id), identity.email)
        modes = sorted({s.connector.data_mode for s in services.catalog.systems if identity.can_use_system(s.id)
                        and s.connector.status in ("SYNTHETIC_FIXTURE", "ROWS_VERIFIED")}
                       | ({"LIVE"} if services.postgres and identity.can_use_system("postgresql") else set()))
        return {**base, "diagnostics": settings.diagnostics, "desktop": settings.desktop,
                "settings_editable": identity.id == OWNER_ID and settings_pane.editable(settings),
                "identity": {"id": identity.id, "name": identity.name, "email": identity.email, "role": identity.role},
                "runtime": {"kind": runtime.kind, "label": runtime.label(), "model": runtime.model,
                            "steering": runtime.steering, **readiness},
                "gemini_account": await account_status(identity), "data_modes": modes,
                "attachments": {"from_this_pc": manager.attachments.local_enabled(), "max_mb": settings.max_attachment_mb},
                "systems": systems_for(identity),
                "metronome": {"enabled": can_schedule(identity),
                              "user": settings.metronome.user if settings.metronome else None}}

    # Session (fixture identities only) ---------------------------------------------------------------------------------
    @app.get("/api/v1/session/identities")
    def fixture_identities() -> dict[str, Any]:
        if settings.auth_mode != "fixture":
            raise HTTPException(404, "Not available.")
        return {"identities": [{"id": i.id, "name": i.name, "role": i.role, "email": i.email} for i in identities.all()],
                "notice": "Test identities for development. Real users sign in through corporate SSO."}

    @app.post("/api/v1/session/login")
    def login(body: LoginBody) -> Response:
        if settings.auth_mode != "fixture":
            raise HTTPException(404, "Sign-in is handled by corporate SSO.")
        identity = identities.get(body.user_id)
        if identity is None:
            raise HTTPException(400, "Unknown test identity.")
        response = JSONResponse({"ok": True, "identity": {"id": identity.id, "name": identity.name}})
        start_session(response, identity.id)
        store.audit(identity.id, "session:login")
        return response

    @app.post("/api/v1/session/logout")
    def logout() -> Response:
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    # Conversations -----------------------------------------------------------------------------------------------------
    @app.get("/api/v1/conversations")
    def conversations(request: Request, q: str | None = None) -> dict[str, Any]:
        return {"conversations": store.conversations(me(request).id, (q or "")[:100] or None)}

    @app.post("/api/v1/conversations")
    def new_conversation(request: Request) -> dict[str, Any]:
        return {"conversation_id": store.create_conversation(me(request).id)}

    def run_detail(identity: Identity, run: dict[str, Any]) -> dict[str, Any]:
        shown = TIMELINE_EVENTS | {"diagnostic"} if settings.diagnostics else TIMELINE_EVENTS
        events = [e for e in store.events(run["id"]) if e["type"] in shown]
        visuals = store.visuals(run["conversation_id"], run["id"])
        evidence = [evidence_summary(e) for e in store.evidence(run["conversation_id"]) if e.get("run_id") == run["id"]]
        shown_run = {k: v for k, v in run.items() if k not in ("user_id", "stats")}
        shown_run["stats"] = json.loads(run["stats"]) if run.get("stats") else {}
        shown_run["systems"] = decode_systems(run.get("systems"))
        files = [public(a) for a in store.conversation_attachments(run["conversation_id"]) if a["run_id"] == run["id"]]
        schedules = [public_schedule(s) for s in store.schedules(run["conversation_id"], run["id"])]
        return {**shown_run, "events": events, "visuals": visuals, "evidence": evidence, "attachments": files,
                "schedules": schedules, "active": run["id"] in manager.active}

    @app.get("/api/v1/conversations/{conversation_id}")
    def conversation(request: Request, conversation_id: str) -> dict[str, Any]:
        identity = me(request)
        found = store.conversation(identity.id, conversation_id)
        if not found:
            raise HTTPException(404, "Conversation not found.")
        return {"conversation": found, "runs": [run_detail(identity, r) for r in store.runs(conversation_id)]}

    @app.patch("/api/v1/conversations/{conversation_id}")
    def rename(request: Request, conversation_id: str, body: TitleBody) -> dict[str, Any]:
        if not store.rename_conversation(me(request).id, conversation_id, body.title.strip()):
            raise HTTPException(404, "Conversation not found.")
        return {"ok": True}

    @app.delete("/api/v1/conversations/{conversation_id}")
    def delete_conversation(request: Request, conversation_id: str) -> dict[str, Any]:
        identity = me(request)
        if not store.delete_conversation(identity.id, conversation_id):
            raise HTTPException(404, "Conversation not found.")
        store.audit(identity.id, "conversation:delete", detail={"conversation_id": conversation_id})
        return {"ok": True}

    @app.get("/api/v1/conversations/{conversation_id}/evidence/{evidence_id}")
    def evidence_detail(request: Request, conversation_id: str, evidence_id: str) -> dict[str, Any]:
        identity = me(request)
        if not store.conversation(identity.id, conversation_id):
            raise HTTPException(404, "Evidence not found.")
        found = store.evidence(conversation_id, evidence_id)
        if not found:
            raise HTTPException(404, "Evidence not found.")
        if not entitled_to(identity, found[0]):
            raise HTTPException(403, {"error": "Your access to this source has changed.", "code": "access_changed"})
        return {"evidence": found[0]}

    # Runs --------------------------------------------------------------------------------------------------------------
    @app.post("/api/v1/runs")
    async def start_run(request: Request, body: RunBody) -> dict[str, Any]:
        identity = me(request)
        conversation_id = body.conversation_id
        if conversation_id and not store.conversation(identity.id, conversation_id):
            raise HTTPException(404, "Conversation not found.")
        files = []
        for attachment_id in dict.fromkeys(body.attachment_ids):
            found = store.attachment(identity.id, attachment_id)
            if not found or found["conversation_id"]:
                raise HTTPException(404, "An attached file is no longer available. Attach it again.")
            if found["status"] != "ok":
                raise HTTPException(400, f"{found['filename']} could not be read; remove it before sending.")
            files.append(attachment_id)
        choice = chosen(identity, body.systems)
        if choice is not None and files and "attachment" not in choice.on:  # attaching a file switches Attached files on
            choice = systems.choice(settings, services, identity, [*(body.systems or []), "attachment"])
        conversation_id = conversation_id or store.create_conversation(identity.id)
        try:
            run = manager.start(identity, conversation_id, body.question.strip(), choice=choice)
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        # Bound before the run's task first runs (no await in between), so its prompt lists these files.
        bound = store.bind_attachments(identity.id, files, conversation_id, run["id"]) if files else []
        return {"run_id": run["id"], "conversation_id": conversation_id, "attachments": [public(a) for a in bound]}

    # Attached files ----------------------------------------------------------------------------------------------------
    @app.post("/api/v1/attachments")
    async def upload_attachment(request: Request) -> dict[str, Any]:
        identity = me(request)
        limit = settings.max_attachment_mb * 1024 * 1024
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, f"The file is larger than {settings.max_attachment_mb} MB.")
        data = await request.body()
        try:
            return {"attachment": await manager.attachments.upload(identity, unquote(request.headers.get("X-File-Name", "")), data)}
        except AttachmentError as error:
            raise HTTPException(error.status, error.message) from None

    @app.get("/api/v1/attachments/local")
    def local_files(request: Request, q: str | None = None) -> dict[str, Any]:
        me(request)
        enabled = manager.attachments.local_enabled()
        return {"enabled": enabled, "folders": [str(f) for f in settings.attachment_folders] if enabled else [],
                "files": manager.attachments.local_files((q or "")[:100]) if enabled else []}

    @app.post("/api/v1/attachments/local")
    async def attach_local(request: Request, body: LocalFileBody) -> dict[str, Any]:
        identity = me(request)
        try:
            return {"attachment": await manager.attachments.attach_local(identity, body.path)}
        except AttachmentError as error:
            raise HTTPException(error.status, error.message) from None

    @app.get("/api/v1/attachments/{attachment_id}/file")
    def attachment_file(request: Request, attachment_id: str) -> Response:
        """Download a file Wizard keeps: an edited copy (or an uploaded original). Only its owner can. The whole file is
        read before the answer starts, so a file that cannot be read is an error, never a download cut short."""
        identity = me(request)
        row = store.attachment(identity.id, attachment_id)
        path = manager.attachments.original(row) if row and row.get("origin") != "local" else None
        if row is None or path is None or not path.is_file():
            raise HTTPException(404, "That file is not available.")
        try:
            data = path.read_bytes()
        except OSError as error:
            raise HTTPException(409, f"{row['filename']} could not be read: {error.strerror or error}.") from None
        store.audit(identity.id, "attachment:download", detail={"attachment_id": attachment_id})
        return Response(data, media_type=DOWNLOAD_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(row['filename'])}"})

    @app.post("/api/v1/attachments/{attachment_id}/save")
    def save_attachment(request: Request, attachment_id: str) -> dict[str, Any]:
        """Download where Wizard runs on the person's own PC: Wizard saves the file in their Downloads folder itself
        (Excel writes it when Office runs here). Elsewhere the page downloads it through the browser."""
        identity = me(request)
        if not on_this_pc(request):
            raise HTTPException(409, {"error": "Wizard saves files only on your own PC.", "code": "not_on_this_pc"})
        try:
            return {"saved": manager.attachments.save_to_downloads(identity, attachment_id)}
        except AttachmentError as error:
            raise HTTPException(error.status, error.message) from None

    @app.post("/api/v1/attachments/{attachment_id}/open")
    def open_attachment(request: Request, attachment_id: str) -> dict[str, Any]:
        """Open the copy Wizard saved in Downloads (Excel), on the person's click."""
        identity = me(request)
        if not on_this_pc(request):
            raise HTTPException(409, {"error": "Wizard opens files only on your own PC.", "code": "not_on_this_pc"})
        try:
            manager.attachments.open_saved(identity, attachment_id)
        except AttachmentError as error:
            raise HTTPException(error.status, error.message) from None
        return {"ok": True}

    @app.delete("/api/v1/attachments/{attachment_id}")
    def remove_attachment(request: Request, attachment_id: str) -> dict[str, Any]:
        if not manager.attachments.remove(me(request), attachment_id):
            raise HTTPException(404, "File not found, or already sent with a question.")
        return {"ok": True}

    @app.post("/api/v1/runs/{run_id}/check")
    async def check_run(request: Request, run_id: str) -> dict[str, Any]:
        identity = me(request)
        parent = store.run(identity.id, run_id)
        if not parent or parent["status"] != "succeeded":
            raise HTTPException(404, "Only a finished answer can be checked.")
        try:
            run = manager.start(identity, parent["conversation_id"], "Check my data", kind="check", parent_run_id=run_id,
                                choice=inherited(identity, parent))
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        return {"run_id": run["id"], "conversation_id": parent["conversation_id"]}

    @app.post("/api/v1/runs/{run_id}/recurring")
    async def make_recurring(request: Request, run_id: str, body: RecurringBody) -> dict[str, Any]:
        """Make recurring under an answer: a follow-up in which Gemini proposes the schedule, asking how often only when
        the person did not pick it from the menu."""
        identity = me(request)
        parent = store.run(identity.id, run_id)
        if not parent or parent["status"] != "succeeded":
            raise HTTPException(404, "Only a finished answer can be made recurring.")
        if not can_schedule(identity):
            raise HTTPException(409, "Recurring extractions are not available: Wizard is not connected to Metronome, or "
                                     "you cannot query the company database.")
        try:
            run = manager.start(identity, parent["conversation_id"], recurring_question(body.cadence), kind="recurring",
                                parent_run_id=run_id, choice=inherited(identity, parent))
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        return {"run_id": run["id"], "conversation_id": parent["conversation_id"], "question": run["question"]}

    @app.post("/api/v1/schedules/{schedule_id}/create")
    async def create_schedule(request: Request, schedule_id: str) -> dict[str, Any]:
        """The person's confirmation: the only path from Wizard to Metronome. The Flow belongs to Metronome's Wizard
        user. A proposal moves to `creating` before anything is sent, so a second click never creates a second Flow."""
        identity = me(request)
        schedule = store.schedule(identity.id, schedule_id)
        if not schedule:
            raise HTTPException(404, "Recurring extraction not found.")
        if schedule["status"] == "created":
            return {"schedule": public_schedule(schedule)}
        if not settings.metronome or not can_schedule(identity):
            raise HTTPException(409, "Wizard is not connected to Metronome, or you can no longer query the company database.")
        if not store.move_schedule(schedule_id, "creating", ("proposed", "failed")):
            raise HTTPException(409, "This recurring extraction is already being created, or its outcome is uncertain: "
                                     "look for it in Metronome's Flows.")
        client = MetronomeClient(settings.metronome, metronome_transport)
        try:
            flow = await asyncio.to_thread(client.create, schedule)
        except Exception as error:  # noqa: BLE001 - a proposal never stays `creating`; an unknown failure may have created it
            if isinstance(error, MetronomeError):
                status, message = ("uncertain" if error.uncertain else "failed"), error.message
            else:
                log.exception("creating recurring extraction %s in Metronome failed", schedule_id)
                status, message = "uncertain", (f"Wizard hit an unexpected error while creating the Flow "
                                                f"({type(error).__name__}). It may have been created: look for it in "
                                                "Metronome's Flows before asking again.")
            store.move_schedule(schedule_id, status, ("creating",), error=message)
            store.audit(identity.id, "metronome:create_flow", run_id=schedule["run_id"], system="metronome", outcome=status,
                        detail={"schedule": schedule["label"]})
        else:
            store.move_schedule(schedule_id, "created", ("creating",), flow=flow)
            store.audit(identity.id, "metronome:create_flow", run_id=schedule["run_id"], system="metronome",
                        detail={"schedule": schedule["label"], "flow_id": flow.get("id"),
                                "recipients": len(schedule["recipients"]), "frequency": schedule["frequency"]})
        return {"schedule": public_schedule(store.schedule(identity.id, schedule_id) or schedule)}

    @app.post("/api/v1/schedules/{schedule_id}/dismiss")
    def dismiss_schedule(request: Request, schedule_id: str) -> dict[str, Any]:
        identity = me(request)
        if not store.schedule(identity.id, schedule_id):
            raise HTTPException(404, "Recurring extraction not found.")
        if not store.move_schedule(schedule_id, "dismissed", ("proposed", "failed")):
            raise HTTPException(409, "Only a recurring extraction that was not created can be dismissed.")
        return {"schedule": public_schedule(store.schedule(identity.id, schedule_id) or {})}

    @app.get("/api/v1/schedules/{schedule_id}/preview")
    def schedule_preview(request: Request, schedule_id: str) -> dict[str, Any]:
        """The email as it looked on the brief's test run, for the card and the Recurring tab."""
        identity = me(request)
        schedule = store.owned_schedule(identity.id, schedule_id)
        if not schedule:
            raise HTTPException(404, "Recurring brief not found.")
        return {"html": metronome.preview_html(schedule)}

    @app.get("/api/v1/recurring")
    async def recurring(request: Request) -> dict[str, Any]:
        """The Recurring tab: the person's briefs in Metronome, each with Metronome's own state (on or off, next and
        last runs). When Metronome cannot be reached the list still shows, with what Wizard last knew."""
        identity = me(request)
        found = store.recurring(identity.id)
        ids = [int(s["flow"]["id"]) for s in found if s.get("flow") and s["flow"].get("id") is not None]
        live: dict[int, dict[str, Any]] = {}
        sync: dict[str, Any] = {"ok": True, "message": None}
        if not settings.metronome:
            sync = {"ok": False, "message": "This Wizard is not connected to Metronome."}
        elif ids:
            try:
                live = await asyncio.to_thread(MetronomeClient(settings.metronome, metronome_transport).status, ids)
            except MetronomeError as error:
                sync = {"ok": False, "message": error.message}
        items = []
        for schedule in found:
            flow_id = (schedule.get("flow") or {}).get("id")
            items.append({**public_schedule(schedule), "metronome": live.get(int(flow_id)) if flow_id is not None else None})
        return {"items": items, "sync": sync}

    @app.post("/api/v1/recurring/{schedule_id}/delete")
    async def delete_recurring(request: Request, schedule_id: str) -> dict[str, Any]:
        """Delete a brief: Metronome turns its Flow off and keeps it with its run history (owner, 23 October 2026). Only
        the Wizard user that owns the Flow, or Metronome's host PC, can delete a Flow there."""
        identity = me(request)
        schedule = store.owned_schedule(identity.id, schedule_id)
        if not schedule or schedule["status"] not in ("created", "deleting"):
            raise HTTPException(404, "Recurring brief not found.")
        if not settings.metronome:
            raise HTTPException(409, "Wizard is not connected to Metronome, so it cannot turn the Flow off.")
        if not store.move_schedule(schedule_id, "deleting", ("created",)):
            raise HTTPException(409, "This brief is already being deleted.")
        flow_id = (schedule.get("flow") or {}).get("id")
        try:
            if flow_id is None:
                raise MetronomeError("Wizard does not know this brief's Flow in Metronome; turn it off in Metronome's "
                                     "Flows.")
            outcome = await asyncio.to_thread(MetronomeClient(settings.metronome, metronome_transport).deactivate,
                                              int(flow_id))
        except MetronomeError as error:
            store.move_schedule(schedule_id, "created", ("deleting",), error=error.message)
            store.audit(identity.id, "metronome:deactivate_flow", run_id=schedule["run_id"], system="metronome",
                        outcome="failed", detail={"schedule": schedule["label"], "flow_id": flow_id})
            raise HTTPException(502, error.message) from None
        flow = {**(schedule.get("flow") or {}), "enabled": False}
        store.move_schedule(schedule_id, "deleted", ("deleting",), flow=flow)
        store.audit(identity.id, "metronome:deactivate_flow", run_id=schedule["run_id"], system="metronome",
                    detail={"schedule": schedule["label"], "flow_id": flow_id, "missing": outcome.get("missing")})
        return {"deleted": True, "flow_id": flow_id, "missing": bool(outcome.get("missing"))}

    @app.get("/api/v1/runs/{run_id}")
    def get_run(request: Request, run_id: str) -> dict[str, Any]:
        identity = me(request)
        run = store.run(identity.id, run_id)
        if not run:
            raise HTTPException(404, "Run not found.")
        return run_detail(identity, run)

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel(request: Request, run_id: str) -> dict[str, Any]:
        return {"cancelled": manager.cancel(me(request).id, run_id)}

    @app.post("/api/v1/runs/{run_id}/steer")
    async def steer(request: Request, run_id: str, body: SteerBody) -> dict[str, Any]:
        """A note to Wizard about a run: free words, or Not this on one of its steps. While the run works on a connection
        that takes notes, Gemini reads it before its next step. Otherwise (a connection that cannot, or an answer already
        finished) it becomes the next question, with the run's steps in its context; a running one is stopped first."""
        identity = me(request)
        run = store.run(identity.id, run_id)
        if not run:
            raise HTTPException(404, "Run not found.")
        text = body.text.strip()
        if not text and not body.call_id:
            raise HTTPException(400, "Write a note for Wizard.")
        about = step_about(store.events(run_id), body.call_id) if body.call_id else None
        if body.call_id and about is None:
            raise HTTPException(404, "That step is not part of this answer.")
        active = run_id in manager.active
        if active and runtime.steering:
            steer = manager.steer(identity.id, run_id, text, body.call_id, body.reason)
            if steer is not None:
                return {"steer": steer}
        if active:
            manager.cancel(identity.id, run_id)
            await manager.finished(run_id)
        question = correction_question(text, about, body.reason)[:4000]
        try:  # the systems as they are now: the picker may have changed while the run worked
            follow = manager.start(identity, run["conversation_id"], question,
                                   choice=inherited(identity, store.run(identity.id, run_id) or run))
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        return {"follow_up": {"run_id": follow["id"], "conversation_id": run["conversation_id"], "question": question,
                              "systems": decode_systems(follow.get("systems"))}}

    @app.post("/api/v1/runs/{run_id}/systems")
    def change_systems(request: Request, run_id: str, body: SystemsBody) -> dict[str, Any]:
        """The systems picker changed while this run works."""
        identity = me(request)
        if not manager.change_systems(identity.id, run_id, chosen(identity, body.systems)):
            raise HTTPException(409, "This answer is no longer running.")
        return {"systems": body.systems}

    # Notes the person asked Wizard to remember ---------------------------------------------------------------------------
    @app.get("/api/v1/memories")
    def memories(request: Request) -> dict[str, Any]:
        return {"memories": [public_memory(m) for m in store.memories(me(request).id)]}

    @app.post("/api/v1/memories")
    def remember(request: Request, body: MemoryBody) -> dict[str, Any]:
        identity = me(request)
        if body.run_id and not store.run(identity.id, body.run_id):
            raise HTTPException(404, "Run not found.")
        try:
            memory = store.add_memory(identity.id, " ".join(body.text.split()), body.run_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        store.audit(identity.id, "memory:add", run_id=body.run_id)
        return {"memory": public_memory(memory)}

    @app.patch("/api/v1/memories/{memory_id}")
    def edit_memory(request: Request, memory_id: str, body: MemoryBody) -> dict[str, Any]:
        if not store.update_memory(me(request).id, memory_id, " ".join(body.text.split())):
            raise HTTPException(404, "Note not found.")
        return {"ok": True}

    @app.delete("/api/v1/memories/{memory_id}")
    def forget(request: Request, memory_id: str) -> dict[str, Any]:
        identity = me(request)
        if not store.delete_memory(identity.id, memory_id):
            raise HTTPException(404, "Note not found.")
        store.audit(identity.id, "memory:delete")
        return {"ok": True}

    @app.post("/api/v1/runs/{run_id}/feedback")
    def feedback(request: Request, run_id: str, body: FeedbackBody) -> dict[str, Any]:
        identity = me(request)
        if not store.run(identity.id, run_id):
            raise HTTPException(404, "Run not found.")
        store.add_feedback(run_id, identity.id, body.category, body.note)
        return {"ok": True}

    @app.post("/api/v1/runs/{run_id}/email")
    async def email_draft(request: Request, run_id: str, body: EmailDraftBody) -> dict[str, Any]:
        """Open the answer as an unsent Outlook message. Only where the browser and Wizard share a PC: behind a proxy,
        Outlook would open on the server, so the page downloads the message as a file instead."""
        identity = me(request)
        run = store.run(identity.id, run_id)
        if not run or run["status"] != "succeeded":
            raise HTTPException(404, "Only a finished answer can be emailed.")
        if not on_this_pc(request):
            raise HTTPException(409, {"error": "Outlook opens only when Wizard runs on your own PC.", "code": "outlook_not_local"})
        try:
            await open_outlook_draft(settings.data_dir / "drafts", body.subject, body.html)
        except DraftError as error:
            raise HTTPException(503, {"error": str(error), "code": "outlook_unavailable"}) from None
        store.audit(identity.id, "email:draft", run_id=run_id)
        return {"ok": True}

    @app.get("/api/v1/runs/{run_id}/events")
    async def run_events(request: Request, run_id: str, after: int = 0) -> StreamingResponse:
        identity = me(request)
        run = store.run(identity.id, run_id)
        if not run:
            raise HTTPException(404, "Run not found.")
        last_event_id = request.headers.get("last-event-id", "")
        start = max(after, int(last_event_id)) if last_event_id.isdigit() else after

        async def stream() -> AsyncIterator[str]:
            queue = manager.subscribe(run_id)
            last = start
            try:
                for event in store.events(run_id, start):
                    last = event["seq"]
                    yield _sse(event)
                    if event["type"] in TERMINAL:
                        return
                if queue is None:
                    current = store.run(identity.id, run_id) or {}
                    if current.get("status") in ("failed", "cancelled"):
                        yield _sse({"seq": last + 1, "type": "run_failed", "ts": current.get("finished_at"),
                                    "payload": {"code": current.get("error_code"), "message": current.get("error_message")}})
                    return
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if event["seq"] <= last:
                        continue
                    last = event["seq"]
                    yield _sse(event)
                    if event["type"] in TERMINAL:
                        return
            finally:
                if queue is not None:
                    manager.unsubscribe(run_id, queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # Reports -----------------------------------------------------------------------------------------------------------
    @app.get("/api/v1/reports")
    def reports(request: Request) -> dict[str, Any]:
        return {"reports": store.reports(me(request).id)}

    @app.get("/api/v1/reports/{report_id}")
    def report(request: Request, report_id: str) -> dict[str, Any]:
        identity = me(request)
        found = store.report(report_id)
        if found and found.get("expired"):
            raise HTTPException(410, "This report has passed its retention period and was removed.")
        if not found or found.get("user_id") != identity.id:
            store.audit(identity.id, "report:open", report_id=report_id, outcome="not_found")
            raise HTTPException(404, "Report not found.")
        if not all(entitled_to(identity, e) for e in found.get("evidence", [])):
            store.audit(identity.id, "report:open", report_id=report_id, outcome="access_changed")
            raise HTTPException(403, {"error": "Your access to one or more sources in this report has changed, so it "
                                               "cannot be reopened.", "code": "access_changed"})
        store.audit(identity.id, "report:open", report_id=report_id)
        return {"report": {k: v for k, v in found.items() if k != "user_id"}}

    # Sources -----------------------------------------------------------------------------------------------------------
    @app.get("/api/v1/sources")
    def sources(request: Request) -> dict[str, Any]:
        identity = me(request)
        out = []
        for system in services.catalog.systems:
            if not identity.can_use_system(system.id):
                continue
            visible = [r for _, r in services.catalog.reports(system.id) if identity.can_see_report(system.id, r.id)]
            markets = identity.allowed_markets(system.id)
            out.append({"id": system.id, "name": system.name, "description": system.description, "families": system.families,
                        "connector_status": system.connector.status, "data_mode": system.connector.data_mode,
                        "live_interface": system.connector.live_interface, "owner": system.owner,
                        "reports": len(visible), "reports_with_rows": sum(1 for r in visible if r.row_access == "ROWS"),
                        "markets": "all" if markets is None else sorted(markets)})
        return {"sources": out}

    @app.get("/api/v1/sources/{system_id}/catalog")
    def source_catalog(request: Request, system_id: str) -> dict[str, Any]:
        identity = me(request)
        contract = services.catalog.contracts.get(system_id)
        if not contract or not identity.can_use_system(system_id):
            raise HTTPException(404, "Source not found.")
        visible = [r for r in contract.reports if identity.can_see_report(system_id, r.id)]
        needed = set()
        for report in visible:
            folder = report.folder
            while folder:
                needed.add(folder)
                folder = next((f.parent for f in contract.folders if f.id == folder), None)  # type: ignore[assignment]
        return {"system": {"id": system_id, "name": contract.system.name, "connector_status": contract.system.connector.status,
                           "data_mode": contract.system.connector.data_mode, "open_url_template": contract.system.open_url_template},
                "folders": [f.model_dump() for f in contract.folders if f.id in needed],
                "reports": [{"id": r.id, "name": r.name, "folder": r.folder, "type": r.type, "row_access": r.row_access,
                             "description": r.description, "as_of": r.as_of, "refresh": r.refresh,
                             "prompts": [p.model_dump() for p in r.prompts], "measures": [m.label for m in r.measures],
                             "sensitivity": r.sensitivity,
                             "status": "NAVIGATION_ONLY" if r.row_access == "NAVIGATION_ONLY" else
                             ("ROWS_VERIFIED" if contract.system.connector.status == "ROWS_VERIFIED" else contract.system.connector.status)}
                            for r in visible]}

    # Brain page (/brain) ---------------------------------------------------------------------------------------------------
    # What Wizard can draw on, for showing it to people: read from the knowledge base, the catalogs and the database,
    # within this person's rights. Read-only, and never a Gemini tool (brain.py).
    live_cache = brain.LiveCache()

    @app.get("/api/v1/brain")
    def brain_map(request: Request) -> dict[str, Any]:
        identity = me(request)
        reports = {s.id: sum(1 for _, r in services.catalog.reports(s.id) if identity.can_see_report(s.id, r.id))
                   for s in services.catalog.systems if identity.can_use_system(s.id)}
        content = "company" if loaded_content else "none" if kb else "examples"
        synced = knowledge_status().get("synced_at")  # never the repository: people do not see it
        return {**brain.knowledge_map(services.knowledge, systems_for(identity), reports, content),
                "knowledge_synced_at": synced, "pg_name": services.postgres_name}

    @app.get("/api/v1/brain/live")
    def brain_live(request: Request) -> dict[str, Any]:
        identity = me(request)
        allowed = identity.can_use_system("postgresql") and identity.allowed_markets("postgresql") is None
        return brain.live(services.postgres, allowed, live_cache, settings.news_table, settings.news_database,
                          services.postgres_name)

    # Dev diagnostics -----------------------------------------------------------------------------------------------------
    @app.get("/api/v1/dev/log")
    async def dev_log(request: Request) -> dict[str, Any]:
        me(request)
        if not settings.diagnostics:
            raise HTTPException(404, "Diagnostics are off (WIZARD_DIAGNOSTICS=false).")
        return {"lines": list(LOG_BUFFER.lines)}

    # Gemini account ----------------------------------------------------------------------------------------------------
    @app.get("/api/v1/account/gemini")
    async def gemini_account(request: Request) -> dict[str, Any]:
        return await account_status(me(request))

    @app.post("/api/v1/account/gemini/link")
    def gemini_link(request: Request) -> dict[str, Any]:
        identity = me(request)
        url, state, verifier = google_oauth.start_link()
        store.put_pending(state, identity.id, verifier, time.time())
        return {"authorize_url": url, "state": state, "redirect_uri": google_oauth.USER_CODE_REDIRECT,
                "instructions": "Sign in with your own enterprise Google account. Google then shows an authorization "
                                "code; paste it here. Wizard never sees your password."}

    @app.post("/api/v1/account/gemini/link/complete")
    async def gemini_link_complete(request: Request, body: LinkCompleteBody) -> dict[str, Any]:
        identity = me(request)
        verifier = store.take_pending(body.state, identity.id, time.time() - 600)
        if not verifier:
            raise HTTPException(400, "This sign-in attempt expired. Start the link again.")
        # The first proxy lookup may evaluate a Windows PAC script (a PowerShell call): keep it off the event loop.
        http = (httpx.AsyncClient(timeout=30, transport=google_transport) if google_transport
                else await asyncio.to_thread(outbound.client, google_oauth.TOKEN_ENDPOINT, override=settings.proxy))
        async with http:
            try:
                tokens = await google_oauth.exchange_code(http, body.code, verifier)
                info = await google_oauth.userinfo(http, tokens.access_token)
            except google_oauth.OAuthError as error:
                store.audit(identity.id, "gemini:link", outcome=error.code)
                raise HTTPException(400, error.message) from None
            except httpx.HTTPError as error:
                message = outbound.explain(error, google_oauth.TOKEN_ENDPOINT, settings.proxy)
                log.warning("gemini link: %s", message)
                store.audit(identity.id, "gemini:link", outcome="network_error")
                raise HTTPException(502, message) from None
        if not info["email"]:
            store.audit(identity.id, "gemini:link", outcome="no_email")
            raise HTTPException(400, "Google did not say which account signed in. Start the link again.")
        domain = info["email"].rsplit("@", 1)[-1].lower()
        if settings.google_domains and domain not in settings.google_domains:
            store.audit(identity.id, "gemini:link", outcome="domain_not_allowed")
            raise HTTPException(403, f"{info['email']} is not a company account. Sign in with your work Google account "
                                     f"({', '.join('@' + d for d in settings.google_domains)}).")
        if identity.id == OWNER_ID:
            if info["email"].lower() != identity.email.lower():
                identity = identity.model_copy(update={"email": info["email"].lower()})
                identities.replace(identity)
        elif settings.require_google_email_match and info["email"].lower() != identity.email.lower():
            store.audit(identity.id, "gemini:link", outcome="email_mismatch")
            owner = identities.get(OWNER_ID)
            hint = (f" {identity.name} is a synthetic test identity: sign out and choose {owner.name} (Owner) instead."
                    if owner else "")
            raise HTTPException(403, f"This Google account ({info['email']}) is not {identity.name}'s ({identity.email}). "
                                     "Wizard does not run questions under another person's Gemini entitlement." + hint)
        home = settings.user_home(identity.id)
        secret_box.write(CodeAssistRuntime.token_path(home), tokens.refresh_token)
        google_oauth.write_cli_credentials(GeminiCliRuntime.gemini_home(home), tokens)
        store.save_link(identity.id, info["email"], settings.google_cloud_project, "user-code")
        store.audit(identity.id, "gemini:link")
        return await account_status(identity)

    # The person's own Gemini quota (Gemini CLI's retrieveUserQuota), under their own sign-in and project.
    quota_client = runtime if isinstance(runtime, CodeAssistRuntime) else CodeAssistRuntime(
        settings.model, secret_box, gemini_project(settings), settings.thinking, proxy=settings.proxy,
        transport=google_transport)
    quota_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @app.get("/api/v1/account/gemini/quota")
    async def gemini_quota(request: Request, refresh: bool = False) -> dict[str, Any]:
        identity = me(request)
        if runtime.kind == "replay":
            return {"available": False, "reason": "Replay mode does not use Gemini."}
        cached = quota_cache.get(identity.id)
        if cached and not refresh and time.time() - cached[0] < 60:
            return cached[1]
        try:
            raw = await quota_client.quota(settings.user_home(identity.id), identity.id)
            result: dict[str, Any] = {"available": True, **summarize_quota(raw, settings.model),
                                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        except AgentFailure as failure:
            result = {"available": False, "code": failure.code, "reason": failure.message}
            log.warning("gemini quota for %s: %s %s", identity.id, failure.code, failure.message)
        quota_cache[identity.id] = (time.time(), result)
        return result

    @app.delete("/api/v1/account/gemini")
    async def gemini_unlink(request: Request) -> dict[str, Any]:
        identity = me(request)
        home = settings.user_home(identity.id)
        secret_box.delete(CodeAssistRuntime.token_path(home))
        google_oauth.clear_cli_credentials(GeminiCliRuntime.gemini_home(home))
        store.delete_link(identity.id)
        store.audit(identity.id, "gemini:unlink")
        return await account_status(identity)

    # Company portals in the person's own Wizard browser ----------------------------------------------------------------
    def portal_browser(request: Request) -> tuple[Identity, PortalBrowser]:
        identity = me(request)
        if services.portals is None or not any(identity.can_use_system(p) for p in portal_ids):
            raise HTTPException(404, "No company portals are configured on this Wizard (Settings → Portals).")
        return identity, services.portals.for_user(identity.id)

    async def portal_action(request: Request, action: str) -> dict[str, Any]:
        identity, browser = portal_browser(request)
        try:
            result = await asyncio.to_thread(getattr(browser, action))
        except PortalError as error:
            raise HTTPException(409, error.message) from None
        if action != "status":
            store.audit(identity.id, f"portals:{action}")
        return result

    @app.get("/api/v1/portals")
    async def portals_status(request: Request) -> dict[str, Any]:
        status = await portal_action(request, "status")
        identity = me(request)
        if services.portal_maps is not None:
            status["maps"] = {p["id"]: services.portal_maps.status(p["id"]) for p in status.get("portals", [])}
            exploration = manager.explorations.get(identity.id)
            status["mapping"] = exploration.public() if exploration else None
        return status

    # Portal maps: Gemini explores a portal in rounds and keeps what it learns (owner, 30 Oct 2026) --------------------
    def map_portal(request: Request, system: str) -> tuple[Identity, Any]:
        identity, browser = portal_browser(request)
        portal = browser.settings.portal(system)
        if portal is None or services.portal_maps is None or not identity.can_use_system(system):
            raise HTTPException(404, f"'{system}' is not a portal configured here (Settings → Portals).")
        return identity, portal

    def map_view(identity: Identity, system: str) -> dict[str, Any]:
        assert services.portal_maps is not None
        exploration = manager.explorations.get(identity.id)
        return {"map": services.portal_maps.status(system),
                "mapping": exploration.public() if exploration and exploration.system == system else None}

    @app.get("/api/v1/portals/{system}/map")
    async def portal_map_status(request: Request, system: str) -> dict[str, Any]:
        identity, portal = map_portal(request, system)
        assert services.portal_maps is not None
        return {**map_view(identity, portal.id), "summary": services.portal_maps.summary(portal.id)}

    @app.post("/api/v1/portals/{system}/map")
    async def start_mapping(request: Request, system: str) -> dict[str, Any]:
        """Gemini explores the portal in rounds, in a conversation of its own, and keeps what it learns in the map."""
        identity, portal = map_portal(request, system)
        try:
            manager.start_exploration(identity, portal.id, portal.name)
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        store.audit(identity.id, "portals:map", system=portal.id)
        return map_view(identity, portal.id)

    @app.post("/api/v1/portals/{system}/map/stop")
    async def stop_mapping(request: Request, system: str) -> dict[str, Any]:
        identity, portal = map_portal(request, system)
        manager.stop_exploration(identity.id)
        return map_view(identity, portal.id)

    @app.post("/api/v1/portals/{system}/map/publish")
    async def publish_map(request: Request, system: str) -> dict[str, Any]:
        identity, portal = map_portal(request, system)
        assert services.portal_maps is not None
        result = await asyncio.to_thread(services.portal_maps.publish, portal.id)
        if result.outcome in ("failed", "not_configured"):
            raise HTTPException(409, result.message)
        store.audit(identity.id, "portals:map_publish", system=portal.id)
        return {**map_view(identity, portal.id), "message": result.message}

    @app.delete("/api/v1/portals/{system}/map")
    async def forget_map(request: Request, system: str) -> dict[str, Any]:
        """The person starts the map again: this PC's copy is deleted (a published copy stays in the knowledge base)."""
        identity, portal = map_portal(request, system)
        exploration = manager.explorations.get(identity.id)
        if exploration and exploration.state == "running" and exploration.system == portal.id:
            raise HTTPException(409, "Stop the mapping first.")
        assert services.portal_maps is not None
        services.portal_maps.forget(portal.id)
        store.audit(identity.id, "portals:map_forget", system=portal.id)
        return map_view(identity, portal.id)

    @app.post("/api/v1/portals/sign-in")
    async def portals_sign_in(request: Request) -> dict[str, Any]:
        """Opens a visible window of Wizard's browser on this PC, one tab per portal, for the person to sign in."""
        return await portal_action(request, "begin_sign_in")

    @app.post("/api/v1/portals/sign-in/done")
    async def portals_signed_in(request: Request) -> dict[str, Any]:
        return await portal_action(request, "finish_sign_in")

    @app.post("/api/v1/portals/check")
    async def portals_check(request: Request) -> dict[str, Any]:
        return await portal_action(request, "check")

    def request_portal(request: Request, system: str) -> tuple[Identity, PortalBrowser, Any]:
        identity, browser = portal_browser(request)
        portal = browser.settings.portal(system)
        if portal is None or portal.id not in access_requests.REQUEST_PORTALS or not identity.can_use_system(system):
            raise HTTPException(404, "Access requests are made in the Big Data Portal's information catalog; it is not "
                                     "configured here (Settings → Portals).")
        return identity, browser, portal

    @app.get("/api/v1/portals/{system}/access-form")
    async def access_form(request: Request, system: str) -> dict[str, Any]:
        """The answers this person gives on every access request, kept on this PC."""
        _, browser, portal = request_portal(request, system)
        return access_requests.form(browser.root, portal)

    @app.post("/api/v1/portals/{system}/access-form")
    async def save_access_form(request: Request, system: str, body: AccessFormBody) -> dict[str, Any]:
        identity, browser, portal = request_portal(request, system)
        try:
            saved = access_requests.save(browser.root, portal, body.page, [f.model_dump() for f in body.fields])
        except access_requests.AccessFormError as error:
            raise HTTPException(400, str(error)) from None
        store.audit(identity.id, "portals:access_form", system=portal.id)
        return saved

    @app.post("/api/v1/portals/{system}/access-request")
    async def open_access_request(request: Request, system: str, body: AccessRequestBody) -> dict[str, Any]:
        """Opens the request page in a visible window of Wizard's browser on this PC and fills the saved answers and
        this request's into the form's empty fields. The person checks them and submits; Wizard never submits."""
        identity, browser, portal = request_portal(request, system)
        saved = access_requests.form(browser.root, portal)
        try:
            address = access_requests.check_address(portal, body.address or saved["page"] or saved["default_page"])
            extra = access_requests.clean_fields([a.model_dump() for a in body.answers])
        except access_requests.AccessFormError as error:
            raise HTTPException(400, str(error)) from None
        tables = [" ".join(t.split())[:200] for t in body.tables if t.strip()]
        answers = access_requests.answers(saved["fields"], extra, tables)
        try:
            status = await asyncio.to_thread(browser.open_access_request, portal, address, answers)
        except PortalError as error:
            raise HTTPException(409, error.message) from None
        store.audit(identity.id, "portals:access_request", system=portal.id, detail={"tables": tables})
        return status

    # Settings pane, model picker and updates (a person's own install only) ----------------------------------------------
    def settings_owner(request: Request) -> Identity:
        identity = me(request)
        if identity.id != OWNER_ID or not settings_pane.editable(settings):
            raise HTTPException(404, "Settings are changed on the PC where Wizard is installed, by the person who uses it.")
        return identity

    def settings_view() -> dict[str, Any]:
        return {**settings_pane.describe(settings), "model": runtime.model, "runtime": runtime.kind,
                "desktop": settings.desktop, "build": settings_pane.installed_build(), "version": __version__}

    def schedule_restart() -> str:
        request_restart = getattr(app.state, "request_restart", None)
        if request_restart is None:
            return "manual"

        async def when_idle() -> None:
            await asyncio.sleep(1.0)  # let the response reach the page first
            while manager.active:
                await asyncio.sleep(3)
            log.info("restarting to apply new settings")
            request_restart()

        app.state.pending_restart = asyncio.get_running_loop().create_task(when_idle())
        return "after_run" if manager.active else "now"

    @app.get("/api/v1/settings")
    def get_settings(request: Request) -> dict[str, Any]:
        settings_owner(request)
        return settings_view()

    @app.put("/api/v1/settings")
    async def put_settings(request: Request, body: SettingsBody) -> dict[str, Any]:
        identity = settings_owner(request)
        try:
            result = await asyncio.to_thread(settings_pane.save, settings, dict(body.values))
        except settings_pane.PaneError as error:
            store.audit(identity.id, "settings:update", outcome="refused", detail={"keys": sorted(body.values)})
            raise HTTPException(error.status, str(error)) from None
        changed = result["changed"]
        store.audit(identity.id, "settings:update", detail={"keys": changed})
        return {**settings_view(), "changed": changed, "apply": schedule_restart() if changed else "none"}

    @app.post("/api/v1/settings/test")
    async def test_settings(request: Request, body: SettingsTestBody) -> dict[str, Any]:
        settings_owner(request)
        try:
            if body.section == "postgres":
                return await asyncio.to_thread(settings_pane.test_postgres, settings, dict(body.values))
            if body.section == "metronome":
                return await asyncio.to_thread(settings_pane.test_metronome, settings, dict(body.values),
                                               metronome_transport)
            return await asyncio.to_thread(settings_pane.test_knowledge, settings, dict(body.values))
        except settings_pane.PaneError as error:
            return {"ok": False, "message": str(error)}

    update_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @app.get("/api/v1/updates")
    async def updates(request: Request, refresh: bool = False) -> dict[str, Any]:
        settings_owner(request)
        cached = update_cache.get("latest")
        if cached and not refresh and time.time() - cached[0] < 300:
            return cached[1]
        result = await asyncio.to_thread(settings_pane.check_update, settings)
        update_cache["latest"] = (time.time(), result)
        return result

    # Internal tool API for MCP shims -------------------------------------------------------------------------------------
    def internal_run(request: Request) -> Any:
        if not _is_loopback(request.client.host if request.client else None):
            raise HTTPException(403, "Internal API is loopback only.")
        header = request.headers.get("authorization", "")
        claims = verify(settings.session_secret, "run", header[7:] if header.lower().startswith("bearer ") else None)
        if not claims:
            raise HTTPException(401, "Invalid run token.")
        run = manager.active.get(str(claims["r"]))
        if run is None or run.identity.id != claims["u"]:
            raise HTTPException(409, "Run is not active.")
        return run

    @app.get("/internal/v1/tools")
    def internal_tools(request: Request, scope: str | None = None) -> dict[str, Any]:
        return {"tools": manager.describe(internal_run(request), scope)}

    @app.post("/internal/v1/tools/{name}")
    async def internal_call(request: Request, name: str, body: InternalCall) -> dict[str, Any]:
        run = internal_run(request)
        spec = registry.specs.get(name)
        if spec and body.scope and spec.scope != body.scope:
            return {"ok": False, "text": json.dumps({"error": {"code": "wrong_server", "message": f"{name} is not served here."}})}
        outcome = await manager.execute_tool(run.id, name, body.arguments)
        return {"ok": outcome.ok, "text": outcome.as_text()}

    # Desktop control API for WizardBar ----------------------------------------------------------------------------------
    def desktop_control(request: Request) -> None:
        if not settings.control_token:
            raise HTTPException(404, "Not available.")
        if not _is_loopback(request.client.host if request.client else None):
            raise HTTPException(403, "Desktop control is loopback only.")
        if not hmac.compare_digest(request.headers.get("x-wizard-control", ""), settings.control_token):
            raise HTTPException(401, "Invalid control token.")

    @app.get("/internal/v1/desktop/status")
    def desktop_status(request: Request) -> dict[str, Any]:
        desktop_control(request)
        return {"version": __version__, "runtime": runtime.kind, "active_runs": len(manager.active),
                "knowledge_base": knowledge_status(), "provision": settings.provision,
                "postgres": bool(services.postgres), "content": "knowledge base" if kb else
                ("folder" if settings.content_dir else "synthetic")}

    @app.post("/internal/v1/desktop/sync")
    async def desktop_sync(request: Request) -> dict[str, Any]:
        desktop_control(request)
        result = await asyncio.to_thread(knowledge_sync.sync, kb, settings.data_dir, proxy=settings.proxy)
        # Asked for by the person at this PC: restart now unless a question is running (then when it finishes).
        restarting = result.ok and bool(knowledge_status().get("restart_pending")) and restart_if_idle(0)
        return {"outcome": result.outcome, "message": result.message, "commit": result.commit, "restarting": restarting,
                "knowledge_base": knowledge_status()}

    @app.post("/internal/v1/desktop/drop")
    def desktop_drop(request: Request, body: DropBody) -> dict[str, Any]:
        """Files the person dropped on the button or the panel: the page may attach each once, from where it is."""
        desktop_control(request)
        return {"files": [manager.attachments.grant(path[:1000]) for path in body.paths]}

    @app.post("/internal/v1/desktop/stop")
    def desktop_stop(request: Request) -> dict[str, Any]:
        desktop_control(request)
        request_stop = getattr(app.state, "request_stop", None)
        if request_stop is None:
            raise HTTPException(409, "This service was not started by the desktop app.")
        request_stop()
        return {"stopping": True}

    # Frontend ----------------------------------------------------------------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path.startswith(("api/", "internal/")):
            raise HTTPException(404, "Not found.")
        dist = settings.web_dist.resolve()
        index = dist / "index.html"
        if path.startswith("assets/"):
            target = (dist / path).resolve()
            if dist in target.parents and target.is_file():
                return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            raise HTTPException(404, "Not found.")
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<!doctype html><title>Wizard</title><p>The web app is not built yet. Run "
                            "<code>npm --prefix apps/web run build</code>, or use the Vite dev server.</p>")

    return app


def _secure(response: Response) -> Response:
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def public_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return {k: memory[k] for k in ("id", "text", "run_id", "created_at")}


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\ndata: {json.dumps(event, default=str)}\n\n"

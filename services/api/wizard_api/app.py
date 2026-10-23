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
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from wizard_agent import google_oauth, outbound
from wizard_agent.code_assist import CodeAssistRuntime, summarize_quota
from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, inherited_project, resolve_cli_js
from wizard_agent.prompting import recurring_question
from wizard_agent.replay import ReplayRuntime
from wizard_agent.runtime import AgentFailure, AgentRuntime
from wizard_agent.secret_box import SecretBox
from wizard_connectors import metronome
from wizard_connectors.content import errors, validate_content
from wizard_connectors.entitlements import Identity, IdentityDirectory, SystemRights
from wizard_connectors.paths import ROOT
from wizard_connectors.tools import build_registry, build_services

from . import __version__, knowledge_sync, settings_pane
from .attachments import AttachmentError, public
from .config import ConfigError, Settings, kb_source, load_settings
from .metronome_client import MetronomeClient, MetronomeError
from .outlook import DraftError, open_outlook_draft
from .runs import Busy, RunManager, entitled_to, evidence_summary, public_schedule
from .security import REQUEST_HEADER, SECURITY_HEADERS, SESSION_COOKIE, session_token, verify
from .store import Store

OWNER_ID = "local-owner"
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
                   "check_result", "schedule_proposed", "warning", "run_failed", "run_finished"}
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


def create_app(settings: Settings | None = None, runtime: AgentRuntime | None = None,
               google_transport: httpx.AsyncBaseTransport | None = None,
               metronome_transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or load_settings()
    loaded_content = settings.content_dir
    if settings.content_dir:
        problems = validate_content(settings.content_dir)
        for problem in problems:
            log.warning("content: %s", problem)
        if errors(problems):
            raise ConfigError(f"WIZARD_CONTENT_DIR {settings.content_dir} has {len(errors(problems))} error(s); run "
                              "scripts/validate_content.py on it. First: " + str(errors(problems)[0]))
        services = build_services(contracts=settings.content_dir / "contracts" / "sources",
                                  knowledge=settings.content_dir / "knowledge", postgres=settings.postgres,
                                  postgres_name=settings.pg_name)
    elif settings.kb_repo:
        # A knowledge base is configured but has never synced: load nothing rather than the synthetic examples.
        empty = settings.data_dir / "knowledge" / "none"
        services = build_services(contracts=empty / "contracts" / "sources", knowledge=empty / "knowledge",
                                  postgres=settings.postgres, postgres_name=settings.pg_name)
    else:
        services = build_services(postgres=settings.postgres, postgres_name=settings.pg_name)
    services.metronome, services.mail_domains = settings.metronome, settings.google_domains
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
                                       [*(s.id for s in services.catalog.systems), *(["postgresql"] if services.postgres else [])]})
        others = [] if settings.desktop else [i for i in identities.all() if not owner.email or i.email != owner.email]
        identities = IdentityDirectory([owner, *others])
    interrupted = store.mark_interrupted()
    secret_box = SecretBox()
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
            log.info("Wizard %s started: runtime %s (%s), model %s, data %s, proxy %s", __version__, runtime.kind,
                     runtime.label(), settings.model, settings.data_dir, settings.proxy or "resolved per request")
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
        """The systems this person's Wizard can draw on, for the systems stage: report platforms, the database, the
        knowledge base and attached files. Only what they may use."""
        found: list[dict[str, Any]] = [{"id": s.id, "name": s.name, "kind": "reports", "data_mode": s.connector.data_mode}
                                       for s in services.catalog.systems if identity.can_use_system(s.id)]
        if services.postgres and identity.can_use_system("postgresql"):
            found.append({"id": "postgresql", "name": services.postgres_name, "kind": "database", "data_mode": "LIVE"})
        if services.knowledge.notes:
            found.append({"id": "knowledge", "name": "Knowledge base", "kind": "knowledge", "notes": len(services.knowledge.notes)})
        found.append({"id": "attachment", "name": "Attached files", "kind": "files"})
        if can_schedule(identity):
            found.append({"id": "metronome", "name": "Metronome", "kind": "schedules"})
        return found

    def can_schedule(identity: Identity) -> bool:
        """Recurring extractions: Metronome is connected and the person may query the whole database."""
        return bool(settings.metronome and services.postgres and identity.can_use_system("postgresql")
                    and identity.allowed_markets("postgresql") is None)

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
                "runtime": {"kind": runtime.kind, "label": runtime.label(), "model": runtime.model, **readiness},
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
        conversation_id = conversation_id or store.create_conversation(identity.id)
        try:
            run = manager.start(identity, conversation_id, body.question.strip())
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
            run = manager.start(identity, parent["conversation_id"], "Check my data", kind="check", parent_run_id=run_id)
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
                                parent_run_id=run_id)
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
        if settings.auth_mode != "fixture" or not _is_loopback(request.client.host if request.client else None):
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
        internal_run(request)
        return {"tools": registry.describe(scope)}

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


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\ndata: {json.dumps(event, default=str)}\n\n"

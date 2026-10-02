"""HTTP surface. Public API under /api/v1 (browser), loopback-only tool API under /internal/v1 (MCP shims)."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from wizard_agent import google_oauth
from wizard_agent.code_assist import CodeAssistRuntime
from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, resolve_cli_js
from wizard_agent.replay import ReplayRuntime
from wizard_agent.runtime import AgentRuntime
from wizard_agent.secret_box import SecretBox
from wizard_connectors.content import errors, validate_content
from wizard_connectors.entitlements import Identity, IdentityDirectory
from wizard_connectors.paths import ROOT
from wizard_connectors.tools import build_registry, build_services

from . import __version__
from .config import ConfigError, Settings, load_settings
from .runs import Busy, RunManager, entitled_to
from .security import REQUEST_HEADER, SECURITY_HEADERS, SESSION_COOKIE, session_token, verify
from .store import Store

log = logging.getLogger("wizard.api")
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/ready", "/api/v1/bootstrap", "/api/v1/session/login",
                "/api/v1/session/logout", "/api/v1/session/identities"}
TIMELINE_EVENTS = {"run_started", "status", "agent_session", "note", "tool_started", "tool_finished", "visual_added",
                   "check_result", "warning", "run_failed", "run_finished"}
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


class TitleBody(Body):
    title: str = Field(min_length=1, max_length=120)


class FeedbackBody(Body):
    category: Literal["wrong_source", "mismatched_period", "wrong_arithmetic", "omitted_contrary_signal",
                      "unsupported_certainty", "poor_chart", "access_problem", "helpful", "other"]
    note: str = Field(default="", max_length=2000)


class LinkCompleteBody(Body):
    state: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: str = Field(min_length=4, max_length=1024)


class InternalCall(Body):
    arguments: dict[str, Any] = Field(default_factory=dict)
    scope: str | None = Field(default=None, max_length=32)


def build_runtime(settings: Settings, secret_box: SecretBox, scopes: list[str]) -> AgentRuntime:
    if settings.runtime == "gemini-cli":
        cli_js = resolve_cli_js(settings.gemini_cli_js, ROOT)
        return GeminiCliRuntime(GeminiCliConfig(
            model=settings.model, internal_url=settings.internal_url, cli_js=cli_js, node=settings.node, scopes=scopes,
            google_cloud_project=settings.google_cloud_project, timeout_s=settings.run_timeout_s,
            fake_responses=Path(settings.gemini_fake_responses).resolve() if settings.gemini_fake_responses else None,
            shim_cwd=str(ROOT / "services" / "connectors")))
    if settings.runtime == "code-assist":
        return CodeAssistRuntime(settings.model, secret_box, settings.google_cloud_project, settings.thinking)
    return ReplayRuntime(settings.transcripts_dir, settings.replay_delay_s)


def _is_loopback(host: str | None) -> bool:
    try:
        return bool(host) and ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return host == "testclient"


def create_app(settings: Settings | None = None, runtime: AgentRuntime | None = None,
               google_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or load_settings()
    if settings.content_dir:
        problems = validate_content(settings.content_dir)
        for problem in problems:
            log.warning("content: %s", problem)
        if errors(problems):
            raise ConfigError(f"WIZARD_CONTENT_DIR {settings.content_dir} has {len(errors(problems))} error(s); run "
                              "scripts/validate_content.py on it. First: " + str(errors(problems)[0]))
        services = build_services(contracts=settings.content_dir / "contracts" / "sources",
                                  knowledge=settings.content_dir / "knowledge")
    else:
        services = build_services()
    registry = build_registry(services)
    identities = IdentityDirectory.load(settings.identities_file)
    store = Store(settings.data_dir / "wizard.sqlite3")
    interrupted = store.mark_interrupted()
    secret_box = SecretBox()
    runtime = runtime or build_runtime(settings, secret_box, registry.scopes())
    manager = RunManager(settings, store, registry, services, runtime)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if interrupted:
            log.warning("%d run(s) were interrupted by a restart and marked failed", interrupted)
        yield
        await manager.shutdown()

    app = FastAPI(title="Wizard", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/v1/openapi.json")
    app.state.settings, app.state.store, app.state.manager, app.state.registry = settings, store, manager, registry

    def identity_of(request: Request) -> Identity | None:
        if settings.auth_mode == "trusted-header":
            client = request.client.host if request.client else None
            email = request.headers.get(settings.identity_header, "").strip()
            if client not in settings.trusted_proxies or not email:
                return None
            return identities.by_login(email) or Identity(id=f"sso:{email.lower()}", email=email.lower(), name=email,
                                                           role="Unassigned", entitlements={})
        claims = verify(settings.session_secret, "session", request.cookies.get(SESSION_COOKIE))
        return identities.get(str(claims["u"])) if claims else None

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
        request.state.identity = identity_of(request) if path.startswith("/api/") else None
        if path.startswith("/api/") and path not in PUBLIC_PATHS and request.state.identity is None:
            return _secure(JSONResponse({"error": "Sign in to use Wizard.", "login_required": True}, status_code=401))
        response = await call_next(request)
        if path.startswith(("/api/", "/internal/")):
            response.headers["Cache-Control"] = "no-store"
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
        checks = {"store": True, "catalog": bool(services.catalog.systems), "runtime": runtime.kind,
                  "content": str(settings.content_dir) if settings.content_dir else "synthetic (built-in)",
                  "runtime_label": runtime.label(), "secret_store": secret_box.kind, "auth_mode": settings.auth_mode,
                  "frontend_built": (settings.web_dist / "index.html").is_file()}
        return {"ready": all(v for k, v in checks.items() if isinstance(v, bool) and k != "frontend_built"), "checks": checks}

    async def account_status(identity: Identity) -> dict[str, Any]:
        home = settings.user_home(identity.id)
        link = store.link(identity.id)
        cli_present = any((GeminiCliRuntime.gemini_home(home) / ".gemini" / name).is_file()
                          for name in ("gemini-credentials.json", "oauth_creds.json"))
        return {"linked": bool(link) or cli_present, "google_email": link["google_email"] if link else None,
                "linked_at": link["linked_at"] if link else None, "method": link["method"] if link else
                ("gemini-cli (host sign-in)" if cli_present else None), "cli_credentials_present": cli_present,
                "secret_store": secret_box.kind, "needs_link": runtime.kind != "replay"}

    @app.get("/api/v1/bootstrap")
    async def bootstrap(request: Request) -> dict[str, Any]:
        identity: Identity | None = request.state.identity
        base: dict[str, Any] = {"version": __version__, "auth": {"mode": settings.auth_mode, "login_required": identity is None},
                                "suggestions": SUGGESTIONS}
        if identity is None:
            return base
        store.touch_user(identity.id, identity.email, identity.name, identity.role)
        readiness = await runtime.readiness(settings.user_home(identity.id), identity.email)
        modes = sorted({s.connector.data_mode for s in services.catalog.systems if identity.can_use_system(s.id)
                        and s.connector.status in ("SYNTHETIC_FIXTURE", "ROWS_VERIFIED")})
        return {**base, "identity": {"id": identity.id, "name": identity.name, "email": identity.email, "role": identity.role},
                "runtime": {"kind": runtime.kind, "label": runtime.label(), "model": runtime.model, **readiness},
                "gemini_account": await account_status(identity), "data_modes": modes}

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
        response.set_cookie(SESSION_COOKIE, session_token(settings.session_secret, identity.id, settings.session_hours),
                            httponly=True, samesite="strict", secure=settings.secure_cookies, max_age=settings.session_hours * 3600)
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
        events = [e for e in store.events(run["id"]) if e["type"] in TIMELINE_EVENTS]
        visuals = store.visuals(run["conversation_id"], run["id"])
        evidence = [{k: e.get(k) for k in ("id", "system", "system_name", "report_id", "report_name", "data_mode",
                                           "as_of", "total_rows", "truncated", "warnings", "access_note", "run_id")}
                    for e in store.evidence(run["conversation_id"]) if e.get("run_id") == run["id"]]
        public = {k: v for k, v in run.items() if k not in ("user_id", "stats")}
        public["stats"] = json.loads(run["stats"]) if run.get("stats") else {}
        return {**public, "events": events, "visuals": visuals, "evidence": evidence, "active": run["id"] in manager.active}

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
        conversation_id = conversation_id or store.create_conversation(identity.id)
        try:
            run = manager.start(identity, conversation_id, body.question.strip())
        except Busy as busy:
            raise HTTPException(429, str(busy)) from None
        return {"run_id": run["id"], "conversation_id": conversation_id}

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
        async with httpx.AsyncClient(timeout=30, transport=google_transport) as http:
            try:
                tokens = await google_oauth.exchange_code(http, body.code, verifier)
                info = await google_oauth.userinfo(http, tokens.access_token)
            except google_oauth.OAuthError as error:
                store.audit(identity.id, "gemini:link", outcome=error.code)
                raise HTTPException(400, error.message) from None
        if settings.require_google_email_match and info["email"].lower() != identity.email.lower():
            store.audit(identity.id, "gemini:link", outcome="email_mismatch")
            raise HTTPException(403, f"Sign in with your own enterprise Google account ({identity.email}). Wizard does not "
                                     "run your questions under another person's Gemini entitlement.")
        home = settings.user_home(identity.id)
        secret_box.write(CodeAssistRuntime.token_path(home), tokens.refresh_token)
        google_oauth.write_cli_credentials(GeminiCliRuntime.gemini_home(home), tokens)
        store.save_link(identity.id, info["email"], settings.google_cloud_project, "user-code")
        store.audit(identity.id, "gemini:link")
        return await account_status(identity)

    @app.delete("/api/v1/account/gemini")
    async def gemini_unlink(request: Request) -> dict[str, Any]:
        identity = me(request)
        home = settings.user_home(identity.id)
        secret_box.delete(CodeAssistRuntime.token_path(home))
        google_oauth.clear_cli_credentials(GeminiCliRuntime.gemini_home(home))
        store.delete_link(identity.id)
        store.audit(identity.id, "gemini:unlink")
        return await account_status(identity)

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

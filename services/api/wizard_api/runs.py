"""Run manager: one agent run per question, executed in the background with every observed action streamed and stored.

What the timeline shows is what actually happened: model text as it streams, each tool call Wizard executed (with its
evidence id), warnings and failures. It never shows private chain of thought and never invents steps. Tool execution
always goes through the registry with the run's own identity, whichever runtime asked for it."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wizard_agent.prompting import compose
from wizard_agent.runtime import AgentFailure, AgentRequest, AgentRuntime, Turn, redact
from wizard_connectors.attachment_tables import index as table_index
from wizard_connectors.entitlements import Identity
from wizard_connectors.tools import Services, ToolContext, ToolError, ToolOutcome, ToolRegistry

from .attachments import AttachmentError, Attachments
from .attachments import public as public_attachment
from .awake import KeepAwake
from .config import Settings
from .security import run_token
from .settings_pane import installed_build
from .store import Store, new_id, now

log = logging.getLogger("wizard.runs")
# The headline data mode of an answer is its weakest source: a user's file ranks above synthetic data, below approved ones.
DATA_MODE_RANK = {"SYNTHETIC": 0, "USER_PROVIDED": 1, "LIVE": 2, "DATED_APPROVED_SNAPSHOT": 3, "LIVE_VERIFIED": 4}
CITATION = re.compile(r"\[(E\d{1,4})\]")
VISUAL = re.compile(r"\[(V\d{1,4})\]")
# Loop check. Tools are read-only, so an identical call returns what it returned before: a second try is allowed (a view
# being refreshed can time out once), a third is refused, and after LOOP_STOP refusals the run stops researching.
REPEAT_LIMIT = 2
LOOP_STOP = 3
RESEARCH = ("source", "knowledge")  # tool categories that gather more; calculating and presenting stay open to the end
# Mapping a portal (owner, 30 Oct 2026): Gemini explores in rounds of at most this many tool calls, each a fresh session
# that continues from the map, so a long exploration never outgrows the model's context. Rounds follow one another
# until nothing is left to map, a round makes no progress twice, the person stops it, or EXPLORE_ROUNDS have run.
EXPLORE_TOOL_CALLS = 80
EXPLORE_ROUNDS = 30
EXPLORE_STALLS = 2


def wrap_up_s(timeout_s: int) -> int:
    """Time kept back at the end of a run for Gemini to write its answer instead of being cut off mid-research."""
    return min(240, timeout_s // 5)


def call_signature(name: str, args: dict[str, Any]) -> str:
    """Same tool, same arguments; whitespace inside strings (a reformatted SQL statement) does not make a call new."""
    def squeeze(value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, dict):
            return {k: squeeze(v) for k, v in value.items()}
        if isinstance(value, list):
            return [squeeze(v) for v in value]
        return value
    return name + json.dumps(squeeze(args), sort_keys=True, default=str)


# What a run that is not a typed question stands for in the conversation, the report and the next prompt. A Make
# recurring run's question already says it ("Make this recurring: every Monday").
KIND_TITLES = {"check": "Check my data"}


def run_title(kind: str, question: str) -> str:
    return KIND_TITLES.get(kind, question)


SUMMARY_KEYS = ("id", "system", "system_name", "report_id", "report_name", "folder_path", "data_mode", "as_of",
                "total_rows", "truncated", "warnings", "access_note", "run_id")


def evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """One evidence item as the run card and the timeline show it; the drawer loads the rows. The SQL and the report's
    folders let the card name the real source (the table a query read, the module a report sits in), so fourteen
    queries on one table read as one source."""
    return {**{k: evidence.get(k) for k in SUMMARY_KEYS}, "sql": (evidence.get("request") or {}).get("sql")}


def public_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """A recurring brief as the page shows it (who asked is the viewer; never their user id). The test run's rows stay
    on the server: the card loads the email preview on its own."""
    shown = {k: v for k, v in schedule.items() if k not in ("requested_by", "conversation_id")}
    preview = schedule.get("preview") or {}
    if "results" in preview:
        shown["preview"] = {"period": preview.get("period"), "read_at": preview.get("read_at"),
                            "rows": [len(result.get("rows") or []) for result in preview["results"]]}
    return {**shown, "requested_by": {"name": schedule.get("requested_by", {}).get("name")}}


def minutes(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60} min {whole % 60} s"


class Busy(Exception):
    pass


@dataclass
class Exploration:
    """A portal being mapped for one person: its rounds run one after another in one conversation."""
    system: str
    name: str
    conversation_id: str
    started_at: str
    round: int = 0
    run_id: str | None = None
    state: str = "running"  # running | finished | stopped | failed
    message: str = ""
    stalls: int = 0
    before: dict[str, int] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {"system": self.system, "conversation_id": self.conversation_id, "started_at": self.started_at,
                "round": self.round, "run_id": self.run_id, "state": self.state, "message": self.message}


@dataclass
class ActiveRun:
    id: str
    identity: Identity
    conversation_id: str
    kind: str
    question: str
    parent_run_id: str | None
    runtime_kind: str
    seq: int = 0
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)
    cancelled: bool = False
    tool_calls: int = 0
    started: float = 0.0  # time.monotonic() when the agent started; 0 until then
    calls_seen: dict[str, int] = field(default_factory=dict)
    repeats_refused: int = 0
    segment: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    visual_ids: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    session: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    last_tool: str = ""    # the last tool call and how it ended, for Error details
    last_status: str = ""  # the last status line the stage showed, for Error details
    waits: int = 0         # times Wizard waited for Gemini (not shown on the stage), for Error details
    waited_s: float = 0.0
    files_made: list[str] = field(default_factory=list)  # edited copies made in this run, announced to the page
    explore: dict[str, Any] | None = None  # a mapping round: {system, name, round}
    maps_changed: set[str] = field(default_factory=set)  # portals whose map this run added to (published after it)
    needs_sign_in: bool = False  # a portal asked for a sign-in during this run
    task: asyncio.Task[None] | None = None


class Recorder:
    """Conversation-scoped evidence (E1, E2... stay valid across follow-ups) with run attribution, and the files attached
    to the conversation (F1, F2...)."""

    def __init__(self, store: Store, run: ActiveRun, files: Attachments | None = None):
        self.store, self.run, self.files = store, run, files

    def attachments(self) -> list[dict[str, Any]]:
        return [a for a in self.store.conversation_attachments(self.run.conversation_id) if a["user_id"] == self.run.identity.id]

    def attachment(self, label: str) -> tuple[dict[str, Any], str] | None:
        row = next((a for a in self.attachments() if a["label"] == label), None)
        if row is None or self.files is None:
            return None
        return row, self.files.text(row)

    def edit_attachment(self, label: str, operations: list[dict[str, Any]], name: str | None) -> dict[str, Any]:
        row = next((a for a in self.attachments() if a["label"] == label), None)
        if row is None or self.files is None:
            labels = ", ".join(f"{a['label']} {a['filename']}" for a in self.attachments()) or "none"
            raise ToolError("unknown_file", f"No attached file {label} in this conversation. Attached files: {labels}.")
        try:
            edited = self.files.edit(self.run.identity, self.run.conversation_id, self.run.id, row, operations, name)
        except AttachmentError as error:
            raise ToolError("edit_failed", error.message) from None
        self.run.files_made.append(edited["id"])
        return edited

    def add_evidence(self, payload: dict[str, Any]) -> str:
        evidence_id = self.store.add_evidence(self.run.conversation_id, self.run.id, self.run.identity.id, payload)
        self.run.evidence_ids.append(evidence_id)
        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        found = self.store.evidence(self.run.conversation_id, evidence_id)
        return found[0] if found else None

    def all_evidence(self) -> list[dict[str, Any]]:
        return self.store.evidence(self.run.conversation_id)

    def add_visual(self, payload: dict[str, Any]) -> str:
        visual_id = self.store.add_visual(self.run.conversation_id, self.run.id, payload)
        self.run.visual_ids.append(visual_id)
        return visual_id

    def add_check(self, payload: dict[str, Any]) -> None:
        self.store.add_check(self.run.id, payload)
        self.run.checks.append(payload)

    def add_schedule(self, payload: dict[str, Any]) -> str:
        _, label = self.store.add_schedule(self.run.conversation_id, self.run.id, self.run.identity.id, payload)
        return label


class Bridge:
    def __init__(self, manager: RunManager, run: ActiveRun):
        self.manager, self.run = manager, run

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        outcome = await self.manager.execute_tool(self.run.id, name, arguments)
        return outcome.ok, outcome.as_text()

    def describe(self) -> list[dict[str, Any]]:
        return self.manager.registry.describe()

    def evidence_index(self) -> list[dict[str, Any]]:
        return [{"id": e["id"], "report_id": e.get("report_id")} for e in self.manager.store.evidence(self.run.conversation_id)]


def portal_name(services: Services, system: Any) -> str:
    portal = services.portals.settings.portal(str(system)) if services.portals else None
    return portal.name if portal else str(system or "the portal").upper()


def tool_label(name: str, args: dict[str, Any], services: Services) -> str:
    if name == "portal_run":
        what = args.get("title") or (f"saved script {args['script']}" if args.get("script") else "")
        return f"Read {portal_name(services, args.get('system'))} in your browser" + (f": {what}" if what else "")
    if name == "portal_guide":
        return f"Read Wizard's guide to {portal_name(services, args.get('system'))}"
    if name == "portal_save_script":
        return f"Kept a {portal_name(services, args.get('system'))} script: {args.get('name', '')}"
    if name == "portal_map":
        what = args.get("find") or args.get("report") or args.get("topic") or ("what is left to map" if args.get("todo") else "")
        return f"Read Wizard's map of {portal_name(services, args.get('system'))}" + (f": {what}" if what else "")
    if name == "portal_map_save":
        reports = [r for r in args.get("reports") or [] if isinstance(r, dict)]
        what = (str(reports[0].get("name") or reports[0].get("id")) if len(reports) == 1 else
                f"{len(reports)} reports" if reports else "how it works")
        return f"Added to Wizard's map of {portal_name(services, args.get('system'))}: {what}"
    if name == "portal_request_access":
        tables = ", ".join(str(t) for t in args.get("tables") or [])
        return f"Prepared an access request in {portal_name(services, args.get('system'))}" + (f": {tables}" if tables else "")
    system = name.split("_", 1)[0].upper()
    if name.endswith("_search_reports"):
        return f"Searched {system} reports for “{args.get('query', '')}”"
    if name == "wizard_search_catalog":
        return f"Searched all sources for “{args.get('query', '')}”"
    if name.endswith("_get_report_schema") or name.endswith("_run_report"):
        found = services.catalog.report(str(args.get("report_id", "")))
        title = found[1].name if found else str(args.get("report_id", "a report"))
        verb = "Inspected" if name.endswith("_get_report_schema") else "Read"
        filters = ", ".join(f"{f.get('field')}={'/'.join(map(str, f.get('values', [])))}" for f in args.get("filters", [])
                            if isinstance(f, dict))
        return f"{verb} {system} · {title}" + (f" ({filters})" if filters and verb == "Read" else "")
    return {"wizard_list_sources": "Listed the sources you can use",
            "wizard_lookup_definitions": f"Looked up “{args.get('query', '')}”",
            "wizard_browse_knowledge": f"Browsed the knowledge base{' · ' + str(args['area']) if args.get('area') else ''}",
            "wizard_read_knowledge": f"Read {', '.join(map(str, args.get('ids', [])))}",
            "wizard_read_attachment": f"Read attached file {args.get('file', '')}" + (f" · {args['part']}" if args.get("part") else ""),
            "wizard_edit_attachment": f"Edited a copy of {args.get('file', '')}: {len(args.get('operations', []))} change(s)",
            "wizard_query_attachment": f"Queried attached file {args.get('file', '')}" + (f" · {args['sheet']}" if args.get("sheet") else ""),
            "wizard_query_postgresql": f"Queried the {services.postgres_name}",
            "wizard_calculate": f"Calculated {str(args.get('expression', ''))[:80]}",
            "wizard_render_visual": f"Prepared a {args.get('kind', 'visual')}: {args.get('title', '')}",
            "wizard_schedule_brief": f"Prepared a recurring brief for Metronome: {args.get('title', '')}",
            "wizard_check_my_data": f"Checked {len(args.get('claims', []))} figure(s) against the evidence"}.get(name, name)


def tool_summary(name: str, outcome: ToolOutcome) -> str:
    if not outcome.ok:
        return f"{outcome.error_code}: {outcome.error_message}"
    data = outcome.data
    if "schedule" in data:
        return f"{data['schedule']} waiting for your confirmation · {data['sends']}"
    if name == "portal_run":
        tables = [o for o in data.get("outputs", []) if "evidence_id" in o]
        page = (data.get("page") or {}).get("title") or ""
        text = (f"{len(tables)} table(s), {sum(o['total_rows'] for o in tables):,} rows" if tables
                else f"on {page}" if page else "done")
        return text + (f" · stopped: {data['stopped']['code']}" if data.get("stopped") else "") + (
            f" · {len(data['refused'])} request(s) refused" if data.get("refused") else "")
    if name == "portal_guide":
        return f"{data.get('name')} guide · {len(data.get('saved_scripts', []))} saved script(s)"
    if name == "wizard_edit_attachment":
        return f"{data['file']} {data['name']} ready to download · {len(data['changes'])} change(s)"
    if name == "portal_save_script":
        return f"saved {data.get('saved')}"
    if name == "portal_map_save":
        counts = data.get("counts") or {}
        return (f"{len(data.get('added', []))} added, {len(data.get('updated', []))} updated · map: {counts.get('mapped', 0)} "
                f"mapped, {counts.get('todo', 0)} to do")
    if name == "portal_map":
        if "report" in data:
            return f"{data['report'].get('name') or data['report'].get('id')} ({data['report'].get('status')})"
        if "todo" in data:
            return f"{len(data['todo'])} report(s) still to map"
        if "reports" in data and "counts" not in data:
            return ", ".join(str(r.get("name") or r.get("id")) for r in data["reports"][:5]) or "nothing matches"
        counts = data.get("counts") or {}
        return f"{counts.get('mapped', 0)} report(s) mapped, {counts.get('todo', 0)} to do" if counts else "done"
    if name == "portal_request_access":
        return "waiting for you to open the request form and submit it"
    if name.endswith("_run_report"):
        extra = f" of {data['total_rows']}" if data.get("truncated") else ""
        as_of = f" · as of {str(data.get('as_of'))[:10]}" if data.get("as_of") else ""
        return f"{data.get('row_count', 0)}{extra} rows{as_of}"
    if "results" in data:
        return f"{len(data['results'])} report(s) found"
    if "row_count" in data:
        return f"{data['row_count']:,} row{'' if data['row_count'] == 1 else 's'}" + (" (more available)" if data.get("truncated") else "")
    if "definitions" in data:
        return ", ".join(d["title"] for d in data["definitions"]) or "no definition found"
    if "notes" in data:
        if "areas" in data:
            return f"{len(data['notes'])} note(s) in {len(data['areas'])} area(s)"
        return ", ".join(n["title"] for n in data["notes"])
    if "file" in data and "text" in data:
        return f"{data.get('name')}: {data.get('chars', 0):,} characters" + (" (more to read)" if data.get("next_offset") else "")
    if "result" in data:
        return f"= {data['result']:,.6g}"
    if "visual_id" in data:
        return f"{data['visual_id']} ready"
    if "overall" in data:
        return f"{data['overall']}: {data.get('summary', '')}"
    if "sources" in data:
        return f"{len(data['sources'])} source(s)"
    if "report_id" in data:
        return str(data.get("name", ""))
    return "done"


def entitled_to(identity: Identity, evidence: dict[str, Any]) -> bool:
    system, report_id = evidence.get("system"), evidence.get("report_id")
    if system == "attachment":
        return True  # the user's own file in their own conversation (callers check the conversation owner)
    if not system or not report_id or not identity.can_see_report(system, report_id):
        return False
    allowed = identity.allowed_markets(system)
    keys = [c["key"] for c in evidence.get("columns", [])]
    if allowed is None or "market" not in keys:
        return True
    index = keys.index("market")
    return {row[index] for row in evidence.get("rows", [])} <= allowed


class RunManager:
    def __init__(self, settings: Settings, store: Store, registry: ToolRegistry, services: Services, runtime: AgentRuntime):
        self.settings, self.store, self.registry, self.services, self.runtime = settings, store, registry, services, runtime
        self.active: dict[str, ActiveRun] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self.attachments = Attachments(settings, store)
        self.awake = KeepAwake()
        self.explorations: dict[str, Exploration] = {}  # by person

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_runs)
        return self._semaphore

    # Lifecycle ---------------------------------------------------------------------------------------------------------
    def start(self, identity: Identity, conversation_id: str, question: str, kind: str = "ask",
              parent_run_id: str | None = None, explore: dict[str, Any] | None = None) -> dict[str, Any]:
        # A question and a portal being mapped run side by side: one of each per person.
        mapping = kind == "explore"
        if any(r.identity.id == identity.id and (r.kind == "explore") == mapping for r in self.active.values()):
            raise Busy("Wizard is already mapping a portal for you. Stop it in Settings → Portals first." if mapping else
                       "A question is already running for you. Wait for it or cancel it.")
        if len(self.active) >= self.settings.max_concurrent_runs * 4:
            raise Busy("Wizard is busy. Try again in a minute.")
        run_id = new_id("run")
        row = {"id": run_id, "conversation_id": conversation_id, "user_id": identity.id, "kind": kind,
               "question": question, "status": "queued", "runtime": self.runtime.kind, "runtime_label": self.runtime.label(),
               "model": self.runtime.model, "check_status": "NOT_CHECKED", "parent_run_id": parent_run_id,
               "created_at": now()}
        self.store.create_run(row)
        self.store.touch_conversation(conversation_id, question[:80] if kind == "ask" else None)
        run = ActiveRun(run_id, identity, conversation_id, kind, question, parent_run_id, self.runtime.kind, explore=explore)
        self.active[run_id] = run
        run.task = asyncio.get_running_loop().create_task(self._execute(run))
        return row

    def cancel(self, user_id: str, run_id: str) -> bool:
        run = self.active.get(run_id)
        if not run or run.identity.id != user_id:
            return False
        run.cancelled = True
        if run.task:
            run.task.cancel()
        return True

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]] | None:
        run = self.active.get(run_id)
        if run is None:
            return None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        run.subscribers.append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        run = self.active.get(run_id)
        if run and queue in run.subscribers:
            run.subscribers.remove(queue)

    async def shutdown(self) -> None:
        for run in list(self.active.values()):
            self.cancel(run.identity.id, run.id)
        tasks = [r.task for r in self.active.values() if r.task]
        if tasks:
            await asyncio.wait(tasks, timeout=20)

    # Events ------------------------------------------------------------------------------------------------------------
    async def emit(self, run: ActiveRun, kind: str, payload: dict[str, Any]) -> None:
        if kind == "text_delta":
            run.segment.append(str(payload.get("text", "")))
        boundary = (kind == "model_tool_trace" and payload.get("phase") == "use") if run.runtime_kind == "gemini-cli" \
            else kind == "tool_started"
        if boundary and "".join(run.segment).strip():
            text = "".join(run.segment).strip()
            run.segment.clear()
            run.notes.append(text)
            self._publish(run, "note", {"text": text})
        elif boundary:
            run.segment.clear()
        if kind == "agent_session":
            run.session = payload
            self.store.update_run(run.id, session_id=payload.get("session_id"), model=payload.get("model") or self.runtime.model)
        elif kind == "agent_stats":
            run.stats = dict(payload.get("stats") or {})
        elif kind == "warning":
            run.warnings.append(str(payload.get("message", ""))[:500])
        elif kind == "status":
            run.last_status = str(payload.get("message", ""))[:500]
        elif kind == "model_wait":
            run.waits += 1
            run.waited_s += float(payload.get("seconds") or 0)
        self._publish(run, kind, payload)

    def _publish(self, run: ActiveRun, kind: str, payload: dict[str, Any]) -> None:
        run.seq += 1
        stamp = self.store.add_event(run.id, run.seq, kind, payload)
        event = {"seq": run.seq, "type": kind, "ts": stamp, "payload": payload}
        for queue in list(run.subscribers):
            queue.put_nowait(event)

    # Tools -------------------------------------------------------------------------------------------------------------
    async def execute_tool(self, run_id: str, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        run = self.active.get(run_id)
        if run is None or run.cancelled:
            return ToolOutcome(False, {}, 0, "run_not_active", "This run is no longer active.")
        run.tool_calls += 1
        call_id = f"c{run.tool_calls}"
        args = arguments if isinstance(arguments, dict) else {}
        spec = self.registry.specs.get(name)
        encoded = json.dumps(args, default=str)
        shown = json.loads(encoded) if len(encoded) <= 4000 else {"truncated": True}
        await self.emit(run, "tool_started", {"call_id": call_id, "name": name, "label": tool_label(name, args, self.services),
                                              "category": spec.category if spec else "unknown", "arguments": shown})
        outcome = self._bound(run, name, args, spec.category if spec else None)
        if outcome is None:
            context = ToolContext(identity=run.identity, run_id=run.id, recorder=Recorder(self.store, run, self.attachments),
                                  services=self.services)
            outcome = await asyncio.to_thread(self.registry.execute, name, args, context)
        if spec and spec.category == "source":
            self.store.audit(run.identity.id, f"tool:{name}", run_id=run.id,
                             system=str(args.get("system")) if name.startswith("portal_") else name.split("_", 1)[0],
                             report_id=str(args.get("report_id")) if args.get("report_id") else None,
                             outcome="ok" if outcome.ok else str(outcome.error_code),
                             detail={"filters": [f.get("field") for f in args.get("filters", []) if isinstance(f, dict)],
                                     "group_by": args.get("group_by")})
        finished: dict[str, Any] = {"call_id": call_id, "name": name, "ok": outcome.ok, "duration_ms": outcome.duration_ms,
                                    "summary": tool_summary(name, outcome)}
        if not outcome.ok:
            finished["error_code"] = outcome.error_code
        run.last_tool = f"{name} at {datetime.now().strftime('%H:%M:%S')}: " + (
            "ok" if outcome.ok else f"{outcome.error_code}: {outcome.error_message or ''}".strip(": "))
        first = outcome.data.get("evidence_id") or (outcome.data.get("evidence_ids") or [None])[0] if outcome.ok else None
        if first:  # a brief's test run reads several queries; the step shows its first
            evidence = self.store.evidence(run.conversation_id, first)[0]
            finished["evidence"] = evidence_summary(evidence)
        await self.emit(run, "tool_finished", finished)
        if outcome.ok and "visual_id" in outcome.data:
            visual = self.store.visuals(run.conversation_id, run.id)[-1]
            await self.emit(run, "visual_added", {"visual": visual})
        if outcome.ok and "schedule" in outcome.data:
            schedule = next(s for s in self.store.schedules(run.conversation_id, run.id) if s["label"] == outcome.data["schedule"])
            await self.emit(run, "schedule_proposed", {"schedule": public_schedule(schedule)})
        if outcome.ok and name == "portal_map_save":
            run.maps_changed.add(str(outcome.data.get("system")))
        if not outcome.ok and outcome.error_code == "sign_in_required":
            run.needs_sign_in = True
        if outcome.ok and name == "portal_request_access":
            await self.emit(run, "access_request_proposed", {"request": outcome.data["access_request"]})
        if outcome.ok and name == "wizard_edit_attachment":
            made = next((a for a in self.store.conversation_attachments(run.conversation_id) if a["id"] == outcome.data["attachment_id"]), None)
            if made is not None:
                await self.emit(run, "file_made", {"attachment": public_attachment(made)})
        if outcome.ok and name == "wizard_check_my_data":
            await self.emit(run, "check_result", {"overall": outcome.data["overall"], "summary": outcome.data["summary"],
                                                  "claims": outcome.data["claims"], "replays": outcome.data["replays"]})
        return outcome

    def _bound(self, run: ActiveRun, name: str, args: dict[str, Any], category: str | None) -> ToolOutcome | None:
        """Stop a run from spinning without choosing its route: refuse an identical repeat, and once the run keeps
        repeating or nears its time limit, refuse further research so Gemini answers with what it has. A refusal is a
        tool error Gemini reads; the run goes on. None means the call may run."""
        limit = min(EXPLORE_TOOL_CALLS, self.settings.max_tool_calls) if run.kind == "explore" else self.settings.max_tool_calls
        if run.tool_calls > limit and not (run.kind == "explore" and name == "portal_map_save"):
            return ToolOutcome(False, {}, 0, "tool_budget_exhausted",
                               f"This run reached its limit of {limit} tool calls. " + (
                                   "Save what you learned with portal_map_save if you have not, then summarise this round; "
                                   "Wizard starts the next round." if run.kind == "explore" else
                                   "Answer with what you have and say what is missing."))
        signature = call_signature(name, args)
        run.calls_seen[signature] = seen = run.calls_seen.get(signature, 0) + 1
        if seen > REPEAT_LIMIT:
            run.repeats_refused += 1
            log.warning("run %s: Gemini repeated an identical %s call (%d times); refused", run.id, name, seen)
            return ToolOutcome(False, {}, 0, "repeated_call",
                               f"You already made this exact call {REPEAT_LIMIT} times in this run; the tools are read-only, "
                               "so it returns the same result. Use that result, change the call, or answer with what you have.")
        if category is not None and category not in RESEARCH:
            return None
        if run.repeats_refused >= LOOP_STOP:
            return ToolOutcome(False, {}, 0, "loop_stopped",
                               "This run keeps repeating calls. Stop gathering data and write your answer now with what you "
                               "have; say what is missing.")
        left = self.settings.run_timeout_s - (time.monotonic() - run.started)
        if run.started and left < wrap_up_s(self.settings.run_timeout_s):
            return ToolOutcome(False, {}, 0, "time_nearly_up",
                               f"About {max(1, round(left / 60))} minute(s) remain before this run's time limit. Stop "
                               "gathering data and write your answer now with what you have; say what is missing.")
        return None

    # Execution ---------------------------------------------------------------------------------------------------------
    def history(self, run: ActiveRun) -> list[Turn]:
        turns = []
        for previous in self.store.runs(run.conversation_id):
            if previous["id"] != run.id and previous["status"] == "succeeded" and previous.get("answer"):
                turns.append(Turn(run_title(previous["kind"], previous["question"]), previous["answer"]))
        return turns

    async def _execute(self, run: ActiveRun) -> None:
        with self.awake:  # a sleeping PC would stop the answer half-way: it stays awake until the run ends
            await self._answer(run)
        for system in sorted(run.maps_changed):
            await self._publish_map(system)
        if run.kind == "explore":
            await self._next_round(run)

    # Portal maps -------------------------------------------------------------------------------------------------------
    async def _publish_map(self, system: str) -> None:
        maps = self.services.portal_maps
        if maps is None or maps.writer is None:
            return
        result = await asyncio.to_thread(maps.publish, system)
        (log.info if result.outcome in ("published", "unchanged") else log.warning)(
            "portal map %s: %s %s", system, result.outcome, result.message)

    def start_exploration(self, identity: Identity, system: str, name: str) -> Exploration:
        """Map a portal: the first round now, the next ones as each round ends (_next_round)."""
        current = self.explorations.get(identity.id)
        if current is not None and current.state == "running":
            raise Busy(f"Wizard is already mapping {current.name} for you.")
        conversation_id = self.store.create_conversation(identity.id, f"Map {name}")
        exploration = Exploration(system, name, conversation_id, now())
        self.explorations[identity.id] = exploration
        try:
            self._round(identity, exploration)
        except Busy:
            del self.explorations[identity.id]
            raise
        return exploration

    def _round(self, identity: Identity, exploration: Exploration) -> None:
        maps = self.services.portal_maps
        exploration.before = maps.counts(maps.load(exploration.system)) if maps else {}
        exploration.round += 1
        question = f"Map {exploration.name}" + (f" (round {exploration.round})" if exploration.round > 1 else "")
        row = self.start(identity, exploration.conversation_id, question, kind="explore",
                         explore={"system": exploration.system, "name": exploration.name, "round": exploration.round})
        exploration.run_id = row["id"]
        exploration.message = f"Round {exploration.round} is running."

    def stop_exploration(self, user_id: str) -> Exploration | None:
        exploration = self.explorations.get(user_id)
        if exploration is None or exploration.state != "running":
            return exploration
        exploration.state, exploration.message = "stopped", f"Stopped by you during round {exploration.round}."
        if exploration.run_id:
            self.cancel(user_id, exploration.run_id)
        return exploration

    async def _next_round(self, run: ActiveRun) -> None:
        exploration = self.explorations.get(run.identity.id)
        if exploration is None or exploration.run_id != run.id or exploration.state != "running":
            return
        maps = self.services.portal_maps
        data = maps.load(exploration.system) if maps else None
        after = maps.counts(data) if maps and data else {}
        finished = self.store.run(run.identity.id, run.id) or {}
        status, code = finished.get("status"), finished.get("error_code")
        progressed = after != exploration.before or bool(run.maps_changed)
        exploration.stalls = 0 if progressed else exploration.stalls + 1
        waiting = after.get("todo", 0) + after.get("partial", 0)
        if status == "cancelled":
            exploration.state, exploration.message = "stopped", f"Round {exploration.round} was cancelled."
        elif code in ("gemini_signin_required", "runtime_unavailable", "model_quota", "model_permission_denied",
                      "gemini_project_unresolved"):
            exploration.state = "failed"
            exploration.message = f"Round {exploration.round} could not run: {finished.get('error_message') or code}"
        elif run.needs_sign_in and not progressed:
            exploration.state = "failed"
            exploration.message = (f"{exploration.name} asks for a sign-in: press Sign in to the portals, sign in in the "
                                   "window that opens and close it, then Continue mapping.")
        elif data is not None and data.get("overview") and data["reports"] and not waiting:
            exploration.state = "finished"
            exploration.message = f"Mapped: {after.get('mapped', 0)} report(s), {after.get('failed', 0)} failed."
        elif exploration.stalls >= EXPLORE_STALLS:
            exploration.state = "failed"
            exploration.message = (f"Stopped after round {exploration.round}: {EXPLORE_STALLS} rounds in a row added nothing "
                                   "to the map. Open the Map conversation to see why.")
        elif exploration.round >= EXPLORE_ROUNDS:
            exploration.state = "finished"
            exploration.message = (f"Paused after {EXPLORE_ROUNDS} rounds with {waiting} report(s) still to map: press "
                                   "Continue mapping to go on.")
        if exploration.state != "running":
            log.info("portal map %s for %s: %s", exploration.system, run.identity.id, exploration.message)
            return
        try:
            self._round(run.identity, exploration)
        except Busy as busy:
            exploration.state, exploration.message = "failed", str(busy)

    async def _answer(self, run: ActiveRun) -> None:
        try:
            async with self.semaphore:
                self.store.update_run(run.id, status="running")
                await self.emit(run, "run_started", {"run_id": run.id, "kind": run.kind, "runtime": self.runtime.kind,
                                                     "runtime_label": self.runtime.label(), "model": self.runtime.model})
                home = self.settings.user_home(run.identity.id)
                ready = await self.runtime.readiness(home, run.identity.email)
                if not ready.get("ready"):
                    raise AgentFailure("gemini_signin_required" if "Link" in str(ready.get("reason")) else "runtime_unavailable",
                                       str(ready.get("reason")))
                today = datetime.now().astimezone().date()  # the server's local date: on Gulf time UTC is still yesterday until 04:00
                request = AgentRequest(
                    run_id=run.id, user_id=run.identity.id, user_email=run.identity.email, user_home=home,
                    prompt=compose(run.question, self.history(run), run.kind, today,
                                   [{**a, "tables": table_index(Path(a["folder"]))}
                                    for a in self.store.conversation_attachments(run.conversation_id)], explore=run.explore),
                    question=run.question, kind=run.kind,  # type: ignore[arg-type]
                    history=self.history(run), internal_url=self.settings.internal_url,
                    run_token=run_token(self.settings.session_secret, run.id, run.identity.id, self.settings.run_timeout_s + 120))
                run.started = time.monotonic()
                await asyncio.wait_for(self.runtime.run(request, lambda k, p: self.emit(run, k, p), Bridge(self, run),
                                                        lambda: run.cancelled),
                                       timeout=self.settings.run_timeout_s + 30)
            await self._finish(run)
        except AgentFailure as failure:
            if failure.code == "empty_answer" and run.notes:  # Gemini's last message stands in, with a warning
                await self._finish(run)
            else:
                await self._fail(run, failure.code, failure.message, details=failure.details)
        except TimeoutError:
            await self._fail(run, "timeout", f"The run did not finish within {self.settings.run_timeout_s} seconds.",
                             details={"Time limit": f"{self.settings.run_timeout_s} s (WIZARD_RUN_TIMEOUT_S)"})
        except asyncio.CancelledError:
            await self._fail(run, "cancelled", "The run was cancelled.", status="cancelled")
        except Exception as error:  # noqa: BLE001 - every failure must surface as a clear run state, never a hung spinner
            log.exception("run %s failed", run.id)
            if self.settings.diagnostics:
                with contextlib.suppress(Exception):
                    await self.emit(run, "diagnostic", {"source": "wizard", "outcome": "internal_error",
                                                        "error": f"{type(error).__name__}: {error}",
                                                        "traceback": traceback.format_exc()[-6000:]})
            where = traceback.extract_tb(error.__traceback__)[-1:]
            await self._fail(run, "internal_error", "Wizard hit an internal error. The failure was logged.", details={
                "Exception": f"{type(error).__name__}: {error}"[:1000],
                **({"Where": f"{Path(where[0].filename).name}, line {where[0].lineno}, in {where[0].name}"} if where else {})})
        finally:
            self.active.pop(run.id, None)

    async def _fail(self, run: ActiveRun, code: str, message: str, status: str = "failed",
                    details: dict[str, str] | None = None) -> None:
        log.warning("run %s %s: %s %s %s", run.id, status, code, message, details or "")
        with contextlib.suppress(Exception):
            self.store.update_run(run.id, status=status, error_code=code, error_message=message, finished_at=now(),
                                  stats=json.dumps(run.stats))
            self._publish(run, "run_failed", {"code": code, "message": message, "status": status,
                                              "evidence_ids": run.evidence_ids,
                                              "details": self.failure_details(run, code, details or {})})

    def failure_details(self, run: ActiveRun, code: str, found: dict[str, str]) -> dict[str, str]:
        """What the run card's Error details shows: the runtime's account of the failure (Google's reason and words),
        then where the run had got to. Never the prompt, the answer or private reasoning; tokens are redacted."""
        details = {"Error code": code, **found}
        details.setdefault("Model", str(run.session.get("model") or self.runtime.model))
        details["Connection"] = self.runtime.label()
        if run.started:
            details["Ran for"] = minutes(time.monotonic() - run.started)
        if run.waits:
            details["Waited for Gemini"] = (f"{run.waits} time{'s' if run.waits != 1 else ''}, {minutes(run.waited_s)} in all "
                                            "(both models busy or rate-limited)")
        details["Tool calls"] = str(run.tool_calls)
        if run.last_tool:
            details["Last tool call"] = run.last_tool
        if run.last_status:
            details["Last status"] = run.last_status
        details["Run"] = run.id
        build = installed_build()
        if build.get("version") or build.get("commit"):
            details["Wizard build"] = " ".join(str(build[k])[:12] for k in ("version", "commit") if build.get(k))
        return {label: redact(str(value))[:2000] for label, value in details.items()}

    async def _finish(self, run: ActiveRun) -> None:
        answer = "".join(run.segment).strip()
        if not answer and run.notes:
            answer = run.notes.pop()
            run.warnings.append("Gemini finished without a separate final answer; its last message is shown.")
        if not answer:
            await self._fail(run, "empty_answer", "Gemini finished without an answer.",
                             details={"What Gemini sent back": "no text after its last step, and no earlier message"})
            return
        conversation_evidence = {e["id"]: e for e in self.store.evidence(run.conversation_id)}
        cited = [c for c in dict.fromkeys(CITATION.findall(answer))]
        unknown = [c for c in cited if c not in conversation_evidence]
        if unknown:
            run.warnings.append(f"The answer cites evidence that does not exist: {', '.join(unknown)}.")
        visuals = self.store.visuals(run.conversation_id, run.id)
        missing_visuals = [v for v in VISUAL.findall(answer) if v not in {x["id"] for x in visuals}]
        if missing_visuals:
            run.warnings.append(f"The answer refers to visuals that were not prepared: {', '.join(missing_visuals)}.")
        evidence_ids = list(dict.fromkeys([*run.evidence_ids, *[c for c in cited if c in conversation_evidence]]))
        evidence = [conversation_evidence[e] for e in evidence_ids]
        modes = sorted({e["data_mode"] for e in evidence}, key=lambda m: DATA_MODE_RANK.get(m, -1))
        data_mode = modes[0] if modes else None
        statuses = {c["overall"] for c in run.checks}
        check_status = "DISCREPANCY" if "DISCREPANCY" in statuses else "CHECKED" if "CHECKED" in statuses else "NOT_CHECKED"
        check_summary = run.checks[-1]["summary"] if run.checks else None
        report_id = new_id("rpt")
        created = now()
        timeline = [e for e in self.store.events(run.id) if e["type"] in ("tool_finished", "note", "warning", "check_result")]
        report = {
            "id": report_id, "run_id": run.id, "conversation_id": run.conversation_id, "user_id": run.identity.id,
            "user": {"name": run.identity.name, "role": run.identity.role}, "created_at": created,
            "question": run_title(run.kind, run.question), "kind": run.kind,
            "parent_run_id": run.parent_run_id, "answer": answer, "notes": run.notes, "visuals": visuals,
            "evidence": evidence, "uncited_evidence": [e for e in run.evidence_ids if e not in cited],
            "data_mode": data_mode, "data_modes": modes,
            "runtime": {"kind": self.runtime.kind, "label": self.runtime.label(), "model": run.session.get("model")
                        or self.runtime.model, "session_id": run.session.get("session_id")},
            "check": {"status": check_status, "summary": check_summary},
            "warnings": run.warnings, "stats": run.stats,
            "timeline": [{"type": e["type"], "payload": e["payload"]} for e in timeline],
        }
        self.store.save_report(report, self.settings.report_retention_days)
        self.store.update_run(run.id, status="succeeded", answer=answer, report_id=report_id, data_mode=data_mode,
                              check_status=check_status, check_summary=check_summary, finished_at=now(),
                              stats=json.dumps(run.stats))
        if run.kind == "check" and run.parent_run_id and run.checks:
            parent = self.store.run(run.identity.id, run.parent_run_id)
            if parent:
                self.store.update_run(parent["id"], check_status=check_status, check_summary=check_summary)
                if parent.get("report_id"):
                    self.store.update_report(parent["report_id"], check={"status": check_status, "summary": check_summary,
                                                                         "checked_by_run": run.id, "checked_at": created})
        self._publish(run, "run_finished", {"status": "succeeded", "report_id": report_id, "answer": answer,
                                            "data_mode": data_mode, "check_status": check_status,
                                            "check_summary": check_summary, "warnings": run.warnings,
                                            "evidence_ids": evidence_ids, "stats": run.stats})

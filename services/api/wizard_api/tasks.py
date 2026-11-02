"""Tasks (owner, 31 Oct 2026): instructions the Wizard team writes for Gemini, run from Settings → Tasks.

"From now on, everything is like pending tasks where you write it for Gemini to execute ... we push them and they stay
as tasks ... it would be really cool if we didn't need to update the app for the tasks to appear there ... The output of
the task is the GitHub repo." A task is one Markdown file in the Wizard repository's `tasks/` folder: flat front matter
(id, title, summary, added) and the instructions for Gemini. Wizard reads the folder from GitHub's API at runtime, the
route the update check uses on the work network, so a task pushed to the repository appears without an update. With
no network it shows the copy bundled with this version. A run is a Gemini run of kind `task` in a conversation of its
own; what it produces goes to the company's knowledge-base repository through the task tools (kb_tools.py).

The list is public instructions only: a task never carries company content, which lives in the knowledge base.

A task may ask for a folder or a file on this PC (owner, 1 Nov 2026: "a task that asks me for a folder, and I point it to
that folder, and it digests the whole thing"): front matter `input: folder` (or `file`, or `folder or file`) with an
`input_label` shown above the path box, and `every_file: true` when it goes through every file, which runs it in rounds
until each file is done (runs.py). Gemini reads the path only with the task-file tools (task_files.py).

A task may run again until it is done (owner, 2 Nov 2026, the task queue): front matter `repeat: until_done`, with
`max_runs` (default 5, at most 10). Each run ends its summary with `Left: <number>`; Wizard runs it again while that is
above 0 and the run changed something (runs.py). Tasks queued to run one after another: task_queue.py."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors.knowledge import front_matter, unquote
from wizard_connectors.paths import ROOT
from wizard_connectors.task_files import input_kind

from .attachments import OFFICE
from .config import Settings

LISTING = "https://api.github.com/repos/datap0nd/wizard/contents/tasks?ref=main"
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
MAX_RUNS = 5  # a task that repeats until done runs at most this many times, unless it says otherwise ...
MAX_RUNS_CAP = 10  # ... and never more than this
REFRESH_SECONDS = 300  # GitHub allows 60 unauthenticated requests an hour; an unchanged folder answers 304 for free


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    summary: str
    added: str
    body: str
    input: str | None = None  # folder | file | either: what the person chooses before it runs
    input_label: str = ""
    every_file: bool = False  # goes through every file of the folder, in rounds
    repeat: bool = False  # runs again while its last run says work is left and changed something
    max_runs: int = 1

    def work(self, path: Path | None = None) -> dict[str, Any]:
        """What a run of it carries (runs.py, prompting.py, the task-file tools). max_runs: the task repeats until done
        (a task that goes through every file already runs until each file is done, in rounds)."""
        every_file = self.every_file and bool(path)
        return {"id": self.id, "title": self.title, "body": self.body, "input": self.input,
                "path": str(path) if path else None, "chosen": ("folder" if path.is_dir() else "file") if path else None,
                "every_file": every_file, "max_runs": self.max_runs if self.repeat and not every_file else None}


def runs_allowed(text: str) -> int:
    """max_runs as written (a comment after it is ignored): MAX_RUNS when absent or not a number, at most MAX_RUNS_CAP."""
    found = re.match(r"\s*(\d{1,4})\b", text)
    return max(1, min(MAX_RUNS_CAP, int(found.group(1)))) if found else MAX_RUNS


def parse(text: str) -> Task | None:
    parsed = front_matter(text)
    if parsed is None:
        return None
    meta, body = parsed
    task_id = unquote(meta.get("id", ""))
    if not TASK_ID.match(task_id) or not body.strip():
        return None
    wanted = input_kind(unquote(meta.get("input", "")))
    label = unquote(meta.get("input_label", "")) or {"folder": "The folder", "file": "The file",
                                                      "either": "The folder or file"}.get(wanted or "", "")
    every_file = bool(wanted) and unquote(meta.get("every_file", "")).casefold() in ("true", "yes")
    repeat = unquote(meta.get("repeat", "").split("#")[0]).casefold() == "until_done" and not every_file
    return Task(task_id, unquote(meta.get("title", "")) or task_id, unquote(meta.get("summary", "")),
                unquote(meta.get("added", "")), body.strip(), wanted, label, every_file, repeat,
                runs_allowed(unquote(meta.get("max_runs", ""))) if repeat else 1)


TOOL_S = 150  # a task-file tool call answers within this (the Gemini CLI route gives a tool call 180 seconds)


class Documents:
    """The document converter for the task-file tools: each call runs scripts/wizard_docs.py in its own process,
    time-limited and one Office job at a time (the lock attached files use), as attachments.py does. A design read
    prints one line per deck as it goes, so the decks read before the time ran out are kept."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _lines(self, arguments: list[str], timeout: float) -> tuple[list[dict[str, Any]], str]:
        command = [sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), *arguments]
        with OFFICE:
            try:
                completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                           timeout=timeout)
                output, error = completed.stdout or "", completed.stderr or ""
            except subprocess.TimeoutExpired as expired:
                raw = expired.stdout or b""
                output = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                error = f"Office did not finish within {round(timeout)} seconds (a dialog may be open in Office)"
        found = []
        for line in output.splitlines():
            if line.startswith("{"):
                try:
                    found.append(json.loads(line))
                except ValueError:
                    continue
        return found, (error.strip().splitlines() or ["no output"])[-1][:300]

    def convert(self, source: Path, out: Path) -> dict[str, Any]:
        lines, error = self._lines(["convert", str(source), "--out", str(out), "--json", "--slide-images", "none",
                                    "--office", self.settings.attachment_office], min(self.settings.attachment_timeout_s, TOOL_S))
        return lines[-1] if lines else {"status": "failed", "note": error}

    def design(self, sources: list[Path]) -> list[dict[str, Any]]:
        office = "never" if self.settings.attachment_office == "never" else "auto"
        lines, _ = self._lines(["design", *map(str, sources), "--office", office],
                               min(self.settings.attachment_timeout_s * len(sources), TOOL_S))
        return lines

    def combine(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        from wizard_documents.design import combine
        return combine(profiles)


def _sorted(tasks: list[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: (t.added, t.id), reverse=True)  # newest first


def run_order(tasks: list[Task]) -> list[Task]:
    """The order a queue runs them in: oldest added first, then by id, so numbered tasks (kb-review-1 ... 7) run in turn."""
    return sorted(tasks, key=lambda t: (t.added, t.id))


class TaskBoard:
    """The tasks and, per task, the last run started from this PC."""

    def __init__(self, data_dir: Path, bundled: Path, proxy: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.folder = data_dir / "tasks"
        self.bundled = bundled
        self.proxy = proxy
        self.transport = transport
        self._lock = threading.Lock()

    # The list ----------------------------------------------------------------------------------------------------------
    def _read(self, name: str) -> dict[str, Any]:
        try:
            value = json.loads((self.folder / name).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, name: str, value: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self.folder / f"{name}.tmp"
        temporary.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.folder / name)

    def _client(self, url: str) -> httpx.Client:
        if self.transport is not None:
            return httpx.Client(transport=self.transport, timeout=30)
        route, _ = outbound.proxy_for(url, self.proxy)
        return httpx.Client(timeout=httpx.Timeout(30, connect=10), verify=outbound.ssl_context(), proxy=route,
                            trust_env=False)

    def refresh(self, force: bool = False) -> dict[str, Any]:
        """Read the tasks folder from GitHub when it changed; keep the last good copy when GitHub does not answer."""
        with self._lock:
            cache = self._read("cache.json")
            if not force and time.time() - float(cache.get("checked") or 0) < REFRESH_SECONDS:
                return cache
            files: dict[str, Any] = cache.get("files") or {}
            try:
                with self._client(LISTING) as client:
                    headers = {"User-Agent": "Wizard", "Accept": "application/vnd.github+json",
                               **({"If-None-Match": cache["etag"]} if cache.get("etag") else {})}
                    listing = client.get(LISTING, headers=headers)
                    if listing.status_code != 304:
                        listing.raise_for_status()
                        items = [i for i in listing.json() if isinstance(i, dict) and i.get("type") == "file"
                                 and str(i.get("name", "")).endswith(".md") and i.get("name") != "README.md"]
                        fresh = {}
                        for item in items:
                            name, sha = str(item["name"]), str(item.get("sha"))
                            if (files.get(name) or {}).get("sha") == sha:
                                fresh[name] = files[name]
                                continue
                            raw = client.get(str(item["url"]), headers={"User-Agent": "Wizard",
                                                                       "Accept": "application/vnd.github.raw+json"})
                            raw.raise_for_status()
                            fresh[name] = {"sha": sha, "text": raw.text}
                        files = fresh
                        cache["etag"] = listing.headers.get("etag")
                cache.update(files=files, checked=time.time(), source="github", message=None)
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                cache.update(checked=time.time(), message="the Wizard repository has no tasks folder" if status == 404
                             else f"GitHub answered {status}")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                cache.update(checked=time.time(), message=(outbound.explain(error, LISTING, self.proxy, windows=True)
                                                           if isinstance(error, httpx.TransportError) else str(error)))
            self._write("cache.json", cache)
            return cache

    def tasks(self, cache: dict[str, Any] | None = None) -> tuple[list[Task], str]:
        """GitHub's list when it has ever answered (a task removed there is gone), else the bundled one."""
        cache = self._read("cache.json") if cache is None else cache
        if cache.get("source") == "github":
            found = [parse(str(f.get("text") or "")) for f in (cache.get("files") or {}).values() if isinstance(f, dict)]
            return _sorted([t for t in found if t]), "github"
        texts = [p.read_text(encoding="utf-8") for p in sorted(self.bundled.glob("*.md")) if p.name != "README.md"] \
            if self.bundled.is_dir() else []
        return _sorted([t for t in (parse(text) for text in texts) if t]), "bundled"

    def task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks()[0] if t.id == task_id), None)

    # Runs ----------------------------------------------------------------------------------------------------------------
    def started(self, task_id: str, run_id: str, conversation_id: str, path: str | None = None, round_number: int = 1) -> None:
        """A run of the task began (each round of one that goes through every file is a run, and each run of one that
        repeats until done); the path is kept to fill in the path box next time."""
        with self._lock:
            state = self._read("state.json")
            entry: dict[str, Any] = {"run_id": run_id, "conversation_id": conversation_id,
                                     "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": round_number}
            if path:
                entry["path"] = path
            state[task_id] = entry
            self._write("state.json", state)

    def ended(self, task_id: str, run_id: str, outcome: str, message: str) -> None:
        """How a task's rounds ended (done, failed, stopped), in words, when that is more than its last run says."""
        with self._lock:
            state = self._read("state.json")
            entry = state.get(task_id)
            if isinstance(entry, dict) and entry.get("run_id") == run_id:
                entry.update(outcome=outcome, message=message)
                self._write("state.json", state)

    def runs(self) -> dict[str, dict[str, Any]]:
        return self._read("state.json")

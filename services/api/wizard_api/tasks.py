"""Tasks (owner, 31 Oct 2026): instructions the Wizard team writes for Gemini, run from Settings → Tasks.

"From now on, everything is like pending tasks where you write it for Gemini to execute ... we push them and they stay
as tasks ... it would be really cool if we didn't need to update the app for the tasks to appear there ... The output of
the task is the GitHub repo." A task is one Markdown file in the Wizard repository's `tasks/` folder: flat front matter
(id, title, summary, added) and the instructions for Gemini. Wizard reads the folder from GitHub's API at runtime, the
route the update check uses on the work network, so a task pushed to the repository appears without an update. With
no network it shows the copy bundled with this version. A run is a Gemini run of kind `task` in a conversation of its
own; what it produces goes to the company's knowledge-base repository through the task tools (kb_tools.py).

The list is public instructions only: a task never carries company content, which lives in the knowledge base."""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors.knowledge import front_matter, unquote

LISTING = "https://api.github.com/repos/datap0nd/wizard/contents/tasks?ref=main"
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
REFRESH_SECONDS = 300  # GitHub allows 60 unauthenticated requests an hour; an unchanged folder answers 304 for free


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    summary: str
    added: str
    body: str


def parse(text: str) -> Task | None:
    parsed = front_matter(text)
    if parsed is None:
        return None
    meta, body = parsed
    task_id = unquote(meta.get("id", ""))
    if not TASK_ID.match(task_id) or not body.strip():
        return None
    return Task(task_id, unquote(meta.get("title", "")) or task_id, unquote(meta.get("summary", "")),
                unquote(meta.get("added", "")), body.strip())


def _sorted(tasks: list[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: (t.added, t.id), reverse=True)  # newest first


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
    def started(self, task_id: str, run_id: str, conversation_id: str) -> None:
        with self._lock:
            state = self._read("state.json")
            state[task_id] = {"run_id": run_id, "conversation_id": conversation_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._write("state.json", state)

    def runs(self) -> dict[str, dict[str, Any]]:
        return self._read("state.json")

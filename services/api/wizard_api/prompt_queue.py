"""The prompt queue (owner, 4 Nov 2026): questions run one after another while the person is away.

"Create a new feature in settings: a prompt queuer. I will put in 20 prompts, delimited with ';' (allow the delimitation
to be custom in a dropdown with the most frequent ones). And I want it to once it finishes a prompt, goes to the next
one, so I can run overnight. If there's an error, a retry, up to 2 retries per prompt."

Settings → Prompt queue splits the text the person pastes by the separator they choose (`split`) and adds each prompt
at the end of their queue. Start runs the first one as a question in a new chat of its own, as if they had asked it, and
the next when it ends. A run that fails is tried again in the same chat, at most MAX_RETRIES times, after a short wait
(RETRY_WAITS_S); then the prompt is marked failed and the queue goes on. A failure no retry can mend (Gemini not signed
in, the quota used up: runs.CANNOT_RUN) stops the queue there, and Continue runs that prompt again. Nobody is waiting
while it runs, so Gemini is told so and is not offered wizard_ask_person (runs.py).

A queued question runs in a lane of its own (runs.PROMPTS_LANE), beside the person's own question, a task and a mapping
round. The queue is kept per person in the data folder (prompt_queues.json), so it outlives the service: a queue the
service left running is "interrupted" when it starts again, and Continue goes on from that prompt. While it runs, the PC
is kept awake and the desktop app does not restart its service (RunManager.busy)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wizard_connectors.entitlements import Identity
from wizard_connectors.tools.systems import SystemChoice

from .runs import CANNOT_RUN, Busy, RunManager
from .store import Store, now

log = logging.getLogger("wizard.prompt_queue")
QUEUE_FILE = "prompt_queues.json"
MAX_PROMPTS = 200       # in one queue
MAX_PROMPT_CHARS = 100_000  # one prompt, as a question asked in the app
MAX_RETRIES = 2         # after the first try: three tries in all
RETRY_WAITS_S = (60, 300)  # before the first retry and the second: Google's busy spells pass, a stuck portal resets
# The separators the panel offers, most used first; "custom" takes the person's own.
SEPARATORS: dict[str, str] = {"semicolon": ";", "newline": "\n", "blank_line": "\n\n", "pipe": "|", "dashes": "---"}
PENDING = ("waiting", "stopped", "interrupted")  # still to run: Start or Continue runs the first
FINAL = ("done", "failed", "skipped")


class QueueError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def split(text: str, separator: str, custom: str | None = None) -> list[str]:
    """The prompts in what the person pasted: cut at the separator, each trimmed, empty ones dropped. A line break is
    any line break (Windows' too); a blank line is a line holding nothing but spaces."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if separator == "custom":
        mark = (custom or "").replace("\\n", "\n")
        if not mark.strip(" "):
            raise QueueError("Type the separator to cut the prompts at.")
        parts = text.split(mark)
    elif separator == "newline":
        parts = text.split("\n")
    elif separator == "blank_line":
        parts = re.split(r"\n[ \t]*\n", text)
    elif separator in SEPARATORS:
        parts = text.split(SEPARATORS[separator])
    else:
        raise QueueError(f"Unknown separator '{separator}'.")
    return [p.strip() for p in parts if p.strip()]


def empty() -> dict[str, Any]:
    return {"state": "empty", "items": [], "message": None, "started_at": None, "finished_at": None, "next": 1}


def short(prompt: str, size: int = 60) -> str:
    line = " ".join(prompt.split())
    return f"“{line[:size].rstrip()}…”" if len(line) > size else f"“{line}”"


def clock(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%H:%M")
    except ValueError:
        return stamp


class PromptQueues:
    """Every person's prompt queue, kept in <data>/prompt_queues.json. Runs start and end on the event loop's thread, and
    so do the queue's changes (its endpoints are async), so a queue is never changed from two threads."""

    def __init__(self, folder: Path, manager: RunManager, store: Store,
                 choose: Callable[[Identity], SystemChoice | None] | None = None):
        self.manager, self.store = manager, store
        self.choose = choose or (lambda identity: None)  # the systems a queued question may use: Auto
        self.path = folder / QUEUE_FILE
        self._lock = threading.Lock()
        self._awake: set[str] = set()
        self._timers: dict[str, asyncio.Task[None]] = {}  # a person's queue waiting to retry a prompt
        self.queues: dict[str, dict[str, Any]] = self._load()
        interrupted = [user for user, queue in self.queues.items() if queue.get("state") == "running"]
        for user in interrupted:
            self._interrupt(self.queues[user], "Wizard restarted")
        if interrupted:
            log.warning("prompt queue interrupted by a restart for %d person(s)", len(interrupted))
            self._save()
        manager.on_prompt_end = self.run_ended
        manager.prompt_queue = self

    # Storage -------------------------------------------------------------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): {**empty(), **v} for k, v in value.items() if isinstance(v, dict)} if isinstance(value, dict) else {}

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.queues, indent=1, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)

    def queue(self, user_id: str) -> dict[str, Any]:
        return self.queues.setdefault(user_id, empty())

    def running(self) -> bool:
        return any(queue.get("state") == "running" for queue in self.queues.values())

    def _hold(self, user_id: str) -> None:
        if user_id not in self._awake:
            self._awake.add(user_id)
            self.manager.awake.__enter__()

    def _release(self, user_id: str) -> None:
        if user_id in self._awake:
            self._awake.discard(user_id)
            self.manager.awake.__exit__(None, None, None)
        timer = self._timers.pop(user_id, None)
        try:
            current = asyncio.current_task()
        except RuntimeError:  # no event loop running: nothing waits
            current = None
        if timer is not None and not timer.done() and timer is not current:
            timer.cancel()

    # What the page shows ---------------------------------------------------------------------------------------------------
    def view(self, user_id: str) -> dict[str, Any]:
        queue = self.queue(user_id)
        items = [dict(i) for i in queue["items"]]
        current = next((i for i in items if i["state"] in ("running", "retry_wait")), None) or (
            next((i for i in items if i["state"] in PENDING), None) if queue["state"] not in ("ready", "empty") else None)
        return {"state": queue["state"], "items": items, "message": queue.get("message"), "total": len(items),
                "done": sum(1 for i in items if i["state"] == "done"),
                "failed": sum(1 for i in items if i["state"] == "failed"),
                "current": current["key"] if current else None,
                "position": items.index(current) + 1 if current else None,
                "started_at": queue.get("started_at"), "finished_at": queue.get("finished_at"),
                "max_retries": MAX_RETRIES, "max_prompts": MAX_PROMPTS}

    # Filling it ------------------------------------------------------------------------------------------------------------
    def _reset(self, queue: dict[str, Any]) -> None:
        counter = queue.get("next") or 1
        queue.clear()
        queue.update({**empty(), "next": counter})

    def add(self, user_id: str, text: str, separator: str, custom: str | None = None) -> dict[str, Any]:
        """The prompts in the text, at the end of the queue, also while it runs. A finished queue starts afresh."""
        prompts = split(text, separator, custom)
        if not prompts:
            raise QueueError("There is no prompt in that text: paste them, cut by the separator you chose.")
        long = next((n for n, p in enumerate(prompts, 1) if len(p) > MAX_PROMPT_CHARS), None)
        if long is not None:
            raise QueueError(f"Prompt {long} is longer than {MAX_PROMPT_CHARS:,} characters. Is the separator right?")
        queue = self.queue(user_id)
        if queue["state"] == "done":  # its outcome was seen: these start a new queue
            self._reset(queue)
        if len(queue["items"]) + len(prompts) > MAX_PROMPTS:
            raise QueueError(f"The queue holds at most {MAX_PROMPTS} prompts; it has {len(queue['items'])} and these are "
                             f"{len(prompts)}.")
        for prompt in prompts:
            key = f"p{queue.get('next') or 1}"
            queue["next"] = int(queue.get("next") or 1) + 1
            queue["items"].append({"key": key, "prompt": prompt, "state": "waiting", "attempts": 0,
                                   "conversation_id": None, "run_id": None, "message": None, "started_at": None,
                                   "finished_at": None, "retry_at": None})
        if queue["state"] == "empty":
            queue["state"] = "ready"
        self.store.audit(user_id, "prompts:queue_add", detail={"prompts": len(prompts), "separator": separator})
        self._save()
        return self.view(user_id)

    def _item(self, queue: dict[str, Any], key: str) -> dict[str, Any]:
        item = next((i for i in queue["items"] if i["key"] == key), None)
        if item is None:
            raise QueueError("That prompt is no longer in the queue.", 404)
        return item

    def move(self, user_id: str, key: str, by: int) -> dict[str, Any]:
        """Up (-1) or down (1), past another prompt still to run; never past one that ran or runs."""
        queue = self.queue(user_id)
        items = queue["items"]
        index = items.index(self._item(queue, key))
        other = index + by
        if not 0 <= other < len(items) or items[index]["state"] not in PENDING or items[other]["state"] not in PENDING:
            raise QueueError("A prompt moves only past another one still to run.", 409)
        items[index], items[other] = items[other], items[index]
        self._save()
        return self.view(user_id)

    def remove(self, user_id: str, key: str) -> dict[str, Any]:
        queue = self.queue(user_id)
        item = self._item(queue, key)
        if item["state"] not in (*PENDING, *FINAL):
            raise QueueError("A prompt that runs, or waits to be tried again, stays: stop the queue first.", 409)
        queue["items"].remove(item)
        if not queue["items"]:
            self._reset(queue)
        elif queue["state"] not in ("running", "empty") and not any(i["state"] in PENDING for i in queue["items"]):
            queue.update(state="done", message=self._summary(queue))
        self._save()
        return self.view(user_id)

    def retry_failed(self, user_id: str) -> dict[str, Any]:
        """The prompts that failed every try go back to the queue, in their place, with their tries again."""
        queue = self.queue(user_id)
        failed = [i for i in queue["items"] if i["state"] == "failed"]
        if not failed:
            raise QueueError("No prompt failed.")
        for item in failed:
            item.update(state="waiting", attempts=0, message=None, finished_at=None, retry_at=None)
        if queue["state"] == "done":
            queue.update(state="stopped", message=f"{len(failed)} failed prompt(s) back in the queue: press Continue.")
        self._save()
        return self.view(user_id)

    def clear(self, user_id: str) -> dict[str, Any]:
        queue = self.queue(user_id)
        if queue["state"] == "running":
            raise QueueError("Stop the queue before you clear it.", 409)
        self._reset(queue)
        self._save()
        return self.view(user_id)

    # Running it -------------------------------------------------------------------------------------------------------------
    async def start(self, identity: Identity) -> dict[str, Any]:
        """Start, or Continue after a stop, a failure Wizard could not retry, or a restart: from the first prompt still to
        run."""
        queue = self.queue(identity.id)
        if queue["state"] == "running":
            raise QueueError("The queue is already running.", 409)
        if not any(i["state"] in PENDING for i in queue["items"]):
            raise QueueError("The queue has no prompt left to run. Add some first.")
        continuing = queue["state"] in ("failed", "stopped", "interrupted") and queue.get("started_at")
        queue.update(state="running", message=None, finished_at=None, started_at=queue["started_at"] if continuing else now())
        self._hold(identity.id)
        self.store.audit(identity.id, "prompts:queue_start",
                         detail={"prompts": sum(1 for i in queue["items"] if i["state"] in PENDING)})
        await self._next(identity, queue)
        return self.view(identity.id)

    async def _next(self, identity: Identity, queue: dict[str, Any]) -> None:
        """Run the first prompt still to run, or finish the queue when none is left."""
        try:
            while queue["state"] == "running":
                item = next((i for i in queue["items"] if i["state"] in PENDING), None)
                if item is None:
                    queue.update(state="done", message=self._summary(queue), finished_at=now())
                    break
                if self._launch(identity, queue, item):
                    break
        except Exception:  # noqa: BLE001 - a queue must end in a state the person sees, never stay "running"
            log.exception("prompt queue for %s", identity.id)
            if queue["state"] == "running":
                queue.update(state="failed", message="Wizard could not start the next prompt: press Continue.",
                             finished_at=now())
        if queue["state"] != "running":
            self._release(identity.id)
        self._save()

    def _launch(self, identity: Identity, queue: dict[str, Any], item: dict[str, Any]) -> bool:
        """Ask one prompt: in a new chat the first time, in its own chat again on a retry. False: it could not start, and
        the queue goes on to the next."""
        conversation_id = item.get("conversation_id")
        if not conversation_id or not self.store.conversation(identity.id, conversation_id):
            conversation_id = self.store.create_conversation(identity.id)
        try:
            row = self.manager.start(identity, conversation_id, item["prompt"], choice=self.choose(identity), queued=True)
        except Busy as busy:
            item.update(state="failed", conversation_id=conversation_id, message=f"It could not start: {busy}",
                        finished_at=now())
            return False
        item.update(state="running", conversation_id=conversation_id, run_id=row["id"], started_at=now(), finished_at=None,
                    retry_at=None, attempts=int(item.get("attempts") or 0) + 1)
        self.store.audit(identity.id, "prompts:run", run_id=row["id"], detail={"queue": item["key"], "try": item["attempts"]})
        log.info("prompt queue for %s: %s, try %d", identity.id, item["key"], item["attempts"])
        return True

    async def run_ended(self, identity: Identity, row: dict[str, Any]) -> None:
        """A queued question ended (RunManager.on_prompt_end). Succeeded: the next. Failed: again after a wait, up to
        MAX_RETRIES times, then the next. Cancelled: the queue was stopped, the person stopped this one (the next), or the
        service is going down."""
        queue = self.queues.get(identity.id)
        item = next((i for i in (queue or {}).get("items", []) if i.get("run_id") == row.get("id")
                     and i["state"] == "running"), None)
        if queue is None or item is None:
            return
        status, code = str(row.get("status") or "failed"), str(row.get("error_code") or "")
        reason = str(row.get("error_message") or "the run failed.")
        if status == "cancelled" and self.manager.closing:
            if queue["state"] == "running":
                self._interrupt(queue, "Wizard restarted")
                self._release(identity.id)
            self._save()
            return
        if queue["state"] != "running":  # Stop: this prompt runs again on Continue, with the tries it had left
            item.update(state="stopped", message="Stopped with the queue.", finished_at=now(),
                        attempts=max(0, int(item.get("attempts") or 1) - 1))
            self._save()
            return
        if status == "succeeded":
            item.update(state="done", message=None, finished_at=now())
        elif status == "cancelled":
            item.update(state="skipped", message="You stopped it in its chat; the queue went on.", finished_at=now())
        elif code in CANNOT_RUN:  # every prompt would fail the same way: the queue waits for the person
            item.update(state="waiting", message=f"Not run: {reason}", finished_at=now(),
                        attempts=max(0, int(item.get("attempts") or 1) - 1))
            queue.update(state="failed", finished_at=now(),
                         message=f"Stopped at {short(item['prompt'])}: {reason} Fix it, then press Continue.")
            self._release(identity.id)
            self._save()
            return
        elif int(item.get("attempts") or 1) <= MAX_RETRIES:
            retry = int(item["attempts"])
            wait = RETRY_WAITS_S[min(retry, len(RETRY_WAITS_S)) - 1]
            at = (datetime.now(UTC) + timedelta(seconds=wait)).isoformat()
            item.update(state="retry_wait", retry_at=at, finished_at=now(),
                        message=f"Failed: {reason} Retry {retry} of {MAX_RETRIES} at {clock(at)}.")
            self._save()
            self._timers[identity.id] = asyncio.get_running_loop().create_task(self._retry(identity, item["key"], wait))
            return
        else:
            item.update(state="failed", finished_at=now(), message=f"Failed {item['attempts']} times. Last: {reason}")
        log.info("prompt queue for %s: %s %s", identity.id, item["key"], item["state"])
        await self._next(identity, queue)

    async def _retry(self, identity: Identity, key: str, wait: float) -> None:
        await asyncio.sleep(wait)
        queue = self.queues.get(identity.id)
        item = next((i for i in (queue or {}).get("items", []) if i["key"] == key and i["state"] == "retry_wait"), None)
        if queue is None or item is None or queue["state"] != "running":
            return
        try:
            if not self._launch(identity, queue, item):
                await self._next(identity, queue)
                return
        except Exception:  # noqa: BLE001 - a queue must end in a state the person sees
            log.exception("prompt queue retry for %s", identity.id)
            item.update(state="failed", message="Wizard could not try it again.", finished_at=now())
            await self._next(identity, queue)
            return
        self._save()

    def stop(self, identity: Identity) -> dict[str, Any]:
        """Stop the queue and the question it is running; a prompt waiting to be tried again waits for Continue."""
        queue = self.queue(identity.id)
        if queue["state"] != "running":
            raise QueueError("The queue is not running.", 409)
        item = next((i for i in queue["items"] if i["state"] in ("running", "retry_wait")), None)
        queue.update(state="stopped", finished_at=now(),
                     message=f"You stopped the queue at {short(item['prompt'])}." if item else "You stopped the queue.")
        self._release(identity.id)
        if item is not None and item["state"] == "retry_wait":
            item.update(state="stopped", retry_at=None, message="Stopped with the queue, before its next try.")
        elif item is not None and not self.manager.cancel(identity.id, str(item.get("run_id"))):
            item.update(state="stopped", message="Stopped with the queue.", finished_at=now(),
                        attempts=max(0, int(item.get("attempts") or 1) - 1))
        self.store.audit(identity.id, "prompts:queue_stop", detail={"prompt": item["key"] if item else None})
        self._save()
        return self.view(identity.id)

    def _interrupt(self, queue: dict[str, Any], why: str) -> None:
        item = next((i for i in queue["items"] if i["state"] in ("running", "retry_wait")), None)
        if item is not None:
            item.update(state="interrupted", message=f"{why} before it finished.", finished_at=now(), retry_at=None,
                        attempts=max(0, int(item.get("attempts") or 1) - (1 if item["state"] == "running" else 0)))
        pending = item or next((i for i in queue["items"] if i["state"] in PENDING), None)
        queue.update(state="interrupted", finished_at=now(),
                     message=f"Interrupted at {short(pending['prompt'])}: {why} before it finished. Press Continue to "
                             "go on." if pending else f"Interrupted: {why}.")

    def _summary(self, queue: dict[str, Any]) -> str:
        items = queue["items"]
        done = sum(1 for i in items if i["state"] == "done")
        failed = sum(1 for i in items if i["state"] == "failed")
        skipped = sum(1 for i in items if i["state"] == "skipped")
        words = [f"{done} of {len(items)} prompt{'s' if len(items) != 1 else ''} answered"]
        if failed:
            words.append(f"{failed} failed after {MAX_RETRIES + 1} tries")
        if skipped:
            words.append(f"{skipped} stopped by you")
        return ", ".join(words) + "."

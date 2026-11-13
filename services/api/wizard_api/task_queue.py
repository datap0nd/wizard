"""The task queue (owner, 2 Nov 2026): tasks run one after another, the next only when the one before succeeded.

"I need something new, a task queuer. It should allow me to run tasks in a sequence. A 'run all tasks' button, where I
can run and it goes from one to another (only when all of them succeeded)." And: "allow me to choose which ones I can
run on a batch sequence, if I can tick like 5 of them and click run selected tasks ... so I can go to lunch and leave
them running."

Settings → Tasks fills a person's queue (Run all, Run selected, or Add to queue on one task), in run order: oldest
`added` first, then id (tasks.run_order). The person reorders it and presses Start. Each task runs as a single Run
does (RunManager.start_task: once, in rounds through every file, or again until done); when it ends done, the next
starts. A task that fails or is stopped stops the queue there, and Continue runs it again and goes on. One task at a
time per person, as before: the queue is the task lane's only user while it runs.

The queue is kept per person in the data folder (tasks/queues.json), so it outlives the service: a queue the service
left running is "interrupted" when it starts again, and Continue goes on from that task. While a queue runs the PC is
kept awake (awake.py) and the desktop app does not restart its service (RunManager.busy)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from wizard_connectors.entitlements import Identity
from wizard_connectors.task_files import TaskFiles, TaskFolderError, check_path

from .runs import LANES, Busy, RunManager
from .store import Store, now
from .tasks import Task, TaskBoard, run_order

log = logging.getLogger("wizard.task_queue")
QUEUE_FILE = "queues.json"
PENDING = ("waiting", "failed", "stopped", "interrupted")  # an item still to run (Start or Continue runs the first)
MAX_ITEMS = 100


class QueueError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def checked_path(task: Task, text: str, task_files: TaskFiles | None) -> Path:
    """The folder or file a task asks for, checked as a single Run checks it: it exists, is the kind asked for, and
    holds files Wizard reads."""
    if task_files is None:
        raise QueueError("This Wizard cannot read folders for tasks.")
    try:
        chosen = check_path(text or "", task.input or "folder")
        files, _ = task_files.listing(chosen, True)
    except TaskFolderError as error:
        raise QueueError(error.message) from None
    if not files:
        raise QueueError("Wizard found no PowerPoint, Word, Excel, email or text files there.")
    return chosen


def empty() -> dict[str, Any]:
    return {"state": "empty", "items": [], "message": None, "started_at": None, "finished_at": None, "selected": [],
            "left_out": [], "next": 1}


def quoted(title: str) -> str:
    return f"“{title}”"


class TaskQueues:
    """Every person's queue, kept in <data>/tasks/queues.json. Runs start and end on the event loop's thread, and so do
    the queue's changes (its endpoints are async; a path is checked in a worker thread first), so a queue is never
    changed from two threads, and the PC's keep-awake request is made and released on the thread runs use."""

    def __init__(self, board: TaskBoard, manager: RunManager, store: Store, task_files: TaskFiles | None):
        self.board, self.manager, self.store, self.task_files = board, manager, store, task_files
        self.path = board.folder / QUEUE_FILE
        self._lock = threading.Lock()
        self._awake: set[str] = set()  # people whose running queue holds the PC awake
        self.queues: dict[str, dict[str, Any]] = self._load()
        interrupted = [user for user, queue in self.queues.items() if queue.get("state") == "running"]
        for user in interrupted:
            self._interrupt(self.queues[user], "Wizard restarted")
        if interrupted:
            log.warning("task queue interrupted by a restart for %d person(s)", len(interrupted))
            self._save()
        manager.on_task_end = self.task_ended
        manager.task_queue = self

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

    # Keeping the PC awake while a queue runs, between its tasks too ---------------------------------------------------------
    def _hold(self, user_id: str) -> None:
        if user_id not in self._awake:
            self._awake.add(user_id)
            self.manager.awake.__enter__()

    def _release(self, user_id: str) -> None:
        if user_id in self._awake:
            self._awake.discard(user_id)
            self.manager.awake.__exit__(None, None, None)

    # What the page shows ---------------------------------------------------------------------------------------------------
    def view(self, user_id: str) -> dict[str, Any]:
        queue = self.queue(user_id)
        rounds = self.manager.task_rounds.get(user_id)
        items = []
        for item in queue["items"]:
            shown = dict(item)
            if (item["state"] == "running" and rounds is not None and rounds.state == "running"
                    and rounds.conversation_id == item.get("conversation_id")):
                shown["message"] = rounds.message  # Round 3: 40 of 300 files done / Run 2 of up to 5
            items.append(shown)
        current = next((i for i in items if i["state"] == "running"), None) or (
            next((i for i in items if i["state"] in PENDING), None) if queue["state"] not in ("ready", "empty") else None)
        return {"state": queue["state"], "items": items, "message": queue.get("message"),
                "total": len(items), "done": sum(1 for i in items if i["state"] == "done"),
                "current": current["key"] if current else None,
                "position": items.index(current) + 1 if current else None,
                "selected": list(queue.get("selected") or []), "left_out": list(queue.get("left_out") or []),
                "started_at": queue.get("started_at"), "finished_at": queue.get("finished_at")}

    # Filling it ------------------------------------------------------------------------------------------------------------
    def _item(self, queue: dict[str, Any], task: Task, path: Path | None) -> dict[str, Any]:
        key = f"q{queue.get('next') or 1}"
        queue["next"] = int(queue.get("next") or 1) + 1
        return {"key": key, "id": task.id, "title": task.title, "path": str(path) if path else None, "state": "waiting",
                "conversation_id": None, "run_id": None, "message": None, "started_at": None, "finished_at": None}

    def _reset(self, queue: dict[str, Any]) -> None:
        selected, counter = queue.get("selected") or [], queue.get("next") or 1
        queue.clear()
        queue.update({**empty(), "selected": selected, "next": counter})

    async def fill(self, user_id: str, ids: list[str] | None, paths: dict[str, str]) -> dict[str, Any]:
        """Run all (ids None) or Run selected: the queue becomes these tasks in run order. A task that asks for a path is
        queued with the path the person typed for it, checked as a single Run checks it; one with no path, or one that
        does not pass, is left out and said."""
        if self.queue(user_id)["state"] == "running":
            raise QueueError("The queue is running. Stop it first, or add a task to it.", 409)
        if ids is not None and not ids:
            raise QueueError("Tick the tasks to run first.")
        tasks = run_order([t for t in self.board.tasks() if ids is None or t.id in ids])
        if not tasks:
            raise QueueError("There are no tasks to queue." if ids is None else "None of the ticked tasks is in the list now.")
        chosen: list[tuple[Task, Path | None]] = []
        left_out: list[dict[str, str]] = []
        for task in tasks:
            path: Path | None = None
            if task.input:
                text = (paths.get(task.id) or "").strip()
                if not text:
                    left_out.append({"id": task.id, "title": task.title,
                                     "reason": f"it asks for a {'file' if task.input == 'file' else 'folder'}: type its "
                                               "path in its box, then add it to the queue"})
                    continue
                try:
                    path = await asyncio.to_thread(self._ready_path, task, text)
                except QueueError as error:
                    left_out.append({"id": task.id, "title": task.title, "reason": error.message})
                    continue
            chosen.append((task, path))
        queue = self.queue(user_id)
        if queue["state"] == "running":  # started while the paths were checked
            raise QueueError("The queue is running. Stop it first, or add a task to it.", 409)
        self._reset(queue)
        queue["items"] = [self._item(queue, task, path) for task, path in chosen]
        queue.update(left_out=left_out, state="ready" if queue["items"] else "empty")
        self._save()
        return self.view(user_id)

    def _ready_path(self, task: Task, text: str) -> Path:
        chosen = checked_path(task, text, self.task_files)
        if task.every_file and self.task_files is not None and self.task_files.counts(task.id, chosen)["left"] == 0:
            raise QueueError("Every file there is already done. Press Run again on the task to start over.")
        return chosen

    async def add(self, user_id: str, task_id: str, path_text: str | None) -> dict[str, Any]:
        """Add one task at the end of the queue, also while it runs."""
        task = self.board.task(task_id)
        if task is None:
            raise QueueError("No such task.", 404)
        path = await asyncio.to_thread(self._ready_path, task, path_text or "") if task.input else None
        queue = self.queue(user_id)
        if any(i["id"] == task.id and i["state"] in ("waiting", "running") for i in queue["items"]):
            raise QueueError(f"{quoted(task.title)} is already in the queue.", 409)
        if len(queue["items"]) >= MAX_ITEMS:
            raise QueueError(f"The queue holds at most {MAX_ITEMS} tasks.")
        if queue["state"] == "done":  # a finished queue's result was seen: this starts a new one
            self._reset(queue)
        queue["items"].append(self._item(queue, task, path))
        if queue["state"] == "empty":
            queue["state"] = "ready"
        queue["left_out"] = [o for o in queue.get("left_out") or [] if o.get("id") != task.id]
        self._save()
        return self.view(user_id)

    def move(self, user_id: str, key: str, by: int) -> dict[str, Any]:
        """Up (-1) or down (1), past another task still to run; never past one that ran or runs."""
        queue = self.queue(user_id)
        items = queue["items"]
        index = next((n for n, i in enumerate(items) if i["key"] == key), None)
        if index is None:
            raise QueueError("That task is no longer in the queue.", 404)
        other = index + by
        if not 0 <= other < len(items) or items[index]["state"] not in PENDING or items[other]["state"] not in PENDING:
            raise QueueError("A task moves only past another one still to run.", 409)
        items[index], items[other] = items[other], items[index]
        self._save()
        return self.view(user_id)

    def remove(self, user_id: str, key: str) -> dict[str, Any]:
        queue = self.queue(user_id)
        item = next((i for i in queue["items"] if i["key"] == key), None)
        if item is None:
            raise QueueError("That task is no longer in the queue.", 404)
        if item["state"] not in PENDING:
            raise QueueError("Only a task still to run leaves the queue; Clear empties it.", 409)
        queue["items"].remove(item)
        if not queue["items"]:
            self._reset(queue)
        elif queue["state"] != "running" and not any(i["state"] in PENDING for i in queue["items"]):
            queue["state"], queue["message"] = "done", self._all_done(queue)
        self._save()
        return self.view(user_id)

    def select(self, user_id: str, ids: list[str]) -> dict[str, Any]:
        """The tasks ticked for Run selected, kept until the queue starts."""
        self.queue(user_id)["selected"] = list(dict.fromkeys(ids))
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
        """Start, or Continue after a failure, a stop or a restart: from the first task still to run."""
        queue = self.queue(identity.id)
        if queue["state"] == "running":
            raise QueueError("The queue is already running.", 409)
        if not any(i["state"] in PENDING for i in queue["items"]):
            raise QueueError("The queue has no task left to run. Add one, or press Run all or Run selected.")
        rounds = self.manager.task_rounds.get(identity.id)
        if (any(r.identity.id == identity.id and r.kind == "task" for r in self.manager.active.values())
                or (rounds is not None and rounds.state == "running")):
            raise QueueError(LANES["task"], 429)
        continuing = queue["state"] in ("failed", "stopped", "interrupted") and queue.get("started_at")
        queue.update(state="running", message=None, finished_at=None, selected=[],
                     started_at=queue["started_at"] if continuing else now())
        self._hold(identity.id)
        self.store.audit(identity.id, "tasks:queue_start", detail={"tasks": [i["id"] for i in queue["items"]
                                                                              if i["state"] in PENDING]})
        await self._next(identity, queue)
        return self.view(identity.id)

    async def _next(self, identity: Identity, queue: dict[str, Any]) -> None:
        """Start the first task still to run, or finish the queue when none is left."""
        try:
            while queue["state"] == "running":
                item = next((i for i in queue["items"] if i["state"] in PENDING), None)
                if item is None:
                    queue.update(state="done", message=self._all_done(queue), finished_at=now())
                    break
                if await self._launch(identity, queue, item):
                    break
        except Exception:  # noqa: BLE001 - a queue must end in a state the person sees, never stay "running"
            log.exception("task queue for %s", identity.id)
            if queue["state"] == "running":
                queue.update(state="failed", message="Wizard could not start the next task: press Continue.",
                             finished_at=now())
        if queue["state"] != "running":
            self._release(identity.id)
        self._save()

    async def _launch(self, identity: Identity, queue: dict[str, Any], item: dict[str, Any]) -> bool:
        """Start one item. False: it needed no run (every file already done), so the queue goes on to the next."""
        item.update(message=None, finished_at=None, conversation_id=None, run_id=None)
        task = self.board.task(item["id"])
        if task is None:
            return self._failed(queue, item, "it is no longer in the task list: remove it from the queue, then press Continue.")
        path: Path | None = None
        if task.input:
            try:
                path = await asyncio.to_thread(checked_path, task, item.get("path") or "", self.task_files)
            except QueueError as error:
                return self._failed(queue, item, error.message)
            if task.every_file and self.task_files is not None and (
                    await asyncio.to_thread(self.task_files.counts, task.id, path))["left"] == 0:
                item.update(state="done", message="Every file there was already done.", finished_at=now())
                return False
        if queue["state"] != "running":  # Stop was pressed while the path was checked
            return True
        conversation_id = self.store.create_conversation(identity.id, f"Task: {task.title}"[:80])
        try:
            row = self.manager.start_task(identity, conversation_id, task.work(path))
        except Busy as busy:
            return self._failed(queue, item, f"it could not start: {busy}")
        except Exception as error:  # noqa: BLE001 - said in the queue; the log has the details
            log.exception("task queue for %s: %s did not start", identity.id, task.id)
            return self._failed(queue, item, f"it could not start: {error}")
        item.update(state="running", conversation_id=conversation_id, run_id=row["id"], started_at=now(), title=task.title)
        self.store.audit(identity.id, "tasks:run", run_id=row["id"], detail={"task": task.id, "path_chosen": bool(path),
                                                                             "queue": item["key"]})
        log.info("task queue for %s: started %s (%s)", identity.id, task.id, item["key"])
        return True

    def _failed(self, queue: dict[str, Any], item: dict[str, Any], reason: str) -> bool:
        item.update(state="failed", message=reason[:1].upper() + reason[1:], finished_at=now())
        queue.update(state="failed", message=f"Stopped at {quoted(item['title'])}: {reason}", finished_at=now())
        return True

    def _all_done(self, queue: dict[str, Any]) -> str:
        count = len(queue["items"])
        return f"All {count} task{'s' if count != 1 else ''} succeeded."

    async def task_ended(self, identity: Identity, task_id: str, conversation_id: str, outcome: str, message: str) -> None:
        """A task ended (RunManager.on_task_end): the next one starts when it is done; otherwise the queue stops there."""
        queue = self.queues.get(identity.id)
        item = next((i for i in (queue or {}).get("items", []) if i.get("conversation_id") == conversation_id
                     and i["id"] == task_id and i["state"] == "running"), None)
        if queue is None or item is None:
            return
        if self.manager.closing and queue["state"] == "running":  # the service is going down: the run was cut off
            self._interrupt(queue, "Wizard restarted")
            self._release(identity.id)
            self._save()
            return
        item.update(state=outcome if outcome in ("done", "failed", "stopped") else "failed", message=message or None,
                    finished_at=now())
        log.info("task queue for %s: %s %s", identity.id, task_id, outcome)
        if queue["state"] != "running":  # Stop already said where the queue stopped
            self._save()
            return
        if item["state"] == "done":
            await self._next(identity, queue)
            return
        why = message or ("its run failed." if item["state"] == "failed" else "its run was stopped.")
        queue.update(state=item["state"], finished_at=now(),
                     message=f"Stopped at {quoted(item['title'])}, which " + (
                         f"failed: {why}" if item["state"] == "failed" else f"was stopped: {why}"))
        self._release(identity.id)
        self._save()

    def stop(self, identity: Identity) -> dict[str, Any]:
        """Stop the queue and the task it is running."""
        queue = self.queue(identity.id)
        if queue["state"] != "running":
            raise QueueError("The queue is not running.", 409)
        item = next((i for i in queue["items"] if i["state"] == "running"), None)
        queue.update(state="stopped", finished_at=now(),
                     message=f"You stopped the queue at {quoted(item['title'])}." if item else "You stopped the queue.")
        self._release(identity.id)
        if item is not None and not self.manager.stop_task(identity.id, str(item.get("conversation_id"))):
            item.update(state="stopped", message="Stopped by you.", finished_at=now())
        self.store.audit(identity.id, "tasks:queue_stop", detail={"task": item["id"] if item else None})
        self._save()
        return self.view(identity.id)

    def _interrupt(self, queue: dict[str, Any], why: str) -> None:
        item = next((i for i in queue["items"] if i["state"] == "running"), None)
        if item is not None:
            item.update(state="interrupted", message=f"{why} before it finished.", finished_at=now())
        title = item["title"] if item else next((i["title"] for i in queue["items"] if i["state"] in PENDING), None)
        queue.update(state="interrupted", finished_at=now(),
                     message=f"Interrupted at {quoted(title)}: {why} before it finished. Press Continue to run it again "
                             "and go on." if title else f"Interrupted: {why}.")

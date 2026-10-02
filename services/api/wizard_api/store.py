"""SQLite store for development and the restricted pilot: users, conversations, runs, run events, evidence, visuals,
checks, dated reports, Gemini account links, audit log and evaluation feedback.

SQLite is the development default, not an approved production database (Step 02/15 decide with IT). All reads are
scoped by user id; there is no query that returns another user's conversation, run, evidence or report."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT, name TEXT, role TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT, created_at TEXT,
  updated_at TEXT, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS conversations_user ON conversations(user_id, updated_at);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, user_id TEXT NOT NULL, kind TEXT,
  question TEXT, status TEXT, runtime TEXT, runtime_label TEXT, model TEXT, session_id TEXT, data_mode TEXT,
  check_status TEXT, check_summary TEXT, answer TEXT, report_id TEXT, error_code TEXT, error_message TEXT,
  stats TEXT, parent_run_id TEXT, created_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS runs_conversation ON runs(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS run_events(run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, ts TEXT NOT NULL,
  payload TEXT NOT NULL, PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS evidence(conversation_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL,
  user_id TEXT NOT NULL, system TEXT, report_id TEXT, payload TEXT NOT NULL, created_at TEXT,
  PRIMARY KEY(conversation_id, id));
CREATE TABLE IF NOT EXISTS visuals(conversation_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL,
  payload TEXT NOT NULL, PRIMARY KEY(conversation_id, id));
CREATE TABLE IF NOT EXISTS checks(run_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
  user_id TEXT NOT NULL, created_at TEXT, expires_at TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reports_user ON reports(user_id, created_at);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user_id TEXT, action TEXT,
  run_id TEXT, system TEXT, report_id TEXT, outcome TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS gemini_links(user_id TEXT PRIMARY KEY, google_email TEXT, project TEXT, linked_at TEXT,
  method TEXT);
CREATE TABLE IF NOT EXISTS oauth_pending(state TEXT PRIMARY KEY, user_id TEXT NOT NULL, verifier TEXT NOT NULL,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, user_id TEXT,
  category TEXT, note TEXT);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12).replace('-', 'x').replace('_', 'y')}"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("The database was created by a newer Wizard release. Use a compatible release.")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(SCHEMA)
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).rowcount

    # Users -------------------------------------------------------------------------------------------------------------
    def touch_user(self, user_id: str, email: str, name: str, role: str) -> None:
        stamp = now()
        self._x("INSERT INTO users(id,email,name,role,first_seen,last_seen) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET email=excluded.email,name=excluded.name,role=excluded.role,"
                "last_seen=excluded.last_seen", (user_id, email, name, role, stamp, stamp))

    # Conversations -----------------------------------------------------------------------------------------------------
    def create_conversation(self, user_id: str, title: str = "New analysis") -> str:
        conversation_id = new_id("cnv")
        stamp = now()
        self._x("INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (conversation_id, user_id, title, stamp, stamp))
        return conversation_id

    def conversation(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM conversations WHERE id=? AND user_id=? AND deleted_at IS NULL", (conversation_id, user_id))
        return dict(rows[0]) if rows else None

    def conversations(self, user_id: str, query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if query:
            rows = self._q("SELECT * FROM conversations WHERE user_id=? AND deleted_at IS NULL AND title LIKE ? "
                           "ORDER BY updated_at DESC LIMIT ?", (user_id, f"%{query}%", limit))
        else:
            rows = self._q("SELECT * FROM conversations WHERE user_id=? AND deleted_at IS NULL ORDER BY updated_at DESC "
                           "LIMIT ?", (user_id, limit))
        return [dict(r) for r in rows]

    def rename_conversation(self, user_id: str, conversation_id: str, title: str) -> bool:
        return self._x("UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=? AND deleted_at IS NULL",
                       (title, now(), conversation_id, user_id)) == 1

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        return self._x("UPDATE conversations SET deleted_at=? WHERE id=? AND user_id=? AND deleted_at IS NULL",
                       (now(), conversation_id, user_id)) == 1

    def touch_conversation(self, conversation_id: str, title: str | None = None) -> None:
        if title:
            self._x("UPDATE conversations SET updated_at=?, title=CASE WHEN title='New analysis' THEN ? ELSE title END "
                    "WHERE id=?", (now(), title, conversation_id))
        else:
            self._x("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))

    # Runs --------------------------------------------------------------------------------------------------------------
    def create_run(self, run: dict[str, Any]) -> None:
        columns = ",".join(run)
        self._x(f"INSERT INTO runs({columns}) VALUES({','.join('?' * len(run))})", tuple(run.values()))  # noqa: S608

    def update_run(self, run_id: str, **fields: Any) -> None:
        assignments = ",".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE runs SET {assignments} WHERE id=?", (*fields.values(), run_id))  # noqa: S608

    def run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                       "WHERE r.id=? AND r.user_id=? AND c.deleted_at IS NULL", (run_id, user_id))
        return dict(rows[0]) if rows else None

    def runs(self, conversation_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM runs WHERE conversation_id=? ORDER BY created_at", (conversation_id,))]

    def mark_interrupted(self) -> int:
        """Runs left 'running' by a previous process (crash, reboot) are closed honestly, not resumed silently."""
        return self._x("UPDATE runs SET status='failed', error_code='interrupted', error_message=?, finished_at=? "
                       "WHERE status IN ('queued','running')",
                       ("Wizard restarted before this run finished. Ask again to rerun it.", now()))

    # Events ------------------------------------------------------------------------------------------------------------
    def add_event(self, run_id: str, seq: int, kind: str, payload: dict[str, Any]) -> str:
        stamp = now()
        self._x("INSERT INTO run_events(run_id,seq,type,ts,payload) VALUES(?,?,?,?,?)",
                (run_id, seq, kind, stamp, json.dumps(payload, default=str)))
        return stamp

    def events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return [{"seq": r["seq"], "type": r["type"], "ts": r["ts"], "payload": json.loads(r["payload"])}
                for r in self._q("SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after))]

    # Evidence, visuals, checks -----------------------------------------------------------------------------------------
    def add_evidence(self, conversation_id: str, run_id: str, user_id: str, payload: dict[str, Any]) -> str:
        with self.lock:
            count = self.db.execute("SELECT COUNT(*) FROM evidence WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
            evidence_id = f"E{count + 1}"
            body = {**payload, "id": evidence_id, "run_id": run_id}
            self.db.execute("INSERT INTO evidence(conversation_id,id,run_id,user_id,system,report_id,payload,created_at) "
                            "VALUES(?,?,?,?,?,?,?,?)", (conversation_id, evidence_id, run_id, user_id, payload.get("system"),
                                                        payload.get("report_id"), json.dumps(body, default=str), now()))
        return evidence_id

    def evidence(self, conversation_id: str, evidence_id: str | None = None) -> list[dict[str, Any]]:
        if evidence_id:
            rows = self._q("SELECT payload FROM evidence WHERE conversation_id=? AND id=?", (conversation_id, evidence_id))
        else:
            rows = self._q("SELECT payload FROM evidence WHERE conversation_id=? ORDER BY CAST(substr(id,2) AS INTEGER)",
                           (conversation_id,))
        return [json.loads(r["payload"]) for r in rows]

    def add_visual(self, conversation_id: str, run_id: str, payload: dict[str, Any]) -> str:
        with self.lock:
            count = self.db.execute("SELECT COUNT(*) FROM visuals WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
            visual_id = f"V{count + 1}"
            self.db.execute("INSERT INTO visuals(conversation_id,id,run_id,payload) VALUES(?,?,?,?)",
                            (conversation_id, visual_id, run_id, json.dumps({**payload, "id": visual_id, "run_id": run_id})))
        return visual_id

    def visuals(self, conversation_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._q("SELECT payload FROM visuals WHERE conversation_id=? AND (? IS NULL OR run_id=?) "
                       "ORDER BY CAST(substr(id,2) AS INTEGER)", (conversation_id, run_id, run_id))
        return [json.loads(r["payload"]) for r in rows]

    def add_check(self, run_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            count = self.db.execute("SELECT COUNT(*) FROM checks WHERE run_id=?", (run_id,)).fetchone()[0]
            self.db.execute("INSERT INTO checks(run_id,seq,payload) VALUES(?,?,?)", (run_id, count + 1, json.dumps(payload)))

    def checks(self, run_id: str) -> list[dict[str, Any]]:
        return [json.loads(r["payload"]) for r in self._q("SELECT payload FROM checks WHERE run_id=? ORDER BY seq", (run_id,))]

    # Reports -----------------------------------------------------------------------------------------------------------
    def save_report(self, report: dict[str, Any], retention_days: int) -> None:
        expires = (datetime.now(UTC) + timedelta(days=retention_days)).isoformat(timespec="seconds")
        report["expires_at"] = expires
        self._x("INSERT OR REPLACE INTO reports(id,run_id,conversation_id,user_id,created_at,expires_at,payload) "
                "VALUES(?,?,?,?,?,?,?)", (report["id"], report["run_id"], report["conversation_id"], report["user_id"],
                                          report["created_at"], expires, json.dumps(report, default=str)))

    def report(self, report_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT payload, expires_at FROM reports WHERE id=?", (report_id,))
        if not rows:
            return None
        if rows[0]["expires_at"] and rows[0]["expires_at"] < now():
            return {"expired": True}
        return dict(json.loads(rows[0]["payload"]))

    def reports(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._q("SELECT payload FROM reports WHERE user_id=? AND expires_at>=? ORDER BY created_at DESC LIMIT ?",
                       (user_id, now(), limit))
        out = []
        for row in rows:
            report = json.loads(row["payload"])
            out.append({k: report.get(k) for k in ("id", "question", "created_at", "data_mode", "check", "run_id",
                                                     "conversation_id", "expires_at")})
        return out

    def update_report(self, report_id: str, **fields: Any) -> None:
        report = self.report(report_id)
        if report and not report.get("expired"):
            report.update(fields)
            self._x("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report, default=str), report_id))

    def purge_expired(self) -> int:
        return self._x("DELETE FROM reports WHERE expires_at < ?", (now(),))

    # Gemini links ------------------------------------------------------------------------------------------------------
    def save_link(self, user_id: str, google_email: str, project: str | None, method: str) -> None:
        self._x("INSERT OR REPLACE INTO gemini_links(user_id,google_email,project,linked_at,method) VALUES(?,?,?,?,?)",
                (user_id, google_email, project, now(), method))

    def link(self, user_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM gemini_links WHERE user_id=?", (user_id,))
        return dict(rows[0]) if rows else None

    def delete_link(self, user_id: str) -> None:
        self._x("DELETE FROM gemini_links WHERE user_id=?", (user_id,))

    def put_pending(self, state: str, user_id: str, verifier: str, created: float) -> None:
        self._x("DELETE FROM oauth_pending WHERE created_at < ?", (created - 900,))
        self._x("INSERT INTO oauth_pending(state,user_id,verifier,created_at) VALUES(?,?,?,?)", (state, user_id, verifier, created))

    def take_pending(self, state: str, user_id: str, oldest: float) -> str | None:
        with self.lock:
            rows = self.db.execute("SELECT verifier, created_at FROM oauth_pending WHERE state=? AND user_id=?",
                                   (state, user_id)).fetchall()
            self.db.execute("DELETE FROM oauth_pending WHERE state=?", (state,))
        return rows[0]["verifier"] if rows and rows[0]["created_at"] >= oldest else None

    # Audit and feedback ------------------------------------------------------------------------------------------------
    def audit(self, user_id: str, action: str, *, run_id: str | None = None, system: str | None = None,
              report_id: str | None = None, outcome: str = "ok", detail: dict[str, Any] | None = None) -> None:
        self._x("INSERT INTO audit_log(ts,user_id,action,run_id,system,report_id,outcome,detail) VALUES(?,?,?,?,?,?,?,?)",
                (now(), user_id, action, run_id, system, report_id, outcome, json.dumps(detail or {})))

    def audit_entries(self, user_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM audit_log WHERE (? IS NULL OR user_id=?) ORDER BY id DESC LIMIT ?", (user_id, user_id, limit))
        return [dict(r) for r in rows]

    def add_feedback(self, run_id: str, user_id: str, category: str, note: str) -> None:
        self._x("INSERT INTO feedback(ts,run_id,user_id,category,note) VALUES(?,?,?,?,?)", (now(), run_id, user_id, category, note))

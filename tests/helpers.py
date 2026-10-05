"""Shared test helpers and constants."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from wizard_api.config import Settings, load_settings

HEADERS = {"X-Wizard-Request": "1"}
TEST_TMP = Path(__file__).resolve().parents[1] / "artifacts" / "test-tmp"
CEO_QUESTION = ("Which market gave us the best return on marketing investment last quarter — tie NERP spend to "
                "sell-through, share gain, and competitive switching, and rank them.")
PLANNER_QUESTION = ("Flag any model where sell-in is outpacing sell-out and installed-base growth is stalling — then check "
                    "Smart Switch and app usage to tell me if it's a demand problem or a channel-stuffing problem.")
CONQUEST_QUESTION = ("Where are we winning switchers from Apple and Xiaomi according to Smart Switch, and does our "
                     "investment and sell-out data support doubling down there?")


class MemoryRecorder:
    def __init__(self) -> None:
        self.evidence: list[dict[str, Any]] = []
        self.visuals: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.files = {}

    def add_evidence(self, payload: dict[str, Any]) -> str:
        evidence_id = f"E{len(self.evidence) + 1}"
        self.evidence.append({**payload, "id": evidence_id})
        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        return next((e for e in self.evidence if e["id"] == evidence_id), None)

    def all_evidence(self) -> list[dict[str, Any]]:
        return self.evidence

    def add_visual(self, payload: dict[str, Any]) -> str:
        visual_id = f"V{len(self.visuals) + 1}"
        self.visuals.append({**payload, "id": visual_id})
        return visual_id

    def add_check(self, payload: dict[str, Any]) -> None:
        self.checks.append(payload)

    files: dict[str, tuple[dict[str, Any], str]]

    def attachments(self) -> list[dict[str, Any]]:
        return [row for row, _ in self.files.values()]

    def attachment(self, label: str) -> tuple[dict[str, Any], str] | None:
        return self.files.get(label)


def make_settings(tmp_path: Path, **overrides: str) -> Settings:
    env = {"WIZARD_DATA_DIR": str(tmp_path / "var"), "WIZARD_AGENT_RUNTIME": "replay", "WIZARD_ATTACHMENT_OFFICE": "never",
           "WIZARD_ATTACHMENT_FOLDERS": "none", **overrides}
    return load_settings(env=env, env_file=tmp_path / "absent.env")


def login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/v1/session/login", json={"user_id": user_id}, headers=HEADERS)
    assert response.status_code == 200, response.text


def wait_run(client: TestClient, run_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return dict(run)
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def ask(client: TestClient, question: str, conversation_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    started = client.post("/api/v1/runs", json=body, headers=HEADERS)
    assert started.status_code == 200, started.text
    return wait_run(client, started.json()["run_id"])


def sse_events(client: TestClient, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    events = []
    with client.stream("GET", f"/api/v1/runs/{run_id}/events?after={after}") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:])
                events.append(event)
                if event["type"] in ("run_finished", "run_failed"):
                    break
    return events


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

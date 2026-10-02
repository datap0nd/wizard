"""The real Gemini CLI (pinned in .tools/ or WIZARD_GEMINI_CLI_JS) with offline fake model responses.

No Google model is called: --fake-responses replays scripted model turns. Everything else is real - the CLI's settings
handling, per-user home, policy engine, MCP client, Wizard's shim, tool execution, evidence and stream-json parsing.
Skipped (reported, not passed) when the CLI is not installed."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import httpx
import pytest

from wizard_agent.gemini_cli import resolve_cli_js

ROOT = Path(__file__).resolve().parents[2]
CLI_JS = resolve_cli_js(os.environ.get("WIZARD_GEMINI_CLI_JS"), ROOT)
pytestmark = [pytest.mark.gemini_cli,
              pytest.mark.skipif(CLI_JS is None or shutil.which("node") is None,
                                 reason="BLOCKED: Gemini CLI not installed (npm --prefix .tools install @google/gemini-cli)")]
FAKE = ROOT / "fixtures" / "gemini_fake" / "ceo-two-tools.jsonl"


def start_run(app, user: str, question: str) -> dict:
    client = httpx.Client(base_url=app.state.base_url, headers={"X-Wizard-Request": "1"}, timeout=60)
    client.post("/api/v1/session/login", json={"user_id": user}).raise_for_status()
    run_id = client.post("/api/v1/runs", json={"question": question}).json()["run_id"]
    deadline = time.time() + 180
    while time.time() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return dict(run)
        time.sleep(0.25)
    raise AssertionError("Gemini CLI run did not finish")


def test_cli_calls_wizard_tools_through_mcp(live_server):
    app = live_server(WIZARD_AGENT_RUNTIME="gemini-cli", WIZARD_GEMINI_FAKE_RESPONSES=str(FAKE))
    run = start_run(app, "u-ceo", "Which market spent most on marketing in Q3?")
    assert run["status"] == "succeeded", (run.get("error_code"), run.get("error_message"))
    assert run["runtime_label"].startswith("Gemini CLI 0.") and run["session_id"]
    traces = [e["payload"] for e in app.state.store.events(run["id"]) if e["type"] == "model_tool_trace"]
    assert [t["name"] for t in traces if t["phase"] == "use"] == ["mcp_wizard_search_catalog", "mcp_nerp_run_report"]
    assert all(t["status"] == "success" for t in traces if t["phase"] == "result")
    finished = [e["payload"] for e in run["events"] if e["type"] == "tool_finished"]
    assert [f["name"] for f in finished] == ["wizard_search_catalog", "nerp_run_report"] and finished[1]["evidence"]["id"] == "E1"
    assert run["answer"].startswith("EG spent $1.5M in 2026-Q3 [E1]") and run["data_mode"] == "SYNTHETIC"
    assert [e["payload"]["text"] for e in run["events"] if e["type"] == "note"] == ["I'll look for marketing spend first."]


def test_cli_declares_only_wizard_tools_and_uses_per_user_file_credentials(live_server, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text('{"method":"countTokens","response":{"totalTokens":1}}\n')
    app = live_server(WIZARD_AGENT_RUNTIME="gemini-cli", WIZARD_GEMINI_FAKE_RESPONSES=str(empty))
    run = start_run(app, "u-cfo", "hello")
    assert run["status"] == "failed" and run["error_code"] == "fake_responses_exhausted"
    detail = next(e["payload"]["detail"] for e in app.state.store.events(run["id"]) if e["type"] == "diagnostic")
    assert "Blocked dangerous environment variable" not in detail
    settings = app.state.settings
    home = settings.user_home("u-cfo") / "gemini"
    assert json.loads((home / ".gemini" / "settings.json").read_text())["tools"]["core"] == []
    other = settings.user_home("u-ceo") / "gemini"
    assert not other.exists(), "running as one user must not create or touch another user's Gemini home"


def test_cli_tool_declarations(live_server, tmp_path):
    """The model-facing declarations: exactly 15 Wizard tools, no shell/file/web tools."""
    import subprocess

    from wizard_agent.runtime import AgentRequest
    from wizard_api.runs import ActiveRun
    from wizard_api.security import run_token
    from wizard_connectors.entitlements import IdentityDirectory
    empty = tmp_path / "empty.jsonl"
    empty.write_text('{"method":"countTokens","response":{"totalTokens":1}}\n')
    app = live_server(WIZARD_AGENT_RUNTIME="gemini-cli", WIZARD_GEMINI_FAKE_RESPONSES=str(empty))
    runtime, settings = app.state.manager.runtime, app.state.settings
    identity = IdentityDirectory.load(ROOT / "fixtures" / "identities.json").get("u-ceo")
    app.state.manager.active["run_decl"] = ActiveRun("run_decl", identity, "cnv", "ask", "q", None, "gemini-cli")
    user_home = settings.user_home("u-ceo")
    home = runtime.prepare_home(user_home)
    request = AgentRequest(run_id="run_decl", user_id="u-ceo", user_email="ceo@wizard.test", user_home=user_home, prompt="hi",
                           question="hi", kind="ask", internal_url=settings.internal_url,
                           run_token=run_token(settings.session_secret, "run_decl", "u-ceo", 300))
    workdir = user_home / "runs" / "decl"
    workdir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(runtime.command(), cwd=workdir, env=runtime.build_env(home, request), input=b"hi\n",
                            capture_output=True, timeout=180)
    final = [json.loads(line) for line in result.stdout.decode().splitlines() if '"type":"result"' in line][-1]
    message = final["error"]["message"]
    sent = json.loads(message[message.index("{"):message.rindex("}") + 1])
    names = sorted(f["name"] for t in sent["config"]["tools"] for f in t["functionDeclarations"])
    assert names == sorted(f"mcp_{s.name}" for s in app.state.registry.list())
    assert not [n for n in names if any(w in n for w in ("shell", "write", "file", "web", "fetch", "memory"))]
    assert sent["config"]["systemInstruction"].startswith("You are Wizard")
    assert sent["config"]["thinkingConfig"]["thinkingLevel"] == "HIGH"


def test_installation_probe_passes_and_ignores_parent_gemini_md(tmp_path):
    """The same probe `run.py --check` runs on the work PC (it plants a GEMINI.md above the run folder)."""
    from wizard_api.config import load_settings
    from wizard_api.preflight import probe_gemini_cli
    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "gemini-cli"}, home=tmp_path)
    passed, detail = probe_gemini_cli(settings)
    assert passed, detail
    assert "15 read-only tools" in detail

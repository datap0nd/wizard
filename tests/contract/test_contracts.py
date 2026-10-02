"""Contract tests: published tool catalog, source contracts, run events and the MCP stdio shim with a real server."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
from tests.helpers import CEO_QUESTION, ask, login

from wizard_api.runs import ActiveRun
from wizard_api.security import run_token
from wizard_connectors.entitlements import IdentityDirectory

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def load(name: str):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_tool_catalog_matches_published_contract(registry):
    published = load("tool-catalog.json")
    assert published["tools"] == registry.describe(), "run scripts/export_contracts.py and review the diff"


def test_source_contracts_validate():
    schema = load("source-contract.schema.json")
    for path in sorted((CONTRACTS / "sources").glob("*.json")):
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)


def test_run_events_and_reports_validate(client):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    event_schema, report_schema = load("run-event.schema.json"), load("report.schema.json")
    for event in client.app.state.store.events(run["id"]):
        jsonschema.validate(event, event_schema)
    jsonschema.validate(client.get(f"/api/v1/reports/{run['report_id']}").json()["report"], report_schema)


def test_openapi_lists_the_documented_surface(client):
    assert client.get("/api/v1/openapi.json").status_code == 401, "the API description is not public"
    login(client, "u-ceo")
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for path in ("/api/v1/runs", "/api/v1/runs/{run_id}", "/api/v1/runs/{run_id}/events", "/api/v1/reports/{report_id}",
                 "/api/v1/sources", "/api/v1/sources/{system_id}/catalog", "/api/v1/runs/{run_id}/check"):
        assert path in paths


def shim(scope: str, url: str, token: str, messages: list[dict]) -> list[dict]:
    env = {**os.environ, "WIZARD_RUN_TOKEN": token, "WIZARD_INTERNAL_URL": url}
    payload = "".join(json.dumps(m) + "\n" for m in messages).encode()
    result = subprocess.run([sys.executable, "-m", "wizard_connectors.mcp_shim", "--scope", scope], input=payload,
                            capture_output=True, env=env, timeout=60, cwd=ROOT / "services" / "connectors")
    return [json.loads(line) for line in result.stdout.decode().splitlines()]


def test_mcp_shim_over_stdio_against_live_server(live_server):
    app = live_server()
    identity = IdentityDirectory.load(ROOT / "fixtures" / "identities.json").get("u-dir-gulf")
    app.state.manager.active["run_mcp"] = ActiveRun("run_mcp", identity, app.state.store.create_conversation("u-dir-gulf"),
                                                    "ask", "q", None, "gemini-cli")
    token = run_token(app.state.settings.session_secret, "run_mcp", "u-dir-gulf", 120)
    replies = shim("nerp", app.state.base_url, token, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                      "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_report", "arguments": {
            "report_id": "nerp-mkt-spend-quarterly", "group_by": ["market"], "measures": ["spend_usd"]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "run_report", "arguments": {"sql": "drop table"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ])
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert [t["name"] for t in by_id[2]["result"]["tools"]] == ["search_reports", "get_report_schema", "run_report"]
    assert all(t["annotations"]["readOnlyHint"] for t in by_id[2]["result"]["tools"])
    ok = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert not by_id[3]["result"]["isError"] and ok["evidence_id"] == "E1" and {r[0] for r in ok["rows"]} <= {"SA", "AE"}
    assert by_id[4]["result"]["isError"] and "invalid_arguments" in by_id[4]["result"]["content"][0]["text"]
    assert by_id[5]["error"]["code"] == -32601 and by_id[6]["result"] == {}
    events = [e["type"] for e in app.state.store.events("run_mcp")]
    assert events.count("tool_started") == 2 and events.count("tool_finished") == 2
    app.state.manager.active.pop("run_mcp")
    expired = shim("nerp", app.state.base_url, token, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                        "params": {"name": "search_reports", "arguments": {"query": "x"}}}])
    assert expired[0]["result"]["isError"] and "no longer authorised" in expired[0]["result"]["content"][0]["text"]


def test_shim_refuses_to_start_without_run_context():
    result = subprocess.run([sys.executable, "-m", "wizard_connectors.mcp_shim", "--scope", "nerp"], capture_output=True,
                            env={k: v for k, v in os.environ.items() if not k.startswith("WIZARD_")}, timeout=30,
                            cwd=ROOT / "services" / "connectors", input=b"")
    assert result.returncode == 2

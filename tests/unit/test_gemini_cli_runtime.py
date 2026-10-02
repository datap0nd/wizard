from __future__ import annotations

import json
from pathlib import Path

from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, classify, policy_toml, redact
from wizard_agent.runtime import AgentRequest
from wizard_agent.stream_json import map_event, parse_line


def runtime(tmp_path: Path, **kw) -> GeminiCliRuntime:
    cli = tmp_path / "gemini.js"
    cli.write_text("// stub")
    return GeminiCliRuntime(GeminiCliConfig(model="gemini-3.8-flash", internal_url="http://127.0.0.1:8770", cli_js=cli,
                                            node="node", **kw))


def request(home: Path, token: str = "tok-123") -> AgentRequest:
    return AgentRequest(run_id="run_1", user_id="u-ceo", user_email="ceo@wizard.test", user_home=home, prompt="p",
                        question="q", kind="ask", run_token=token, internal_url="http://127.0.0.1:8770")


def test_settings_remove_builtin_tools_and_allow_only_wizard_servers(tmp_path):
    rt = runtime(tmp_path)
    home = rt.prepare_home(tmp_path / "users" / "a")
    settings = json.loads((home / ".gemini" / "settings.json").read_text())
    assert settings["tools"]["core"] == []
    assert settings["mcp"]["allowed"] == ["asap", "gscm", "nerp", "wizard"]
    assert settings["security"]["auth"]["selectedType"] == "oauth-personal"
    assert settings["model"]["name"] == "gemini-3.8-flash"
    for server in settings["mcpServers"].values():
        assert server["args"][:2] == ["-m", "wizard_connectors.mcp_shim"]
        assert set(server["env"]) == {"WIZARD_RUN_TOKEN", "WIZARD_INTERNAL_URL"}  # PYTHONPATH is blocked by the CLI
        assert server["env"]["WIZARD_RUN_TOKEN"] == "$WIZARD_RUN_TOKEN", "the token must never be written to disk"
    policy = (home / ".gemini" / "wizard-policy.toml").read_text()
    assert policy == policy_toml(["asap", "gscm", "nerp", "wizard"])
    assert 'mcpName = "*"\ndecision = "deny"' in policy and policy.count('decision = "allow"') == 4


def test_each_user_gets_an_isolated_home_and_file_credentials(tmp_path):
    rt = runtime(tmp_path)
    a, b = rt.prepare_home(tmp_path / "users" / "a"), rt.prepare_home(tmp_path / "users" / "b")
    env_a, env_b = rt.build_env(a, request(tmp_path / "users" / "a")), rt.build_env(b, request(tmp_path / "users" / "b"))
    assert env_a["GEMINI_CLI_HOME"] != env_b["GEMINI_CLI_HOME"]
    for env, home in ((env_a, a), (env_b, b)):
        assert env["GEMINI_FORCE_FILE_STORAGE"] == "true", "keychain storage would be shared between users"
        assert env["USERPROFILE"] == env["HOME"] == str(home)
        assert env["APPDATA"].startswith(str(home)) and env["TEMP"].startswith(str(home))
        assert env["NO_BROWSER"] == "true"
        assert "GEMINI_API_KEY" not in env and "GOOGLE_APPLICATION_CREDENTIALS" not in env


def test_command_uses_node_directly_and_keeps_secrets_off_argv(tmp_path):
    rt = runtime(tmp_path)
    home = rt.prepare_home(tmp_path / "users" / "a")
    cmd = rt.command()
    assert cmd[0] == "node" and cmd[1].endswith("gemini.js") and not any(part.endswith(".cmd") for part in cmd)
    assert "--output-format" in cmd and "stream-json" in cmd and "--policy" in cmd and "--yolo" not in cmd
    assert cmd[cmd.index("--policy") + 1] == str(home / ".gemini" / "wizard-policy.toml")
    assert not any("tok-123" in part for part in cmd)
    env = rt.build_env(home, request(tmp_path / "users" / "a"))
    assert env["WIZARD_RUN_TOKEN"] == "tok-123"


def test_signed_in_detects_per_home_credentials(tmp_path):
    rt = runtime(tmp_path)
    user = tmp_path / "users" / "a"
    assert not rt.signed_in(user)
    rt.prepare_home(user)
    (rt.gemini_home(user) / ".gemini" / "gemini-credentials.json").write_text("{}")
    assert rt.signed_in(user) and not rt.signed_in(tmp_path / "users" / "b")


def test_stream_json_mapping():
    assert map_event(parse_line('{"type":"init","timestamp":"t","session_id":"s","model":"m"}')).kind == "agent_session"
    delta = map_event(parse_line('{"type":"message","role":"assistant","content":"Hi","delta":true}'))
    assert delta.kind == "text_delta" and delta.payload == {"text": "Hi", "delta": True}
    assert map_event(parse_line('{"type":"message","role":"user","content":"q"}')) is None
    use = map_event(parse_line('{"type":"tool_use","tool_name":"mcp_nerp_run_report","tool_id":"1","parameters":{"a":1}}'))
    assert use.kind == "model_tool_trace" and use.payload["phase"] == "use"
    result = map_event(parse_line('{"type":"tool_result","tool_id":"1","status":"error","error":{"type":"x","message":"m"}}'))
    assert result.payload == {"phase": "result", "tool_id": "1", "status": "error", "error": "m"}
    assert map_event(parse_line('{"type":"error","severity":"warning","message":"w"}')).kind == "warning"
    assert map_event(parse_line('{"type":"result","status":"success","stats":{"tool_calls":2}}')).payload["stats"] == {"tool_calls": 2}
    assert parse_line("Ripgrep is not available.") is None and parse_line("{not json") is None


def test_failure_classification_and_redaction():
    assert classify("Please set an Auth method in settings")[0] == "gemini_signin_required"
    assert classify("429 RESOURCE_EXHAUSTED")[0] == "model_capacity"
    assert classify("PERMISSION_DENIED for project")[0] == "model_permission_denied"
    assert classify("fetch failed ENOTFOUND")[0] == "model_unreachable"
    assert classify("weird")[0] == "model_error"
    assert classify("No more mock responses ... session 1790927401123 ... oauth")[0] == "fake_responses_exhausted"
    assert classify("request id 84014012 failed")[0] == "model_error", "digits inside ids are not status codes"
    assert redact("token=abc ya29.secretTOKEN and abc", "abc") == "token=[redacted] [redacted] and [redacted]"

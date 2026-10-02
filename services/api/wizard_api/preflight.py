"""`run.py --check`: validate an installation before anyone uses it, without calling Google or touching real data.

The Gemini CLI probe runs the installed CLI against a throwaway Wizard instance with offline fake model replies and reads
back the request the CLI would have sent: it must offer exactly Wizard's tools, use Wizard's system prompt and ignore any
GEMINI.md lying in parent folders. This catches CLI versions whose settings or policy format changed."""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .config import ConfigError, Settings

MARKER = "WIZARD-PREFLIGHT-PARENT-CONTEXT-MARKER"


def _line(status: str, text: str) -> None:
    print(f"{status:<5} {text}", flush=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def probe_gemini_cli(settings: Settings) -> tuple[bool, str]:
    import uvicorn

    from wizard_agent.runtime import AgentRequest
    from wizard_connectors.entitlements import IdentityDirectory

    from .app import create_app
    from .runs import ActiveRun
    from .security import run_token

    scratch = Path(tempfile.mkdtemp(prefix="wizard-probe-"))
    try:
        (scratch / "GEMINI.md").write_text(MARKER, encoding="utf-8")
        fake = scratch / "fake.jsonl"
        fake.write_text('{"method":"countTokens","response":{"totalTokens":1}}\n', encoding="utf-8")
        port = _free_port()
        probe_settings = dataclasses.replace(settings, data_dir=scratch / "data", port=port, host="127.0.0.1",
                                             gemini_fake_responses=str(fake), content_dir=None)
        app = create_app(probe_settings)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        try:
            runtime, registry = app.state.manager.runtime, app.state.registry
            identity = IdentityDirectory.load(probe_settings.identities_file).get("u-ceo")
            if identity is None:
                return False, "the synthetic probe identity u-ceo is missing from the identities file"
            app.state.manager.active["run_probe"] = ActiveRun("run_probe", identity, "cnv", "ask", "q", None, "gemini-cli")
            user_home = probe_settings.user_home("u-ceo")
            home = runtime.prepare_home(user_home)
            request = AgentRequest(run_id="run_probe", user_id="u-ceo", user_email="ceo@wizard.test", user_home=user_home,
                                   prompt="hi", question="hi", kind="ask", internal_url=probe_settings.internal_url,
                                   run_token=run_token(probe_settings.session_secret, "run_probe", "u-ceo", 300))
            workdir = user_home / "runs" / "probe"
            workdir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(runtime.command(), cwd=workdir, env=runtime.build_env(home, request), input=b"hi\n",
                                    capture_output=True, timeout=240,
                                    creationflags=0x08000000 if os.name == "nt" else 0)
        finally:
            server.should_exit = True
        lines = [json.loads(line) for line in result.stdout.decode("utf-8", "replace").splitlines() if line.startswith("{")]
        final = next((e for e in reversed(lines) if e.get("type") == "result"), None)
        if not final or "error" not in final:
            tail = result.stderr.decode("utf-8", "replace")[-600:]
            return False, f"the CLI did not reach the model call (exit {result.returncode}). {tail}"
        message = final["error"]["message"]
        try:
            sent = json.loads(message[message.index("{"):message.rindex("}") + 1])
        except ValueError:
            return False, f"unexpected CLI error: {message[:300]}"
        declared = sorted(f["name"] for t in sent.get("config", {}).get("tools", []) for f in t.get("functionDeclarations", []))
        expected = sorted(f"mcp_{s.name}" for s in registry.list())
        problems = []
        if declared != expected:
            problems.append(f"tools offered to the model differ: {len(declared)} offered, expected {len(expected)} "
                            f"({', '.join(sorted(set(declared) ^ set(expected)))[:300]})")
        if not str(sent.get("config", {}).get("systemInstruction", "")).startswith("You are Wizard"):
            problems.append("Wizard's system prompt was not used (GEMINI_SYSTEM_MD ignored)")
        if MARKER in json.dumps(sent):
            problems.append("a GEMINI.md from a parent folder leaked into the analyst's context")
        thinking = sent.get("config", {}).get("thinkingConfig", {})
        if problems:
            return False, "; ".join(problems)
        return True, f"offers exactly Wizard's {len(expected)} read-only tools, Wizard's prompt, thinking {thinking.get('thinkingLevel', 'default')}"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def run_checks(settings: Settings) -> int:
    """0 = ready; 1 = the application works but Gemini CLI is not usable yet; 2 = the application cannot start."""
    ok = True
    gemini_ok = True
    print("Wizard installation check", flush=True)
    _line("INFO", f"runtime {settings.runtime} · model {settings.model} · auth {settings.auth_mode} · port {settings.port}")
    _line("INFO", f"data {settings.data_dir} · content {settings.content_dir or 'built-in SYNTHETIC examples'}")
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _line("PASS", "data folder is writable")
    except OSError as error:
        ok = False
        _line("FAIL", f"data folder is not writable: {error}")
    if (settings.web_dist / "index.html").is_file():
        _line("PASS", "web app is built")
    else:
        ok = False
        _line("FAIL", f"web app missing at {settings.web_dist}")
    try:
        from .app import create_app
        app = create_app(settings)
        app.state.store.db.close()
        systems = ", ".join(s.id.upper() for s in app.state.manager.services.catalog.systems)
        _line("PASS", f"application starts; platforms: {systems}")
    except ConfigError as error:
        _line("FAIL", str(error))
        return 2
    if settings.local_user_email:
        _line("PASS", f"your sign-in identity: {settings.local_user_name} <{settings.local_user_email}>")
    else:
        _line("WARN", "WIZARD_LOCAL_USER_EMAIL is not set: you can only use test identities and cannot link Gemini")
    if settings.runtime == "gemini-cli":
        from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, resolve_cli_js
        from wizard_connectors.paths import ROOT
        cli_js = resolve_cli_js(settings.gemini_cli_js, ROOT)
        node = settings.node or shutil.which("node")
        if not node:
            gemini_ok = False
            _line("FAIL", "Node.js not found (set WIZARD_NODE)")
        if not cli_js:
            gemini_ok = False
            _line("FAIL", "Gemini CLI not found (install it, or set WIZARD_GEMINI_CLI_JS to ...\\@google\\gemini-cli\\bundle\\gemini.js)")
        if node and cli_js:
            version = GeminiCliRuntime(GeminiCliConfig(model=settings.model, internal_url="", cli_js=cli_js, node=node)).version()
            _line("PASS", f"Gemini CLI {version or '(version unknown)'} at {cli_js}")
            if not (settings.google_cloud_project or os.environ.get("GOOGLE_CLOUD_PROJECT")):
                _line("WARN", "GOOGLE_CLOUD_PROJECT is not set; enterprise Gemini usually needs your organisation's project id")
            try:
                passed, detail = probe_gemini_cli(settings)
            except Exception as error:  # noqa: BLE001 - report any probe failure as a readable FAIL line
                passed, detail = False, f"probe error: {error}"
            gemini_ok = gemini_ok and passed
            _line("PASS" if passed else "FAIL", f"Gemini CLI compatibility: {detail}")
    elif settings.runtime == "code-assist":
        _line("INFO", "code-assist runtime: link your Gemini account in the app (Account → Sign in with Google)")
    else:
        _line("INFO", "replay runtime: recorded answers over synthetic data, no Gemini calls")
    if not ok:
        _line("FAIL", "the application is not ready")
        return 2
    if not gemini_ok:
        _line("WARN", "the application works, but Gemini CLI is not ready (replay mode still works)")
        return 1
    _line("PASS", "installation check finished")
    return 0

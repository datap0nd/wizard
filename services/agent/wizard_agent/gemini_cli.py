"""Gemini CLI runtime: headless stream-json runs under each user's own isolated Gemini CLI state.

Isolation rules (verified against Gemini CLI 0.62.0, see docs/gemini-runtime.md):
- GEMINI_CLI_HOME points at the user's own directory; settings, sessions and history live there.
- GEMINI_FORCE_FILE_STORAGE=true: by default the CLI keeps OAuth tokens in the OS keychain under one fixed entry
  ("gemini-cli-oauth"/"main-account") shared by every GEMINI_CLI_HOME of the same OS account. Forcing file storage keeps
  each user's tokens inside their own home. Without it two executives on one service account would share a login.
- tools.core = [] removes every built-in tool (shell, files, web); the model sees only Wizard's MCP tools.
- GEMINI_SYSTEM_MD replaces the CLI's coding-agent system prompt with Wizard's short analyst instructions.
- The CLI is started as `node gemini.js`, never through gemini.cmd: user text must not pass through cmd.exe parsing.
  The prompt goes over stdin, the run token over the environment (never argv)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import outbound
from .prompting import system_prompt
from .runtime import AgentFailure, AgentRequest, Emit, RuntimeKind, ToolBridge
from .stream_json import map_event, parse_line

PROMPT_FLAG_TEXT = "Respond to the request above as Wizard."
PASSTHROUGH_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "LANG", "LC_ALL", "TZ", "HTTPS_PROXY", "HTTP_PROXY",
                   "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
                   "PROGRAMFILES", "PROGRAMDATA", "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")
GEMINI_API_URL = "https://cloudcode-pa.googleapis.com/"
CREDENTIAL_FILES = ("gemini-credentials.json", "oauth_creds.json")


@dataclass
class GeminiCliConfig:
    model: str
    internal_url: str
    cli_js: Path | None = None
    node: str | None = None
    python: str = sys.executable
    scopes: list[str] = field(default_factory=lambda: ["asap", "gscm", "nerp", "wizard"])
    google_cloud_project: str | None = None
    fake_responses: Path | None = None
    timeout_s: int = 600
    shim_command: list[str] = field(default_factory=lambda: ["-m", "wizard_connectors.mcp_shim"])
    proxy: str | None = None  # WIZARD_PROXY: a URL or "direct"; None resolves it (see outbound.proxy_for)


def resolve_cli_js(explicit: str | None, repo_root: Path) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(repo_root / ".tools" / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    on_path = shutil.which("gemini")
    if on_path:
        resolved = Path(on_path).resolve()
        candidates.append(resolved if resolved.suffix == ".js" else resolved.parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    return next((c for c in candidates if c.is_file()), None)


def classify(message: str) -> tuple[str, str]:
    """Map CLI error text to a stable code. Most specific first; status codes only as whole words (an error dump can
    contain request ids and timestamps with arbitrary digits)."""
    text = message.lower()

    def has(*patterns: str) -> bool:
        return any(re.search(p, text) for p in patterns)

    if "no more mock responses" in text:
        return "fake_responses_exhausted", "The offline test transcript ended before the run finished."
    if has(r"auth method", r"unauthenticated", r"invalid_grant", r"401", r"failed to login", r"login required",
           r"oauth credentials"):
        return "gemini_signin_required", "Your Gemini sign-in is missing or expired. Link your Gemini account again."
    if has(r"429", r"resource_exhausted", r"quota", r"at capacity"):
        return "model_capacity", "Gemini is at capacity or your quota is exhausted. Try again in a few minutes."
    if has(r"permission_denied", r"403", r"not entitled"):
        return "model_permission_denied", "Your Gemini entitlement does not allow this model or project."
    if has(r"enotfound", r"econnrefused", r"etimedout", r"fetch failed", r"econnreset", r"certificate"):
        return "model_unreachable", "Gemini could not be reached from this host (network, proxy or certificate)."
    return "model_error", "Gemini stopped with an error. See the run diagnostics."


class GeminiCliRuntime:
    kind: RuntimeKind = "gemini-cli"

    def __init__(self, config: GeminiCliConfig):
        self.config = config
        self.model = config.model
        self._version: str | None = None

    # Status ------------------------------------------------------------------------------------------------------------
    def version(self) -> str | None:
        node = self._node()
        if self._version is None and self.config.cli_js and node:
            try:
                out = subprocess.run([node, str(self.config.cli_js), "--version"], capture_output=True, text=True,
                                     timeout=60, env=self._base_env(Path(os.environ.get("TEMP", "."))))
                self._version = out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else ""
            except (OSError, subprocess.TimeoutExpired):
                self._version = ""
        return self._version or None

    def label(self) -> str:
        version = self.version()
        return f"Gemini CLI {version} · {self.model}" if version else f"Gemini CLI · {self.model}"

    @staticmethod
    def gemini_home(user_home: Path) -> Path:
        return user_home / "gemini"

    def signed_in(self, user_home: Path) -> bool:
        directory = self.gemini_home(user_home) / ".gemini"
        return any((directory / name).is_file() for name in CREDENTIAL_FILES)

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]:
        if not self.config.cli_js or not self._node():
            return {"ready": False, "reason": "Gemini CLI is not installed on this host (set WIZARD_GEMINI_CLI_JS)."}
        if self.config.fake_responses:
            return {"ready": True, "reason": "Offline fake model responses (test mode)."}
        if not self.signed_in(user_home):
            return {"ready": False, "reason": "Link your own Gemini account to ask questions."}
        return {"ready": True, "reason": None}

    # Home preparation --------------------------------------------------------------------------------------------------
    def prepare_home(self, user_home: Path) -> Path:
        home = self.gemini_home(user_home)
        directory = home / ".gemini"
        directory.mkdir(parents=True, exist_ok=True)
        self._policy_path = directory / "wizard-policy.toml"
        (directory / "wizard-system.md").write_text(system_prompt(), encoding="utf-8")
        auth = "gemini-api-key" if self.config.fake_responses else "oauth-personal"
        env = {"WIZARD_RUN_TOKEN": "$WIZARD_RUN_TOKEN", "WIZARD_INTERNAL_URL": "$WIZARD_INTERNAL_URL"}
        settings = {
            "security": {"auth": {"selectedType": auth}, "folderTrust": {"enabled": False}},
            "model": {"name": self.model},
            "general": {"enableAutoUpdate": False, "enableAutoUpdateNotification": False},
            "privacy": {"usageStatisticsEnabled": False},
            "telemetry": {"enabled": False},
            "tools": {"core": []},
            "mcp": {"allowed": list(self.config.scopes)},
            # Never load GEMINI.md files from parent folders (an install folder's operator notes, a repo's developer
            # notes): the analyst's context is Wizard's system prompt plus the conversation, nothing else.
            "context": {"fileName": "WIZARD-RUNTIME-NO-PROJECT-CONTEXT.md", "includeDirectoryTree": False},
            "mcpServers": {
                scope: {"command": self.config.python, "args": [*self.config.shim_command, "--scope", scope],
                        "env": env, "trust": True, "timeout": self.config.timeout_s * 1000,
                        "description": f"Wizard read-only {scope} tools"}
                for scope in self.config.scopes
            },
        }
        (directory / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        (directory / "wizard-policy.toml").write_text(policy_toml(self.config.scopes), encoding="utf-8")
        for sub in ("AppData/Roaming", "AppData/Local", "tmp"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        return home

    def _node(self) -> str | None:
        return self.config.node or shutil.which("node")

    def _base_env(self, home: Path) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in PASSTHROUGH_ENV}
        env.update({"GEMINI_CLI_HOME": str(home), "USERPROFILE": str(home), "HOME": str(home),
                    "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
                    "TEMP": str(home / "tmp"), "TMP": str(home / "tmp"), "GEMINI_FORCE_FILE_STORAGE": "true",
                    "NO_BROWSER": "true", "NO_COLOR": "1", "FORCE_COLOR": "0",
                    # Trust the Windows certificate store (corporate TLS inspection); ignored by Node versions without it.
                    "NODE_USE_SYSTEM_CA": "1"})
        if not self.config.fake_responses:
            self._apply_proxy(env)
        return env

    def _apply_proxy(self, env: dict[str, str]) -> None:
        """The CLI's HOME is the user's isolated folder, so it cannot read the person's own Gemini CLI proxy setting or
        evaluate a Windows PAC script: hand it the proxy Wizard resolved for the Gemini API."""
        names = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
        if self.config.proxy is None and any(env.get(n) for n in names):
            return
        proxy, _ = outbound.proxy_for(GEMINI_API_URL, self.config.proxy)
        for name in names:
            env.pop(name, None)
        if proxy:
            env["HTTPS_PROXY"] = env["HTTP_PROXY"] = proxy
            env["NO_PROXY"] = ",".join(filter(None, [env.get("NO_PROXY") or env.pop("no_proxy", ""), "127.0.0.1,localhost"]))

    def build_env(self, home: Path, request: AgentRequest) -> dict[str, str]:
        env = self._base_env(home)
        env["GEMINI_SYSTEM_MD"] = str(home / ".gemini" / "wizard-system.md")
        env["WIZARD_RUN_TOKEN"] = request.run_token
        env["WIZARD_INTERNAL_URL"] = request.internal_url
        if self.config.google_cloud_project:
            env["GOOGLE_CLOUD_PROJECT"] = self.config.google_cloud_project
        if self.config.fake_responses:
            env["GEMINI_API_KEY"] = "offline-fake-responses"  # never sent: the fake content generator answers locally
        return env

    _policy_path: Path = Path("wizard-policy.toml")

    def command(self) -> list[str]:
        node = self._node()
        if not node or not self.config.cli_js:
            raise AgentFailure("runtime_unavailable", "Gemini CLI is not installed on this host.")
        cmd = [node, str(self.config.cli_js), "--output-format", "stream-json", "--model", self.model, "--skip-trust",
               "--policy", str(self._policy_path), "--prompt", PROMPT_FLAG_TEXT]
        if self.config.fake_responses:
            cmd += ["--fake-responses-non-strict", str(self.config.fake_responses)]
        return cmd

    # Run ---------------------------------------------------------------------------------------------------------------
    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        home = self.prepare_home(request.user_home)
        if not self.config.fake_responses and not self.signed_in(request.user_home):
            raise AgentFailure("gemini_signin_required", "Link your own Gemini account before asking questions. Wizard never "
                                                         "runs your question under someone else's sign-in.")
        workdir = request.user_home / "runs" / request.run_id
        workdir.mkdir(parents=True, exist_ok=True)
        cmd = self.command()
        env = self.build_env(home, request)
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(cmd, cwd=workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, creationflags=flags, start_new_session=sys.platform != "win32")
        except OSError as error:
            raise AgentFailure("runtime_unavailable", f"Gemini CLI could not start: {error.strerror}.") from None

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
        stderr_tail: deque[str] = deque(maxlen=60)

        def pump(stream: Any, tag: str) -> None:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace")
                if tag == "err":
                    stderr_tail.append(line.rstrip())
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, ("out", line))
            loop.call_soon_threadsafe(queue.put_nowait, (f"eof-{tag}", None))

        threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
        for thread in threads:
            thread.start()
        prompt = request.prompt + "\n"
        try:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

        deadline = time.monotonic() + self.config.timeout_s
        result: dict[str, Any] | None = None
        errors: list[str] = []
        open_streams = 2
        try:
            while open_streams:
                if cancelled():
                    raise AgentFailure("cancelled", "The run was cancelled.")
                if time.monotonic() > deadline:
                    raise AgentFailure("timeout", f"Gemini did not finish within {self.config.timeout_s} seconds.")
                try:
                    tag, line = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    continue
                if tag.startswith("eof"):
                    open_streams -= 1
                    continue
                event = parse_line(line or "")
                mapped = map_event(event) if event else None
                if mapped is None:
                    continue
                if mapped.kind == "agent_result":
                    result = mapped.payload
                elif mapped.kind == "agent_error":
                    errors.append(str(mapped.payload.get("message") or ""))
                    await emit("warning", {"message": redact(str(mapped.payload.get("message") or ""), request.run_token)})
                else:
                    await emit(mapped.kind, mapped.payload)
            await asyncio.to_thread(proc.wait, 30)
        finally:
            if proc.poll() is None:
                kill_tree(proc.pid)
        if result and result.get("status") == "success":
            await emit("agent_stats", {"stats": result.get("stats") or {}, "exit_code": proc.returncode})
            return
        detail = " ".join(filter(None, [*(errors or []), (result or {}).get("error") or "", *list(stderr_tail)[-8:]]))
        code, message = classify(detail)
        await emit("diagnostic", {"exit_code": proc.returncode, "detail": redact(detail[-1500:], request.run_token),
                                  "at": datetime.now(UTC).isoformat()})
        raise AgentFailure(code, message)


def policy_toml(scopes: list[str]) -> str:
    """Headless Gemini CLI denies any tool whose policy would ask the user. Allow exactly Wizard's read-only MCP servers
    and deny every other MCP server; built-in tools are already removed by tools.core = []."""
    rules = ["# Written by Wizard for each run. Only Wizard's read-only MCP servers may be called."]
    for scope in scopes:
        rules.append(f'[[rule]]\ntoolName = "*"\nmcpName = "{scope}"\ndecision = "allow"\npriority = 900\n')
    rules.append('[[rule]]\ntoolName = "*"\nmcpName = "*"\ndecision = "deny"\npriority = 100\n')
    return "\n".join(rules)


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return re.sub(r"(ya29\.[A-Za-z0-9_\-]+|1//[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,})", "[redacted]", text)


def kill_tree(pid: int) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(pid, signal.SIGKILL)

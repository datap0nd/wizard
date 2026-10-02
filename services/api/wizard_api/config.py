"""Configuration from environment variables, optionally seeded from a .env file (environment wins).

Every setting is validated at start-up; an invalid value stops the service with a clear message instead of failing on
the first executive question."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from wizard_connectors.paths import FIXTURES, ROOT

RUNTIMES = ("gemini-cli", "code-assist", "replay")
AUTH_MODES = ("fixture", "trusted-header")


class ConfigError(ValueError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8770
    public_origin: str | None = None
    runtime: str = "replay"
    model: str = "gemini-3.8-flash"
    thinking: str = "high"
    gemini_cli_js: str | None = None
    node: str | None = None
    gemini_fake_responses: str | None = None
    google_cloud_project: str | None = None
    auth_mode: str = "fixture"
    identity_header: str = "X-Forwarded-Email"
    trusted_proxies: set[str] = field(default_factory=lambda: {"127.0.0.1", "::1"})
    identities_file: Path = FIXTURES / "identities.json"
    transcripts_dir: Path = FIXTURES / "transcripts"
    web_dist: Path = ROOT / "apps" / "web" / "dist"
    content_dir: Path | None = None
    max_concurrent_runs: int = 4
    run_timeout_s: int = 600
    max_tool_calls: int = 40
    require_google_email_match: bool = True
    report_retention_days: int = 30
    secure_cookies: bool = False
    replay_delay_s: float = 0.0
    session_hours: int = 12
    local_user_email: str | None = None
    local_user_name: str | None = None
    session_secret: bytes = b""

    @property
    def internal_url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::", "") else self.host  # noqa: S104 - comparison, not binding
        return f"http://{host}:{self.port}"

    def user_home(self, user_id: str) -> Path:
        import hashlib
        return self.data_dir / "users" / hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:20]


def _bool(value: str, name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false")


def _int(value: str, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number") from None
    if not low <= number <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return number


def load_settings(env: dict[str, str] | None = None, env_file: Path | None = None, home: Path | None = None) -> Settings:
    """`home` is a work-PC install folder: .env lives there and relative paths (data, content, identities) resolve
    against it, so they survive updates. Without it, a development checkout uses the repository root."""
    base = Path(home).resolve() if home else ROOT
    merged = read_env_file(env_file or base / ".env")
    merged.update({k: v for k, v in (env if env is not None else os.environ).items() if k.startswith(("WIZARD_", "GOOGLE_CLOUD_PROJECT"))})

    def get(name: str, default: str | None = None) -> str | None:
        value = merged.get(name)
        return value if value not in (None, "") else default

    def local(path: str) -> Path:
        candidate = Path(path)
        return (candidate if candidate.is_absolute() else base / candidate).resolve()

    data_dir = local(get("WIZARD_DATA_DIR", "data" if home else "var") or "var")
    settings = Settings(data_dir=data_dir)
    settings.host = get("WIZARD_HOST", settings.host) or settings.host
    settings.port = _int(get("WIZARD_PORT", "8770") or "8770", "WIZARD_PORT", 1, 65535)
    settings.public_origin = get("WIZARD_PUBLIC_ORIGIN")
    settings.runtime = get("WIZARD_AGENT_RUNTIME", "replay") or "replay"
    if settings.runtime not in RUNTIMES:
        raise ConfigError(f"WIZARD_AGENT_RUNTIME must be one of {', '.join(RUNTIMES)}")
    settings.model = get("WIZARD_GEMINI_MODEL", settings.model) or settings.model
    settings.thinking = get("WIZARD_GEMINI_THINKING", "high") or "high"
    if settings.thinking not in ("high", "low", "none"):
        raise ConfigError("WIZARD_GEMINI_THINKING must be high, low or none")
    settings.gemini_cli_js = get("WIZARD_GEMINI_CLI_JS")
    settings.node = get("WIZARD_NODE")
    settings.gemini_fake_responses = get("WIZARD_GEMINI_FAKE_RESPONSES")
    settings.google_cloud_project = get("WIZARD_GOOGLE_CLOUD_PROJECT") or get("GOOGLE_CLOUD_PROJECT")
    settings.auth_mode = get("WIZARD_AUTH_MODE", "fixture") or "fixture"
    if settings.auth_mode not in AUTH_MODES:
        raise ConfigError(f"WIZARD_AUTH_MODE must be one of {', '.join(AUTH_MODES)}")
    settings.identity_header = get("WIZARD_IDENTITY_HEADER", settings.identity_header) or settings.identity_header
    proxies = get("WIZARD_TRUSTED_PROXIES")
    if proxies:
        settings.trusted_proxies = {p.strip() for p in proxies.split(",") if p.strip()}
    identities = get("WIZARD_IDENTITIES_FILE")
    if identities:
        settings.identities_file = local(identities)
    transcripts = get("WIZARD_TRANSCRIPTS_DIR")
    if transcripts:
        settings.transcripts_dir = Path(transcripts)
    content = get("WIZARD_CONTENT_DIR")
    if content:
        settings.content_dir = local(content)
        if settings.runtime == "replay":
            raise ConfigError("WIZARD_CONTENT_DIR cannot be combined with the replay runtime: replay plays recorded "
                              "transcripts over the synthetic catalog. Use gemini-cli or code-assist.")
    settings.local_user_email = get("WIZARD_LOCAL_USER_EMAIL")
    if settings.local_user_email and "@" not in settings.local_user_email:
        raise ConfigError("WIZARD_LOCAL_USER_EMAIL must be your work email address")
    settings.local_user_name = get("WIZARD_LOCAL_USER_NAME") or (settings.local_user_email or "").split("@")[0] or None
    dist = get("WIZARD_WEB_DIST")
    if dist:
        settings.web_dist = Path(dist)
    settings.max_concurrent_runs = _int(get("WIZARD_MAX_CONCURRENT_RUNS", "4") or "4", "WIZARD_MAX_CONCURRENT_RUNS", 1, 64)
    settings.run_timeout_s = _int(get("WIZARD_RUN_TIMEOUT_S", "600") or "600", "WIZARD_RUN_TIMEOUT_S", 10, 3600)
    settings.max_tool_calls = _int(get("WIZARD_MAX_TOOL_CALLS", "40") or "40", "WIZARD_MAX_TOOL_CALLS", 1, 200)
    settings.require_google_email_match = _bool(get("WIZARD_REQUIRE_GOOGLE_EMAIL_MATCH", "true") or "true",
                                                "WIZARD_REQUIRE_GOOGLE_EMAIL_MATCH")
    settings.report_retention_days = _int(get("WIZARD_REPORT_RETENTION_DAYS", "30") or "30", "WIZARD_REPORT_RETENTION_DAYS", 1, 3650)
    settings.secure_cookies = _bool(get("WIZARD_SECURE_COOKIES", "false") or "false", "WIZARD_SECURE_COOKIES")
    settings.replay_delay_s = float(get("WIZARD_REPLAY_DELAY_S", "0") or "0")
    if settings.auth_mode == "trusted-header" and settings.runtime != "replay" and not settings.public_origin:
        raise ConfigError("WIZARD_PUBLIC_ORIGIN is required behind a corporate SSO proxy")
    settings.session_secret = _session_secret(data_dir)
    return settings


def _session_secret(data_dir: Path) -> bytes:
    path = data_dir / "secrets" / "session.key"
    if path.is_file():
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_text(key.hex(), encoding="ascii")
    return key

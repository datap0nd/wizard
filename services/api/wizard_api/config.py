"""Configuration from environment variables, optionally seeded from a .env file (environment wins).

Every setting is validated at start-up; an invalid value stops the service with a clear message instead of failing on
the first executive question."""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wizard_connectors.metronome import MetronomeConfigError, MetronomeSettings
from wizard_connectors.metronome import settings_from as metronome_settings
from wizard_connectors.paths import FIXTURES, ROOT
from wizard_connectors.pg import PgError, PgSettings
from wizard_connectors.pg import settings_from as pg_settings
from wizard_connectors.portals import PortalConfigError, PortalSettings
from wizard_connectors.portals import settings_from as portal_settings

from . import knowledge_sync, provisioning

RUNTIMES = ("gemini-cli", "code-assist", "replay")
# Saved by the in-app model picker, which was removed: ignored in this PC's settings layer.
PICKER_KEYS = ("WIZARD_GEMINI_MODEL", "WIZARD_GEMINI_FALLBACK_MODEL")
KB_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
KB_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,200}$")
KB_PATH = re.compile(r"^[A-Za-z0-9_. /\\-]{1,200}$")
SITE_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~%/-]*)?$")
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
    # Used for the rest of an answer when Google has no capacity for the chosen model or its quota is used up. As in
    # Gemini CLI, Flash and Pro stand in for each other (owner, 20 Oct 2026: "fall back to Pro, 3.1 Pro preview").
    fallback_model: str | None = "gemini-3.1-pro-preview"
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
    # Folder of standalone HTML reports (local files for now). Configured only; no tool reads it yet.
    html_reports_dir: Path | None = None
    # Files people attach to questions: "From this PC" lists these folders (local installs; empty behind an SSO proxy,
    # where the server's folders are not the user's), uploads are capped, and each conversion has a time limit.
    attachment_folders: list[Path] = field(default_factory=list)
    max_attachment_mb: int = 50
    attachment_timeout_s: int = 180
    attachment_office: str = "auto"  # "never": read only plain Office Open XML files, without starting Office (tests)
    # Read-only PostgreSQL account for wizard_query_postgresql (WIZARD_PG_* in .env, else the PG* variables); None = not set.
    postgres: PgSettings | None = None
    # The name people see for that database in the app (the systems stage, sources, evidence).
    pg_name: str = "AI Team Database"
    # The news table the Brain page shows (schema.name, optionally in another database); None: found by its name.
    news_table: str | None = None
    news_database: str | None = None
    # Backstops against a runaway run, not a budget for a normal answer: Gemini may take its time and many calls. A run
    # is steered to answer by the loop and time checks in runs.py long before it is cut off.
    max_concurrent_runs: int = 8
    run_timeout_s: int = 1800
    max_tool_calls: int = 150
    require_google_email_match: bool = True
    report_retention_days: int = 30
    secure_cookies: bool = False
    replay_delay_s: float = 0.0
    session_hours: int = 12
    local_user_email: str | None = None
    local_user_name: str | None = None
    # A work-PC install (run.py --home): the person at this PC is the Owner, whatever Google account they link.
    install_mode: bool = False
    # Outbound proxy for Google: a URL, "direct", or None to resolve it (env, Gemini CLI settings, Windows/PAC).
    proxy: str | None = None
    # The company GitHub (knowledge base, portal maps): a URL, "direct", or None for the route Windows and Edge take
    # (outbound.windows_route). WIZARD_PROXY and Gemini CLI's proxy are for Google and do not apply there.
    github_proxy: str | None = None
    # Dev mode: show every run's full diagnostics and the server log in the UI (WIZARD_DIAGNOSTICS=false to hide).
    diagnostics: bool = True
    session_secret: bytes = b""
    # The desktop app (run.py --desktop, started by WizardBar): only the person at this PC signs in, and the bar restarts
    # the service when it exits with RESTART_EXIT_CODE (a new knowledge-base version is applied while idle).
    desktop: bool = False
    # Shared secret for /internal/v1/desktop/*, generated by WizardBar for each launch and passed in the environment.
    control_token: str | None = None
    # Knowledge base synced from a private GitHub repository (WIZARD_KB_*, usually from the provisioning file).
    kb_repo: str | None = None
    kb_ref: str = "main"
    kb_path: str = ""
    kb_token: str | None = None
    # The knowledge base's write token, entered on this PC only: Wizard publishes its portal maps with it.
    kb_write_token: str | None = None
    kb_sync_minutes: int = 30
    # The Pages site (owner, 30 Oct 2026): Brain and Cases, two pages of their own on GitHub Pages, published from this PC
    # with the knowledge base's write token to a branch that is not the notes' own (WIZARD_SITE_*). The repository
    # defaults to the knowledge base's; the address is the one GitHub shows under Settings → Pages.
    site_repo: str | None = None
    site_branch: str = "gh-pages"
    site_url: str | None = None
    # Google accounts allowed to link for Gemini (company domains); empty: any account that matches the user's email rule.
    # Also the only domains a recurring extraction may be emailed to (else the requester's own).
    google_domains: list[str] = field(default_factory=list)
    # Metronome, which runs recurring extractions as Flows owned by its Wizard user (WIZARD_METRONOME_*); None = not set.
    metronome: MetronomeSettings | None = None
    # Company portals Gemini reads in the person's own Wizard browser (WIZARD_PORTAL_*, WIZARD_BROWSER); None = not set.
    # Only on a single-person PC: the browser runs where Wizard runs, signed in as the person at that PC.
    portals: PortalSettings | None = None
    # Names (never values) of what the provisioning file set, for readiness views.
    provision: dict[str, Any] = field(default_factory=dict)
    # A work-PC or desktop install folder (run.py --home) and its .env: the settings pane edits only such installs.
    home: Path | None = None
    env_file: Path | None = None

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
    # Organisation settings from an imported provisioning file, then this PC's choices from the settings pane, sit
    # underneath the PC's own .env and environment.
    provisioned = provisioning.load(data_dir)
    chosen = provisioning.load(data_dir, layer="local")
    # The in-app model picker is gone (owner, 20 Oct 2026: Gemini 3.8 Flash for everyone). A model saved with it on
    # this PC no longer applies; the company file, .env or the environment can still set one.
    picked = {k: v for k, v in (chosen.values() if chosen else {}).items() if k not in PICKER_KEYS}
    stored = {**(provisioned.values() if provisioned else {}), **picked}
    if stored:
        merged = {**stored, **{k: v for k, v in merged.items() if v not in (None, "")}}
    settings = Settings(data_dir=data_dir)
    settings.home = base if home else None
    settings.env_file = env_file or base / ".env"
    settings.provision = provisioning.status(data_dir) if provisioned else {"imported": False}
    settings.host = get("WIZARD_HOST", settings.host) or settings.host
    settings.port = _int(get("WIZARD_PORT", "8770") or "8770", "WIZARD_PORT", 1, 65535)
    settings.public_origin = get("WIZARD_PUBLIC_ORIGIN")
    settings.runtime = get("WIZARD_AGENT_RUNTIME", "replay") or "replay"
    if settings.runtime not in RUNTIMES:
        raise ConfigError(f"WIZARD_AGENT_RUNTIME must be one of {', '.join(RUNTIMES)}")
    settings.model = get("WIZARD_GEMINI_MODEL", settings.model) or settings.model
    fallback = get("WIZARD_GEMINI_FALLBACK_MODEL")
    if fallback is not None:
        settings.fallback_model = None if fallback.strip().lower() in ("", "none") else fallback.strip()
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
    html_reports = get("WIZARD_HTML_REPORTS_DIR")
    if html_reports:
        settings.html_reports_dir = local(html_reports)
        if not settings.html_reports_dir.is_dir():
            raise ConfigError(f"WIZARD_HTML_REPORTS_DIR {settings.html_reports_dir} is not a folder. Point it at the folder "
                              "that holds the HTML reports, or remove the line.")
    settings.local_user_email = get("WIZARD_LOCAL_USER_EMAIL")
    if settings.local_user_email and "@" not in settings.local_user_email:
        raise ConfigError("WIZARD_LOCAL_USER_EMAIL must be your work email address")
    settings.local_user_name = get("WIZARD_LOCAL_USER_NAME") or (settings.local_user_email or "").split("@")[0] or None
    settings.install_mode = home is not None
    settings.proxy = get("WIZARD_PROXY") or None
    settings.github_proxy = get("WIZARD_GITHUB_PROXY") or None
    settings.diagnostics = _bool(get("WIZARD_DIAGNOSTICS", "true") or "true", "WIZARD_DIAGNOSTICS")
    dist = get("WIZARD_WEB_DIST")
    if dist:
        settings.web_dist = Path(dist)
    folders = get("WIZARD_ATTACHMENT_FOLDERS")
    if folders is None and settings.auth_mode == "fixture":
        settings.attachment_folders = [p for p in (Path.home() / n for n in ("Downloads", "Desktop", "Documents")) if p.is_dir()]
    elif folders and folders.strip().lower() != "none":
        settings.attachment_folders = [local(f.strip()) for f in folders.split(";") if f.strip()]
        missing = [str(f) for f in settings.attachment_folders if not f.is_dir()]
        if missing:
            raise ConfigError(f"WIZARD_ATTACHMENT_FOLDERS: {', '.join(missing)} is not a folder (separate folders with ;)")
    settings.attachment_office = get("WIZARD_ATTACHMENT_OFFICE", "auto") or "auto"
    if settings.attachment_office not in ("auto", "never"):
        raise ConfigError("WIZARD_ATTACHMENT_OFFICE must be auto or never")
    settings.max_attachment_mb = _int(get("WIZARD_MAX_ATTACHMENT_MB", "50") or "50", "WIZARD_MAX_ATTACHMENT_MB", 1, 500)
    settings.attachment_timeout_s = _int(get("WIZARD_ATTACHMENT_TIMEOUT_S", "180") or "180", "WIZARD_ATTACHMENT_TIMEOUT_S",
                                         10, 3600)
    try:
        source_env = env if env is not None else os.environ
        settings.postgres = pg_settings({k: v for k, v in merged.items() if k.startswith("WIZARD_PG_")},
                                        {k: v for k, v in source_env.items() if k.startswith("PG")})
    except PgError as error:
        raise ConfigError(f"PostgreSQL settings: {error}") from None
    settings.pg_name = (get("WIZARD_PG_NAME", "AI Team Database") or "AI Team Database").strip()[:60]
    # Checked where the Brain page reads them (brain.py), which says what is wrong: a showcase page never stops Wizard.
    settings.news_table = (get("WIZARD_NEWS_TABLE") or "").strip() or None
    settings.news_database = (get("WIZARD_NEWS_DATABASE") or "").strip() or None
    settings.max_concurrent_runs = _int(get("WIZARD_MAX_CONCURRENT_RUNS", "8") or "8", "WIZARD_MAX_CONCURRENT_RUNS", 1, 64)
    settings.run_timeout_s = _int(get("WIZARD_RUN_TIMEOUT_S", "1800") or "1800", "WIZARD_RUN_TIMEOUT_S", 10, 3600)
    settings.max_tool_calls = _int(get("WIZARD_MAX_TOOL_CALLS", "150") or "150", "WIZARD_MAX_TOOL_CALLS", 1, 500)
    settings.require_google_email_match = _bool(get("WIZARD_REQUIRE_GOOGLE_EMAIL_MATCH", "true") or "true",
                                                "WIZARD_REQUIRE_GOOGLE_EMAIL_MATCH")
    settings.report_retention_days = _int(get("WIZARD_REPORT_RETENTION_DAYS", "30") or "30", "WIZARD_REPORT_RETENTION_DAYS", 1, 3650)
    settings.secure_cookies = _bool(get("WIZARD_SECURE_COOKIES", "false") or "false", "WIZARD_SECURE_COOKIES")
    settings.replay_delay_s = float(get("WIZARD_REPLAY_DELAY_S", "0") or "0")
    settings.control_token = get("WIZARD_CONTROL_TOKEN")
    if settings.control_token and len(settings.control_token) < 32:
        raise ConfigError("WIZARD_CONTROL_TOKEN must be at least 32 characters")
    settings.kb_repo = get("WIZARD_KB_REPO")
    if settings.kb_repo and not KB_REPO.match(settings.kb_repo):
        raise ConfigError("WIZARD_KB_REPO must be owner/name, for example acme/wizard-content")
    settings.kb_ref = get("WIZARD_KB_REF", "main") or "main"
    if not KB_REF.match(settings.kb_ref):
        raise ConfigError("WIZARD_KB_REF must be a branch, tag or commit name")
    settings.kb_path = (get("WIZARD_KB_PATH", "") or "").strip("/\\")
    if settings.kb_path and (".." in settings.kb_path.replace("\\", "/").split("/") or not KB_PATH.match(settings.kb_path)):
        raise ConfigError("WIZARD_KB_PATH must be a folder inside the repository, for example content")
    settings.kb_token = get("WIZARD_KB_TOKEN")
    settings.kb_write_token = get("WIZARD_KB_WRITE_TOKEN")
    settings.kb_sync_minutes = _int(get("WIZARD_KB_SYNC_MINUTES", "30") or "30", "WIZARD_KB_SYNC_MINUTES", 0, 1440)
    settings.site_repo = get("WIZARD_SITE_REPO") or settings.kb_repo
    if settings.site_repo and not KB_REPO.match(settings.site_repo):
        raise ConfigError("WIZARD_SITE_REPO must be owner/name, for example acme/wizard-content")
    settings.site_branch = get("WIZARD_SITE_BRANCH", "gh-pages") or "gh-pages"
    if not KB_REF.match(settings.site_branch):
        raise ConfigError("WIZARD_SITE_BRANCH must be a branch name, for example gh-pages")
    if settings.site_repo and settings.site_repo == settings.kb_repo and settings.site_branch == settings.kb_ref:
        raise ConfigError("WIZARD_SITE_BRANCH must not be the knowledge base's own branch: every PC would download the site "
                          "with the notes. Use gh-pages.")
    site_url = (get("WIZARD_SITE_URL", "") or "").strip()
    if site_url and not SITE_URL.match(site_url):
        raise ConfigError("WIZARD_SITE_URL must be the https:// address GitHub shows under Settings → Pages")
    settings.site_url = site_url.rstrip("/") + "/" if site_url else None
    if settings.kb_repo and settings.content_dir:
        raise ConfigError("Set either WIZARD_KB_REPO (synced knowledge base) or WIZARD_CONTENT_DIR (a local folder), not both")
    if settings.kb_repo and settings.runtime == "replay":
        raise ConfigError("WIZARD_KB_REPO cannot be combined with the replay runtime: replay plays recorded transcripts over "
                          "the synthetic catalog. Use code-assist or gemini-cli.")
    if settings.kb_repo:
        # The last validated snapshot; None until the first sync succeeds (create_app then loads no content at all,
        # never the synthetic examples).
        settings.content_dir = knowledge_sync.active_content(data_dir, kb_source(settings))
    domains = get("WIZARD_GOOGLE_DOMAINS", "") or ""
    settings.google_domains = sorted({d.strip().lower().lstrip("@") for d in domains.split(",") if d.strip()})
    try:
        settings.metronome = metronome_settings(get("WIZARD_METRONOME_URL"), get("WIZARD_METRONOME_CLIENT_KEY"),
                                                get("WIZARD_METRONOME_USER"))
    except MetronomeConfigError as error:
        raise ConfigError(str(error)) from None
    try:
        settings.portals = portal_settings({**{k: v for k, v in merged.items() if k.startswith(("WIZARD_PORTAL_", "WIZARD_BROWSER"))},
                                            "WIZARD_BROWSER_EXECUTABLE": (env if env is not None else os.environ).get(
                                                "WIZARD_BROWSER_EXECUTABLE") or read_env_file(env_file or base / ".env").get(
                                                "WIZARD_BROWSER_EXECUTABLE")})
    except PortalConfigError as error:
        raise ConfigError(str(error)) from None
    if settings.portals and settings.auth_mode != "fixture":
        raise ConfigError("The company portals (WIZARD_PORTAL_*) run in each person's own browser, so only the desktop app "
                          "or a work-PC install can use them, not a shared server behind SSO.")
    if settings.auth_mode == "trusted-header" and settings.runtime != "replay" and not settings.public_origin:
        raise ConfigError("WIZARD_PUBLIC_ORIGIN is required behind a corporate SSO proxy")
    settings.session_secret = _session_secret(data_dir)
    return settings


def kb_source(settings: Settings) -> knowledge_sync.Source | None:
    if not settings.kb_repo:
        return None
    return knowledge_sync.Source(settings.kb_repo, settings.kb_ref, settings.kb_path, settings.kb_token)


def _session_secret(data_dir: Path) -> bytes:
    path = data_dir / "secrets" / "session.key"
    if path.is_file():
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_text(key.hex(), encoding="ascii")
    return key

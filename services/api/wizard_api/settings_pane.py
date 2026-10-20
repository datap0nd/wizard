"""The settings pane: the company settings a person may change on their own PC (Gemini model and project, the knowledge
base, the read-only database, the proxy), where each value comes from, saving, and connection tests.

Values are saved to this PC's store (provisioning.update_local; secrets through the SecretBox). A key that the PC's .env
also sets is removed from .env on save, so the new value applies and no password stays there in plain text. A key set
in the environment is shown but cannot be changed here. A secret is never sent back: the pane only learns whether it is
set. Every save is validated by loading the settings again; an invalid change is rolled back."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors.pg import PgError, PgSettings
from wizard_connectors.pg import settings_from as pg_settings

from . import knowledge_sync, provisioning
from .config import ConfigError, Settings, load_settings, read_env_file

MODEL = re.compile(r"^[a-z0-9][a-z0-9.\-]{2,79}$")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    section: str
    help: str = ""
    placeholder: str = ""
    choices: tuple[str, ...] = ()

    @property
    def secret(self) -> bool:
        return provisioning.is_secret(self.key)


SECTIONS = [
    ("gemini", "Gemini", "The model answers under your own Google sign-in."),
    ("knowledge", "Knowledge base", "The private GitHub repository Wizard reads its company notes from."),
    ("postgres", "Company database", "A read-only PostgreSQL account for Gemini's SQL questions."),
    ("network", "Network", "Only if Wizard cannot reach Google or GitHub on its own."),
]
FIELDS = [
    Field("WIZARD_GEMINI_MODEL", "Model", "gemini", "Takes effect on the next question.", "gemini-3.8-flash"),
    Field("WIZARD_GEMINI_FALLBACK_MODEL", "Fallback model", "gemini",
          "Answers instead when Google has no capacity for the model above or its quota is used up. none: no fallback.",
          "gemini-3.8-flash"),
    Field("GOOGLE_CLOUD_PROJECT", "Google Cloud project", "gemini", "Your organisation's Gemini project, if it has one."),
    Field("WIZARD_GOOGLE_DOMAINS", "Company Google domains", "gemini", "Only these accounts may link, e.g. company.com.",
          "company.com"),
    Field("WIZARD_KB_REPO", "Repository", "knowledge", "owner/name of the private repository.", "acme/wizard-content"),
    Field("WIZARD_KB_TOKEN", "Read-only token", "knowledge", "Fine-grained token: that repository only, Contents read.",
          "github_pat_…"),
    Field("WIZARD_KB_REF", "Branch", "knowledge", "", "main"),
    Field("WIZARD_KB_PATH", "Folder in the repository", "knowledge", "Leave empty when the notes are at the root.", ""),
    Field("WIZARD_KB_SYNC_MINUTES", "Check for changes every (minutes)", "knowledge", "0 checks only at start-up.", "30"),
    Field("WIZARD_PG_NAME", "Name people see", "postgres", "Shown in the app and in answers' sources.", "AI Team Database"),
    Field("WIZARD_PG_HOST", "Server", "postgres", "", "db.company.example"),
    Field("WIZARD_PG_PORT", "Port", "postgres", "", "5432"),
    Field("WIZARD_PG_DATABASE", "Database", "postgres", "", "postgres"),
    Field("WIZARD_PG_USER", "User (read-only)", "postgres", "", "wizard_ro"),
    Field("WIZARD_PG_PASSWORD", "Password", "postgres"),
    Field("WIZARD_PG_SSLMODE", "SSL", "postgres", "", "prefer",
          ("disable", "prefer", "require", "verify-ca", "verify-full")),
    Field("WIZARD_PROXY", "Proxy", "network", "http://host:port, or direct. Empty: the Windows proxy settings.", ""),
]
BY_KEY = {f.key: f for f in FIELDS}


class PaneError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def editable(settings: Settings) -> bool:
    """Only a single-person install edits its own settings: never a shared server behind SSO."""
    return settings.home is not None and settings.auth_mode == "fixture" and (settings.install_mode or settings.desktop)


def _environ() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(("WIZARD_", "GOOGLE_CLOUD_PROJECT")) and v}


def _layers(settings: Settings) -> list[tuple[str, dict[str, str]]]:
    """(source, values) from the strongest to the weakest."""
    env_file = read_env_file(settings.env_file) if settings.env_file else {}
    local = provisioning.load(settings.data_dir, layer="local")
    company = provisioning.load(settings.data_dir)
    return [("environment", _environ()), ("env_file", {k: v for k, v in env_file.items() if v}),
            ("this_pc", local.values() if local else {}), ("company", company.values() if company else {})]


def describe(settings: Settings) -> dict[str, Any]:
    layers = _layers(settings)
    fields = []
    for f in FIELDS:
        source, value = next(((name, values[f.key]) for name, values in layers if f.key in values), ("default", ""))
        if f.key == "WIZARD_GEMINI_MODEL" and source == "default":
            value = settings.model
        if f.key == "WIZARD_GEMINI_FALLBACK_MODEL" and source == "default":
            value = settings.fallback_model or ""
        from_company = next((values.get(f.key) for name, values in layers if name == "company"), None)
        fields.append({"key": f.key, "label": f.label, "section": f.section, "help": f.help, "placeholder": f.placeholder,
                       "choices": list(f.choices), "secret": f.secret, "source": source,
                       "value": None if f.secret else value, "set": bool(value),
                       "company_value": bool(from_company) if f.secret else from_company,
                       "editable": source != "environment"})
    company_file = provisioning.status(settings.data_dir)
    return {"sections": [{"id": i, "title": t, "about": a} for i, t, a in SECTIONS], "fields": fields,
            "company_file": {"name": company_file.get("name"), "imported_at": company_file.get("imported_at")}
            if company_file.get("imported") else None,
            "restart": "automatic" if settings.desktop else "manual"}


def _clean(changes: dict[str, Any]) -> dict[str, str | None]:
    cleaned: dict[str, str | None] = {}
    for key, value in changes.items():
        if key not in BY_KEY:
            raise PaneError(f"{key} is not a setting the pane can change")
        if value is not None and not isinstance(value, str | int):
            raise PaneError(f"{key} must be text")
        text = None if value is None else str(value).strip()
        if text and ("\n" in text or "\r" in text or len(text) > 2000):
            raise PaneError(f"{key} must be one line")
        field = BY_KEY[key]
        if text and field.choices and text not in field.choices:
            raise PaneError(f"{field.label} must be one of {', '.join(field.choices)}")
        if text and key in ("WIZARD_GEMINI_MODEL", "WIZARD_GEMINI_FALLBACK_MODEL") and not MODEL.match(text):
            raise PaneError("The model name looks wrong: use the id Gemini shows, e.g. gemini-3.1-pro")
        cleaned[key] = text
    return cleaned


def _remove_from_env_file(path: Path, keys: set[str]) -> bool:
    if not keys or not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    kept = [line for line in lines if not (("=" in line) and line.split("=", 1)[0].strip() in keys
                                           and not line.lstrip().startswith("#"))]
    if len(kept) == len(lines):
        return False
    path.write_text("".join(kept), encoding="utf-8")
    return True


def save(settings: Settings, changes: dict[str, Any]) -> dict[str, Any]:
    """Save changes (None = keep a secret as it is; "" = back to the company value or the default). Returns the keys
    that were written. Raises PaneError when the result would not load."""
    cleaned = _clean(changes)
    environ = _environ()
    locked = [k for k in cleaned if k in environ]
    if locked:
        raise PaneError(f"{', '.join(locked)} is set by an environment variable on this PC; change it there", 409)
    updates = {k: v for k, v in cleaned.items() if not (BY_KEY[k].secret and v is None)}
    if not updates:
        return {"changed": []}
    local_folder = provisioning.folder(settings.data_dir, "local")
    backup = local_folder.with_name(local_folder.name + ".previous")
    shutil.rmtree(backup, ignore_errors=True)
    if local_folder.is_dir():
        shutil.copytree(local_folder, backup)
    env_text = settings.env_file.read_text(encoding="utf-8-sig") if settings.env_file and settings.env_file.is_file() else None
    try:
        provisioning.update_local(settings.data_dir, updates)
        if settings.env_file:
            _remove_from_env_file(settings.env_file, set(updates))
        load_settings(home=settings.home)
    except (ConfigError, provisioning.ProvisionError) as error:
        shutil.rmtree(local_folder, ignore_errors=True)
        if backup.is_dir():
            backup.rename(local_folder)
        if env_text is not None and settings.env_file:
            settings.env_file.write_text(env_text, encoding="utf-8")
        raise PaneError(f"Not saved: {error}") from None
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    return {"changed": sorted(updates)}


def _candidate(settings: Settings, proposed: dict[str, Any]) -> dict[str, str]:
    """Effective values if the proposed changes were saved (a secret left empty keeps the stored one)."""
    cleaned = _clean(proposed)
    values: dict[str, str] = {}
    for _, layer in reversed(_layers(settings)):
        values.update(layer)
    for key, value in cleaned.items():
        if value is None and BY_KEY[key].secret:
            continue
        if value:
            values[key] = value
        else:
            values.pop(key, None)
    return values


def test_postgres(settings: Settings, proposed: dict[str, Any]) -> dict[str, Any]:
    from wizard_connectors.pg import Pg8000Session
    values = _candidate(settings, proposed)
    try:
        target: PgSettings | None = pg_settings({k: v for k, v in values.items() if k.startswith("WIZARD_PG_")}, {})
    except PgError as error:
        return {"ok": False, "message": str(error)}
    if target is None:
        return {"ok": False, "message": "Fill in at least the server and the user."}
    try:
        session = Pg8000Session(target, application_name="wizard-settings-test")
        row = session.rows("SELECT current_user AS who, current_setting('transaction_read_only') AS ro, version() AS v")[0]
        session.close()
    except PgError as error:
        return {"ok": False, "message": f"Could not connect: {error}"}
    return {"ok": True, "message": f"Connected as {row['who']} to {target.database} on {target.host}; this session is "
                                   f"read-only: {row['ro']}. {str(row['v']).split(',')[0]}."}


def test_knowledge(settings: Settings, proposed: dict[str, Any],
                   transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    values = _candidate(settings, proposed)
    repo, token = values.get("WIZARD_KB_REPO"), values.get("WIZARD_KB_TOKEN")
    if not repo or not token:
        return {"ok": False, "message": "Fill in the repository and the token."}
    source = knowledge_sync.Source(repo, values.get("WIZARD_KB_REF") or "main", (values.get("WIZARD_KB_PATH") or "").strip("/\\"),
                                   token)
    result = knowledge_sync.check(source, proxy=values.get("WIZARD_PROXY") or settings.proxy, transport=transport)
    return {"ok": result.ok, "message": result.message}


RELEASE = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/"


def installed_build() -> dict[str, Any]:
    from wizard_connectors.paths import ROOT
    try:
        record = json.loads((ROOT / "BUILD.json").read_text(encoding="utf-8"))
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def _version(text: object) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(text).split("."))
    except ValueError:
        return ()


def check_update(settings: Settings, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """The newest desktop release against this build. Only reads the public release manifest."""
    build = installed_build()
    installed = build.get("version")
    url = RELEASE + "wizard-desktop.json"
    result: dict[str, Any] = {"installed": installed, "commit": build.get("commit"), "download": RELEASE + "WizardSetup.exe"}
    try:
        if transport is not None:
            client = httpx.Client(transport=transport, timeout=30, follow_redirects=True)
        else:
            route, _ = outbound.proxy_for(url, settings.proxy)
            client = httpx.Client(timeout=30, verify=outbound.ssl_context(), proxy=route, trust_env=False, follow_redirects=True)
        with client:
            response = client.get(url, headers={"User-Agent": "Wizard"})
            response.raise_for_status()
            manifest = response.json()
    except (httpx.HTTPError, ValueError) as error:
        return {**result, "ok": False, "message": f"Could not read the release: {error}"}
    latest = manifest.get("version") if isinstance(manifest, dict) else None
    available = bool(_version(latest)) and (not _version(installed) or _version(latest) > _version(installed))
    return {**result, "ok": True, "latest": latest, "latest_commit": manifest.get("commit"), "available": available,
            "message": (f"Version {latest} is available." if available else f"You have the latest version ({installed}).")
            if installed else f"The latest release is {latest}; this copy was not installed from a release."}

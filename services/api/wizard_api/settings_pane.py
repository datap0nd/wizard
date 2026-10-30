"""The settings pane: the company settings a person may change on their own PC (Gemini model and project, the knowledge
base, the read-only database, Metronome, the portals, the proxy), where each value comes from, saving, and connection
tests.

Values are saved to this PC's store (provisioning.update_local; secrets through the SecretBox). A key that the PC's .env
also sets is removed from .env on save, so the new value applies and no password stays there in plain text. A key set
in the environment is shown but cannot be changed here. A secret is never sent back: the pane only learns whether it is
set. Every save is validated by loading the settings again; an invalid change is rolled back."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors.metronome import MetronomeConfigError
from wizard_connectors.metronome import settings_from as metronome_settings
from wizard_connectors.pg import PgError, PgSettings
from wizard_connectors.pg import settings_from as pg_settings

from . import knowledge_sync, provisioning
from .config import ConfigError, Settings, load_settings, read_env_file
from .metronome_client import MetronomeClient


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
    ("metronome", "Metronome", "Recurring extractions: Metronome emails a table on a schedule, as Flows owned by its "
                               "Wizard user."),
    ("portals", "Portals", "ASAP, GSCM and the Big Data Portal (its information catalog and Superset), read by Gemini in "
                           "Wizard's own browser on this PC, signed in as you. Sign in once in the window Wizard opens; "
                           "it then works in the background."),
    ("network", "Network", "Only if Wizard cannot reach Google or GitHub on its own."),
]
FIELDS = [
    Field("GOOGLE_CLOUD_PROJECT", "Google Cloud project", "gemini", "Your organisation's Gemini project, if it has one."),
    Field("WIZARD_GOOGLE_DOMAINS", "Company Google domains", "gemini", "Only these accounts may link, e.g. company.com.",
          "company.com"),
    Field("WIZARD_KB_REPO", "Repository", "knowledge", "owner/name of the private repository.", "acme/wizard-content"),
    Field("WIZARD_KB_TOKEN", "Read-only token", "knowledge", "Fine-grained token: that repository only, Contents read.",
          "github_pat_…"),
    Field("WIZARD_KB_WRITE_TOKEN", "Write token (PAT)", "knowledge",
          "Lets Wizard save what it learns, such as the portal maps, to this repository: a token with Contents read and "
          "write on it. Kept on this PC only.", "github_pat_…"),
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
    Field("WIZARD_METRONOME_URL", "Address", "metronome", "Metronome on the office network.", "http://10.0.0.5:8000"),
    Field("WIZARD_METRONOME_CLIENT_KEY", "Wizard's key", "metronome",
          "Signed in to Metronome as the Wizard user; scripts/metronome_link.py makes one on the Metronome host PC."),
    Field("WIZARD_METRONOME_USER", "Metronome user", "metronome", "Every Flow Wizard creates belongs to this user.",
          "Wizard"),
    Field("WIZARD_PORTAL_ASAP_URL", "ASAP address", "portals", "The page you open ASAP with.", "https://asap.company.example/"),
    Field("WIZARD_PORTAL_GSCM_URL", "GSCM address", "portals", "The page you open GSCM with.", "https://gscm.company.example/"),
    Field("WIZARD_PORTAL_BDP_CATALOG_URL", "Big Data Portal: information catalog", "portals",
          "Where you search for tables and request access to them.", "https://catalog.company.example/"),
    Field("WIZARD_PORTAL_BDP_URL", "Big Data Portal: Superset", "portals", "Where you query the tables (SQL Lab).",
          "https://superset.company.example/"),
    Field("WIZARD_BROWSER", "Browser", "portals", "Wizard uses its own profile of this browser, never your everyday one.",
          "chrome", ("chrome", "msedge")),
    Field("WIZARD_PORTAL_HOSTS", "Other hosts the portals need", "portals",
          "Only when sign-in or a portal uses a host outside the company domain, e.g. login.microsoftonline.com.", ""),
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
    proxy = values.get("WIZARD_PROXY") or settings.proxy
    result = knowledge_sync.check(source, proxy=proxy, transport=transport)
    writer = values.get("WIZARD_KB_WRITE_TOKEN")
    if not writer or not result.ok:
        return {"ok": result.ok, "message": result.message}
    from wizard_documents import kb
    client = httpx.Client(transport=transport, timeout=30) if transport is not None else None
    ok, message = kb.check_write(repo, writer, proxy=proxy, client=client)
    return {"ok": ok, "message": f"{result.message} {message}"}


def test_metronome(settings: Settings, proposed: dict[str, Any],
                   transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    values = _candidate(settings, proposed)
    try:
        target = metronome_settings(values.get("WIZARD_METRONOME_URL"), values.get("WIZARD_METRONOME_CLIENT_KEY"),
                                    values.get("WIZARD_METRONOME_USER"))
    except MetronomeConfigError as error:
        return {"ok": False, "message": str(error)}
    if target is None:
        return {"ok": False, "message": "Fill in Metronome's address and Wizard's key."}
    return MetronomeClient(target, transport).check()


RELEASE = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/"
# The mirror branch CI force-pushes with every release (desktop.yml), read from api.github.com as setup.ps1 reads.
MIRROR_MANIFEST = "https://api.github.com/repos/datap0nd/wizard/contents/wizard-desktop.json?ref=desktop-download"


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


def _read_release(url: str, proxy: str | None, transport: httpx.BaseTransport | None, accept: str = "") -> Any:
    """GitHub answers a release link with a redirect to its download host (release-assets.githubusercontent.com). Each
    hop gets its own route: the Windows proxy settings (a PAC script) can route that host differently from github.com.
    An answer that is not a release manifest (a proxy's page) is refused."""
    for _ in range(5):
        if transport is not None:
            client = httpx.Client(transport=transport, timeout=30)
        else:
            route, _ = outbound.proxy_for(url, proxy)
            client = httpx.Client(timeout=httpx.Timeout(30, connect=10), verify=outbound.ssl_context(), proxy=route,
                                  trust_env=False)
        with client:
            response = client.get(url, headers={"User-Agent": "Wizard", **({"Accept": accept} if accept else {})})
        if not response.has_redirect_location:
            response.raise_for_status()
            manifest = response.json()
            if not isinstance(manifest, dict) or not _version(manifest.get("version")):
                raise ValueError("The answer is not a release manifest.")
            return manifest
        url = str(response.url.join(response.headers["location"]))
    raise httpx.TooManyRedirects("Too many redirects.", request=response.request)


def check_update(settings: Settings, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """The newest desktop release against this build. Only reads the public release manifest, with Wizard's own
    connection, first where Metronome's setup.ps1 reads (owner, 30 Oct 2026: GitHub downloads were tightened on the work
    network): api.github.com for the manifest on the mirror branch CI keeps of every release, then the release itself.
    It never starts PowerShell (owner, 30 Oct 2026: Microsoft Defender reported Wizard's hidden PowerShell downloads as
    malware). When neither answers, the page offers Check with Windows: WizardBar reads in its own process with Windows'
    proxy settings and the person's proxy sign-in, up to 20 attempts."""
    build = installed_build()
    installed = build.get("version")
    url = RELEASE + "wizard-desktop.json"
    result: dict[str, Any] = {"installed": installed, "commit": build.get("commit"), "download": RELEASE + "WizardSetup.exe"}
    manifest: Any = None
    errors: list[str] = []
    for address, accept in ((MIRROR_MANIFEST, "application/vnd.github.raw+json"), (url, "")):
        try:
            manifest = _read_release(address, settings.proxy, transport, accept)
            break
        except (httpx.HTTPError, ValueError) as error:
            errors.append(outbound.explain(error, str(error.request.url), settings.proxy)
                          if isinstance(error, httpx.TransportError) else f"{httpx.URL(address).host}: {error}")
    if manifest is None:
        return {**result, "ok": False, "message": f"Could not read the release: {' '.join(errors)}"}
    latest = manifest.get("version") if isinstance(manifest, dict) else None
    available = bool(_version(latest)) and (not _version(installed) or _version(latest) > _version(installed))
    return {**result, "ok": True, "latest": latest, "latest_commit": manifest.get("commit"), "available": available,
            "message": (f"Version {latest} is available." if available else f"You have the latest version ({installed}).")
            if installed else f"The latest release is {latest}; this copy was not installed from a release."}

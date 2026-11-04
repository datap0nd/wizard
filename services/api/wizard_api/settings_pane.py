"""The settings pane: the company settings a person may change on their own PC (Gemini model and project, the knowledge
base, the read-only database, the dashboards folder, Metronome, the portals, the source order, the proxy), where each
value comes from, saving, and connection tests.

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
from wizard_connectors import dashboards
from wizard_connectors.metronome import MetronomeConfigError
from wizard_connectors.metronome import settings_from as metronome_settings
from wizard_connectors.paths import ROOT
from wizard_connectors.pg import PgError, PgSettings
from wizard_connectors.pg import settings_from as pg_settings

from . import knowledge_sync, provisioning, source_order
from .config import PICKER_KEYS, ConfigError, Settings, load_settings, read_env_file
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
    ("site", "Pages site", "Brain and Cases, two pages of their own on the company GitHub's Pages, published from this PC "
                           "with the knowledge base's write token."),
    ("postgres", "Company database", "A read-only PostgreSQL account for Gemini's SQL questions."),
    ("nerp", "NERP", "NERP's views on their own PostgreSQL server: one database, one schema, views only, read with a "
                     "read-only account. Gemini queries only those views; the task \"Map NERP's views\" documents each "
                     "one so questions go straight to the right columns."),
    ("dashboards", "Dashboards", "The team's HTML dashboards: the database's data with the team's business logic, which "
                                 "Gemini reads first when one covers the question. A mapped drive is saved as the network "
                                 "path it stands for, so every PC finds the same folder."),
    ("metronome", "Metronome", "Recurring extractions: Metronome emails a table on a schedule, as Flows owned by its "
                               "Wizard user."),
    ("portals", "Portals", "ASAP, GSCM and the Big Data Portal (its information catalog and Superset), read by Gemini in "
                           "Wizard's own browser on this PC, signed in as you. Sign in once in the window Wizard opens; "
                           "it then works in the background."),
    ("sources", "Source order", "Where Wizard starts: the data sources in the company's order, what each is for, and "
                                "which it uses only when asked. Gemini starts with the first source that holds what is "
                                "asked and goes further only for what it lacks. One order for the whole company: Export "
                                "settings… carries it."),
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
          "Lets Wizard save what it learns to this repository: the notes tasks write and the portal maps; Test "
          "connection gives an empty repository its first commit. Fine-grained token: resource "
          "owner the organisation, that repository only, Contents read and write (GitHub preselects \"Read-only\": choose "
          "\"Read and write\"; organisations may refuse classic tokens). Kept on this PC only.", "github_pat_…"),
    Field("WIZARD_KB_REF", "Branch", "knowledge", "", "main"),
    Field("WIZARD_KB_PATH", "Folder in the repository", "knowledge", "Leave empty when the notes are at the root.", ""),
    Field("WIZARD_KB_SYNC_MINUTES", "Check for changes every (minutes)", "knowledge", "0 checks only at start-up.", "30"),
    Field("WIZARD_SITE_REPO", "Repository", "site", "Empty: the knowledge base's repository. Another one needs the write "
          "token to cover it too.", "acme/wizard-content"),
    Field("WIZARD_SITE_BRANCH", "Branch", "site", "Never the notes' branch. On GitHub, Settings → Pages: Deploy from a "
          "branch, this branch, / (root).", "gh-pages"),
    Field("WIZARD_SITE_URL", "Site address", "site", "The address GitHub shows under Settings → Pages, so Wizard can link "
          "the pages.", "https://pages.github.example.com/acme/wizard-content/"),
    Field("WIZARD_PG_NAME", "Name people see", "postgres", "Shown in the app and in answers' sources.", "AI Team Database"),
    Field("WIZARD_PG_HOST", "Server", "postgres", "", "db.company.example"),
    Field("WIZARD_PG_PORT", "Port", "postgres", "", "5432"),
    Field("WIZARD_PG_DATABASE", "Database", "postgres", "", "postgres"),
    Field("WIZARD_PG_USER", "User (read-only)", "postgres", "", "wizard_ro"),
    Field("WIZARD_PG_PASSWORD", "Password", "postgres"),
    Field("WIZARD_PG_SSLMODE", "SSL", "postgres", "", "prefer",
          ("disable", "prefer", "require", "verify-ca", "verify-full")),
    Field("WIZARD_PG_SCHEMAS", "Schemas Wizard may query", "postgres",
          "Separated by commas. Gemini's queries may read only these schemas (and pg_catalog and information_schema for "
          "metadata); a query that reads any other, also through a view, is refused. Empty: every schema the account can "
          "read.", "reporting"),
    Field("WIZARD_NERP_NAME", "Name people see", "nerp", "Shown in the app and in answers' sources.", "NERP"),
    Field("WIZARD_NERP_HOST", "Server", "nerp", "Its host name, host:port, or a postgresql:// address (a database in it "
          "fills Database; never a password).", "nerp-db.company.example"),
    Field("WIZARD_NERP_PORT", "Port", "nerp", "", "5432"),
    Field("WIZARD_NERP_DATABASE", "Database", "nerp", "The only database Wizard reads on that server.", "nerp"),
    Field("WIZARD_NERP_SCHEMA", "Schema", "nerp", "The only schema: Gemini's queries may name only its views (and "
          "materialized views); a table, another schema or the catalog is refused.", "reporting"),
    Field("WIZARD_NERP_VIEWS", "Views Wizard may query", "nerp",
          "Separated by commas. Gemini (and every NERP task) may list, read and query only these views of the schema; "
          "any other is refused. Empty: every view of the schema the account can read.", "sellout_daily_v, spend_v"),
    Field("WIZARD_NERP_USER", "User (read-only)", "nerp", "An account that can read those views only.", "wizard_nerp_ro"),
    Field("WIZARD_NERP_PASSWORD", "Password", "nerp"),
    Field("WIZARD_NERP_SSLMODE", "SSL", "nerp", "", "prefer", ("disable", "prefer", "require", "verify-ca", "verify-full")),
    Field("WIZARD_HTML_REPORTS_DIR", "Folder", "dashboards", "Paste the folder's path (quotes from Copy as path are fine). "
          "A mapped drive such as Y:\\Dashboards is saved as its network path (\\\\server\\share\\Dashboards). If this "
          "PC cannot reach it, ask for access to the share: Wizard still starts, and says so when it needs them.",
          "\\\\fileserver\\team\\Dashboards"),
    Field("WIZARD_DASHBOARDS_NAME", "Name people see", "dashboards", "Shown in the systems list and in answers' sources.",
          "Dashboards"),
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
    Field(source_order.KEY, "Order", "sources", "Move a source up or down, put it on the same level as the one above, "
          "say in a line what it is for, or keep it for when someone asks. A source not listed (a portal set up later) "
          "comes last."),
    Field("WIZARD_PROXY", "Proxy", "network", "For Google (Gemini) and the app's updates: http://host:port, or direct. "
          "Empty: the proxy in your Gemini CLI settings, else the Windows proxy settings.", ""),
    Field("WIZARD_GITHUB_PROXY", "Company GitHub proxy", "network", "For the company GitHub (the knowledge base and the "
          "portal maps): http://host:port, or direct. Empty: the route Windows and Edge take to it.", ""),
]
BY_KEY = {f.key: f for f in FIELDS}
DASHBOARDS = "WIZARD_HTML_REPORTS_DIR"
MAX_CHARS = 2000
# Values longer than one ordinary line: the source order holds a "use it for" line per source.
LONG = {source_order.KEY: source_order.MAX_CHARS}


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
            "restart": "automatic" if settings.desktop else "manual",
            "source_order": {"default": source_order.view(None), "max_use": source_order.MAX_USE}}


def _clean(changes: dict[str, Any]) -> dict[str, str | None]:
    cleaned: dict[str, str | None] = {}
    for key, value in changes.items():
        if key not in BY_KEY:
            raise PaneError(f"{key} is not a setting the pane can change")
        if value is not None and not isinstance(value, str | int):
            raise PaneError(f"{key} must be text")
        text = None if value is None else str(value).strip()
        if text and ("\n" in text or "\r" in text or len(text) > LONG.get(key, MAX_CHARS)):
            raise PaneError(f"{key} must be one line")
        field = BY_KEY[key]
        if text and field.choices and text not in field.choices:
            raise PaneError(f"{field.label} must be one of {', '.join(field.choices)}")
        if text and key == source_order.KEY:
            try:  # stored as Wizard writes it: compact, validated
                text = source_order.render(source_order.parse(text) or ())
            except source_order.OrderError as error:
                raise PaneError(f"Source order: {error}") from None
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
    if updates.get(DASHBOARDS):  # quotes removed, a mapped drive as its network path (owner, 2 Nov 2026)
        updates[DASHBOARDS] = dashboards.stored_value(str(updates[DASHBOARDS]))
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


def export(settings: Settings) -> dict[str, Any]:
    """This PC's settings as a provisioning file for another PC (owner, 30 Oct 2026: "I want to export my settings file
    basically. and import it there"): the company file's keys and every Settings field, each with the value this PC uses
    (environment > .env > this PC > company file), passwords and tokens included in plain text: the person saves it and
    imports it on the other PC. Per-PC values and the knowledge base's write token are left out, as from any
    provisioning file (provisioning.LOCAL_ONLY, PC_CHOSEN); so is the Gemini sign-in, which is never a setting."""
    layers = _layers(settings)
    company = layers[-1][1]
    wanted = set(company) | set(BY_KEY)
    values: dict[str, str] = {}
    for source, layer in reversed(layers):  # weakest first
        values.update({k: v for k, v in layer.items() if not (source == "this_pc" and k in PICKER_KEYS)})
    kept = {k: v for k, v in values.items() if k in wanted and v and provisioning.KEY.match(k)
            and k not in provisioning.LOCAL_ONLY and k not in provisioning.PC_CHOSEN}
    if not kept:
        raise PaneError("This PC has no settings to export yet.")
    name = provisioning.status(settings.data_dir).get("name") or "Wizard"
    text = provisioning.render(kept, f"{name} (exported)")
    return {"text": text, "settings": sorted(k for k in kept if not provisioning.is_secret(k)),
            "secrets": sorted(k for k in kept if provisioning.is_secret(k)),
            "left_out": sorted(k for k in provisioning.PC_CHOSEN if values.get(k))}


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


def test_nerp(settings: Settings, proposed: dict[str, Any]) -> dict[str, Any]:
    """Connect with the NERP settings typed, read-only, and say what Wizard would see: the views of the schema, and
    whether the account can also read tables there (it should read views only)."""
    from wizard_connectors.nerp import VIEWS
    from wizard_connectors.nerp import settings_from as nerp_settings
    from wizard_connectors.pg import Pg8000Session
    values = _candidate(settings, proposed)
    try:
        target = nerp_settings({k: v for k, v in values.items() if k.startswith("WIZARD_NERP_")})
    except PgError as error:
        return {"ok": False, "message": str(error)[:1].upper() + str(error)[1:] + "."}
    if target is None:
        return {"ok": False, "message": "Fill in at least the server, the database, the schema and the user."}
    try:
        session = Pg8000Session(target.pg, application_name="wizard-settings-test")
        try:
            session.rows("START TRANSACTION READ ONLY")
            who = session.rows("SELECT current_user AS who")[0]["who"]
            every = session.rows(VIEWS, schema=target.schema)
            views = [v for v in every if target.allows(str(v["name"]))]
            missing = [v for v in target.views if v not in {str(r["name"]) for r in every}]
            tables = session.rows(
                "SELECT count(*) AS n FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relkind IN ('r', 'p', 'f') "
                "AND pg_catalog.has_table_privilege(c.oid, 'SELECT')", schema=target.schema)[0]["n"]
            session.rows("ROLLBACK")
        finally:
            session.close()
    except PgError as error:
        return {"ok": False, "message": f"Could not connect: {error}"}
    except Exception as error:  # noqa: BLE001 - a database error, in words
        return {"ok": False, "message": f"Connected, but could not read the schema {target.schema}: {error}"}
    if missing:
        return {"ok": False, "message": f"Connected as {who} to {target.pg.database}, but schema {target.schema} has no view "
                                        f"named {', '.join(missing)} that this account can read: check the names (a name "
                                        "with capitals needs double quotes) and the account's grants."}
    if not views:
        return {"ok": False, "message": f"Connected as {who} to {target.pg.database}, but this account can read no view "
                                        f"in schema {target.schema}: check the schema's name and the account's grants."}
    names = ", ".join(str(v["name"]) for v in views[:6]) + (f" and {len(views) - 6} more" if len(views) > 6 else "")
    extra = (f" This account can also read {tables} table(s) in that schema; Wizard still queries only the views, but "
             "ask for an account limited to them." if tables else "")
    limit = (f" Wizard may query these {len(views)} of the schema's {len(every)} view(s)." if target.views else
             " No views are listed, so Wizard may query every one.")
    return {"ok": True, "message": f"Connected as {who} to {target.pg.database} on {target.pg.host}: {len(views)} "
                                   f"view(s) in {target.schema} ({names}).{limit}{extra}"}


def test_knowledge(settings: Settings, proposed: dict[str, Any],
                   transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    values = _candidate(settings, proposed)
    repo, token = values.get("WIZARD_KB_REPO"), values.get("WIZARD_KB_TOKEN")
    if not repo or not token:
        return {"ok": False, "message": "Fill in the repository and the token."}
    source = knowledge_sync.Source(repo, values.get("WIZARD_KB_REF") or "main", (values.get("WIZARD_KB_PATH") or "").strip("/\\"),
                                   token)
    proxy = values.get("WIZARD_GITHUB_PROXY") or settings.github_proxy  # the company GitHub's own route
    result = knowledge_sync.check(source, proxy=proxy, transport=transport)
    writer = values.get("WIZARD_KB_WRITE_TOKEN")
    from wizard_documents import kb

    def client() -> httpx.Client | None:
        return httpx.Client(transport=transport, timeout=30) if transport is not None else None

    started = ""
    if writer and result.outcome == "empty":
        # A new, empty repository: its first commit (the README) comes from the write token, the way every note
        # reaches it (decision 2026-11-02), so the users' read-only token reads it and every PC syncs.
        try:
            kb.start(repo, writer, proxy=proxy, client=client())
        except kb.PublishError as error:
            return {"ok": False, "message": f"{result.message} Write token: {error}"}
        except httpx.HTTPError as error:
            return {"ok": False, "message": f"{result.message} Write token: {outbound.explain(error, kb.API, proxy, windows=True)}"}
        started = f"{repo} was empty: Wizard gave it its first commit (README.md) with the write token. "
        result = knowledge_sync.check(source, proxy=proxy, transport=transport)
    if not writer or not result.ok:
        return {"ok": result.ok, "message": started + result.message}
    ok, message = kb.check_write(repo, writer, proxy=proxy, client=client())
    return {"ok": ok, "message": f"{started}{result.message} {message}"}


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


def test_dashboards(settings: Settings, proposed: dict[str, Any]) -> dict[str, Any]:
    """Find the dashboards in the folder the person typed: the path Wizard would save (a mapped drive as its network
    path), whether this PC reaches it, and how many dashboards it holds."""
    values = _candidate(settings, proposed)
    typed = values.get(DASHBOARDS) or ""
    if not dashboards.clean(typed):
        return {"ok": False, "message": "Paste the path of the folder that holds the team's HTML dashboards."}
    stored = dashboards.stored_value(typed)
    folder = dashboards.Dashboards(dashboards.folder_path(stored, settings.home or ROOT), None)
    mapped = (f" ({dashboards.clean(typed)[:2].upper()} on this PC; Wizard saves the network path so every PC finds the "
              "same folder)") if stored != dashboards.clean(typed) else ""
    problem = folder.problem(fresh=True)
    if problem:
        return {"ok": False, "value": stored, "message": dashboards.unreachable(folder.root, problem).split(" Until")[0]}
    try:
        found = folder.listing(fresh=True)
    except dashboards.DashboardError as error:
        return {"ok": False, "value": stored, "message": error.message}
    if not found:
        return {"ok": False, "value": stored, "count": 0,
                "message": f"Wizard reaches {folder.root}{mapped}, but it holds no HTML files (.html, .htm), subfolders "
                           "included. Check that this is the dashboards folder."}
    return {"ok": True, "value": stored, "count": len(found),
            "message": f"Found {len(found):,} dashboard{'' if len(found) == 1 else 's'} in {folder.root}{mapped}. Save to "
                       "keep it."}


RELEASE = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/"
# The mirror branch CI force-pushes with every release (desktop.yml), read from api.github.com as setup.ps1 reads.
MIRROR_MANIFEST = "https://api.github.com/repos/datap0nd/wizard/contents/wizard-desktop.json?ref=desktop-download"


def installed_build() -> dict[str, Any]:
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

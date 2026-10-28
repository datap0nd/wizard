"""Company web portals (ASAP, GSCM, the Big Data Portal) read through the person's own browser: settings and the rules
that keep Gemini's browser scripts read-only.

Owner decision (23 October 2026, docs/decisions/2026-10-23-portal-browser.md): Wizard opens its own Chrome window,
signed in as the person at this PC, and Gemini explores and queries the portals in it, preferring the portals' own data
requests (MicroStrategy, Nexacro transactions, Superset's API) over clicking through screens. Everything here is pure
Python so the rules are tested without a browser; portal_browser.py applies them to every request and click.

The rules, applied inside the tool, never by Gemini's goodwill:
- only the configured portals' hosts, their company domain and the hosts the person's own sign-in went through can be
  reached, so a script cannot send data anywhere else;
- requests that save, delete, approve, upload, request access or sign out are refused before they leave the browser (by
  the verb that starts a path segment or a service name, a POST to an access-request collection, a GraphQL mutation),
  PUT/PATCH/DELETE only for MicroStrategy prompt answers;
- Superset SQL Lab runs one SELECT at a time;
- clicks on controls named Save, Delete, Submit, Pin, Request... are refused (Metronome's list, FORBIDDEN_CLICK_WORDS);
- session tokens, passwords and cookies are redacted from everything Gemini sees."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .postgres_query import _code, without_terminator

# The portals Wizard knows, in the order people see them. Each is configured by its start address. The Big Data Portal
# is two applications with an address each: Superset, where people query tables (SQL Lab), and the information catalog,
# where they search for tables and request access to them (owner, 28 October 2026).
KNOWN = {
    "asap": ("ASAP", "WIZARD_PORTAL_ASAP_URL"),
    "gscm": ("GSCM", "WIZARD_PORTAL_GSCM_URL"),
    "bdp": ("Big Data Portal", "WIZARD_PORTAL_BDP_URL"),
}
# A portal's applications when it has more than one: (part, label, setting). The first configured one is the portal's
# start page.
PARTS = {
    "bdp": (("superset", "Superset", "WIZARD_PORTAL_BDP_URL"),
            ("catalog", "information catalog", "WIZARD_PORTAL_BDP_CATALOG_URL")),
}
CHANNELS = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}
HOST = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$")

# A path segment, service name or task id that starts with one of these verbs changes something.
WRITE_VERBS = frozenset({
    "save", "insert", "ins", "update", "upd", "upsert", "merge", "delete", "del", "remove", "rm", "drop", "truncate",
    "modify", "mod", "edit", "upload", "import", "approve", "reject", "regist", "register", "reg", "create", "new",
    "add", "submit", "send", "publish", "write", "share", "pin", "unpin", "apply", "confirm", "cancel", "revoke",
    "grant", "assign", "reset", "clear", "logout", "logoff", "signout", "subscribe", "unsubscribe", "schedule", "email",
    "transfer", "request",
})
# A POST to an address part that ends in an access request (/access-requests, permissionRequest, tableAccessRequest.do)
# files one in the information catalog; selectAccessRequestList.do still reads.
ACCESS_WORDS = frozenset({"access", "permission", "permissions", "authority", "privilege", "privileges"})
REQUEST_WORDS = frozenset({"request", "requests"})
EXTENSIONS = frozenset({"do", "json", "jsp", "action", "xml"})
# A GraphQL mutation (optionally named, then its variables or selection), not a search text that starts with the word.
GRAPHQL_MUTATION = re.compile(r"^\s*(#[^\n]*\n\s*)*mutation\b\s*([A-Za-z_]\w*)?\s*[({]")
# Query or form parameters whose value names the action a generic endpoint performs.
ACTION_PARAMS = frozenset({"taskid", "task", "action", "method", "cmd", "command", "op", "operation", "svc", "svcid",
                           "service", "serviceid", "mode", "evtname"})
# MicroStrategy REST answers report prompts with PUT; nothing else may use PUT, PATCH or DELETE.
WRITE_METHODS_ALLOWED = (re.compile(r"/prompts/answers/?$"),)
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST"})
# Superset SQL Lab: the request carries SQL, which must be one read-only statement.
SQLLAB = re.compile(r"/(api/v1/sqllab/execute|superset/sql_json)/?$")
# The statement already has to start with SELECT, WITH, SHOW, EXPLAIN, DESCRIBE or VALUES and be alone, so these catch
# what can still write from there: data-modifying CTEs, SELECT ... INTO, INSERT OVERWRITE, EXPLAIN ANALYZE (which runs
# its statement). Functions such as REPLACE() and columns such as comment stay allowed.
SQL_WRITE = re.compile(r"\b(insert|update|delete|merge|upsert|drop|create|alter|truncate|grant|revoke|copy|call|"
                       r"into|overwrite|analyze|analyse|vacuum|execute|exec|refresh|optimize|msck)\b", re.I)
SQL_READ_START = re.compile(r"^\s*(\(\s*)*(select|with|show|explain|describe|desc|values)\b", re.I)

# Metronome's list of controls a portal script must never click (data_governance app/flow_gscm.py), matched as whole
# words of a control's label, title, value or name, plus the last part of its id (Nexacro ids are component paths).
# Plus request: the Big Data Portal's information catalog requests table access in the person's name.
FORBIDDEN_CLICK_WORDS = frozenset({
    "save", "delete", "remove", "del", "drop", "clear", "reset", "unselect", "apply", "submit", "confirm", "pin",
    "unpin", "share", "new", "add", "edit", "modify", "update", "upload", "import", "send", "approve", "reject",
    "publish", "register", "create", "insert", "logout", "logoff", "signout", "subscribe", "unsubscribe", "schedule",
    "request",
})
FORBIDDEN_CLICK_PHRASES = ("sign out", "log out", "log off", "export all")

# Names whose values are secrets: session ids, tokens, passwords, keys. A key named just "session" (ASAP's whole
# session object, or W.mstr.session()'s summary) is not one: the secret fields inside it are redacted by name.
SECRET_NAME = re.compile(r"(token|auth(?!or)|sess_?id|session_?id|sessid|session_?key|passw|pwd|secret|csrf|xsrf|cookie|"
                         r"apikey|api_key|ticket|saml|jwt|bearer|credential|signature|^sig$|^key$)", re.I)
REDACTED = "<redacted>"
FORM_BODY = re.compile(r"^[\w.%\[\]-]+=[^&\s]*(&[\w.%\[\]-]+=[^&\s]*)*$")
TOKEN_VALUE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-+/=.]{40,}(?![A-Za-z0-9])")


class PortalConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Part:
    """One application of a portal that has several (the Big Data Portal's Superset and information catalog)."""
    id: str
    label: str
    url: str

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()


@dataclass(frozen=True)
class Portal:
    id: str
    name: str
    url: str  # the start page: steps begin here, and a path resolves here unless the page is on another of its parts
    parts: tuple[Part, ...] = ()

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()

    @property
    def origin(self) -> str:
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def pages(self) -> list[tuple[str, str, str]]:
        """Each application to sign in to and check, as (id, name, start address)."""
        if not self.parts:
            return [(self.id, self.name, self.url)]
        return [(f"{self.id}-{part.id}", f"{self.name}: {part.label}", part.url) for part in self.parts]

    @property
    def hosts(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((urlsplit(url).hostname or "").lower() for _, _, url in self.pages))


@dataclass(frozen=True)
class PortalSettings:
    portals: tuple[Portal, ...]
    channel: str = "chrome"
    # Hosts the portals need besides their own company domain (a sign-in service on another domain), as host names or
    # *.domain wildcards.
    extra_hosts: tuple[str, ...] = ()
    # Tests and Linux development only: a Chromium binary instead of the installed Chrome or Edge.
    executable: str | None = None

    def portal(self, portal_id: str) -> Portal | None:
        return next((p for p in self.portals if p.id == portal_id), None)


def settings_from(values: dict[str, str | None]) -> PortalSettings | None:
    """Portals from WIZARD_PORTAL_*_URL, WIZARD_BROWSER, WIZARD_PORTAL_HOSTS and WIZARD_BROWSER_EXECUTABLE; None when
    no portal is configured."""
    portals = []
    for portal_id, (name, key) in KNOWN.items():
        if portal_id in PARTS:
            parts = tuple(Part(part, label, _address_setting(values, setting)) for part, label, setting in PARTS[portal_id]
                          if (values.get(setting) or "").strip())
            if parts:
                portals.append(Portal(portal_id, name, parts[0].url, parts))
            continue
        if (values.get(key) or "").strip():
            portals.append(Portal(portal_id, name, _address_setting(values, key)))
    if not portals:
        return None
    channel = (values.get("WIZARD_BROWSER") or "chrome").strip().lower()
    if channel not in CHANNELS:
        raise PortalConfigError("WIZARD_BROWSER must be chrome or msedge")
    hosts = []
    for raw in (values.get("WIZARD_PORTAL_HOSTS") or "").split(","):
        host = raw.strip().lower()
        if not host:
            continue
        if not HOST.match(host) or host.count(".") < 1 or (host.startswith("*.") and host.count(".") < 2):
            raise PortalConfigError(f"WIZARD_PORTAL_HOSTS: {raw.strip()} is not a host name or *.domain wildcard")
        hosts.append(host)
    executable = (values.get("WIZARD_BROWSER_EXECUTABLE") or "").strip() or None
    return PortalSettings(tuple(portals), channel, tuple(hosts), executable)


def _address_setting(values: dict[str, str | None], key: str) -> str:
    url = (values.get(key) or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise PortalConfigError(f"{key} must be the portal's address, for example https://portal.company.example/")
    if parts.username or parts.password:
        raise PortalConfigError(f"{key} must not contain a user name or password")
    return url


def company_domain(host: str) -> str | None:
    """The domain a portal host belongs to (its host without the first label), when that still names a company domain
    rather than a public suffix: portal.corp.example.com -> corp.example.com, but portal.example.com -> None."""
    labels = host.lower().split(".")
    if len(labels) < 4 or all(label.isdigit() for label in labels):
        return None
    return ".".join(labels[1:])


@dataclass
class HostPolicy:
    """Which hosts a Gemini browser script may reach."""
    settings: PortalSettings
    learned: set[str] = field(default_factory=set)  # hosts the person's own sign-in window went through

    def allowed(self, host: str | None) -> bool:
        if not host:
            return False
        if self.portal_domain(host):
            return True
        host = host.lower().rstrip(".")
        for pattern in self.settings.extra_hosts:
            if host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:])):
                return True
        return host in self.learned

    def portal_domain(self, host: str) -> bool:
        """The host is a portal's own, or in a portal's company domain."""
        host = host.lower().rstrip(".")
        for portal in self.settings.portals:
            for own in portal.hosts:
                domain = company_domain(own)
                if host == own or (domain and (host == domain or host.endswith("." + domain))):
                    return True
        return False

    def portal_for(self, host: str | None) -> Portal | None:
        return next((p for p in self.settings.portals if host and host.lower() in p.hosts), None)


def _tokens(text: str) -> list[str]:
    """Words of a name: saveBookmark.do -> save, bookmark, do; btn_exceldown -> btn, exceldown."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [t for t in re.split(r"[^A-Za-z]+", spaced.casefold()) if t]


def _starts_with_verb(name: str) -> str | None:
    words = _tokens(name)
    return words[0] if words and words[0] in WRITE_VERBS else None


def write_reason(method: str, url: str, body: str | None = None) -> str | None:
    """Why this request would change something in the portal, or None when it reads. Conservative: a refused read
    costs Gemini a retry with another route; an allowed write could change company data."""
    method = method.upper()
    parts = urlsplit(url)
    path = parts.path or "/"
    if method not in READ_METHODS and not (method in ("PUT",) and any(p.search(path) for p in WRITE_METHODS_ALLOWED)):
        return f"{method} requests change data"
    for segment in path.split("/"):
        verb = _starts_with_verb(segment.split(";")[0])
        if verb:
            return f"'{segment}' in the address starts with '{verb}'"
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in ACTION_PARAMS:
            verb = _starts_with_verb(value)
            if verb:
                return f"the {key} parameter '{value[:60]}' starts with '{verb}'"
    if method == "POST":
        for segment in path.split("/"):
            words = [w for w in _tokens(segment) if w not in EXTENSIONS]
            if len(words) >= 2 and words[-2] in ACCESS_WORDS and words[-1] in REQUEST_WORDS:
                return f"a POST to '{segment[:60]}' requests access"
    if body and method == "POST":
        if SQLLAB.search(path):
            return sql_problem(body)
        mutation = _graphql_mutation(body)
        if mutation:
            return mutation
        if "=" in body[:2000] and not body.lstrip().startswith(("<", "{", "[")):
            for key, value in parse_qsl(body[:20_000], keep_blank_values=True):
                if key.casefold() in ACTION_PARAMS:
                    verb = _starts_with_verb(value)
                    if verb:
                        return f"the {key} field '{value[:60]}' starts with '{verb}'"
        for name in re.findall(r"<Parameter\s+id=\"(?:svcid|service|svc|method|action)\"[^>]*>([^<]{1,200})<", body[:50_000],
                               re.I):
            verb = _starts_with_verb(name)
            if verb:
                return f"the service '{name[:60]}' starts with '{verb}'"
    return None


def _graphql_mutation(body: str) -> str | None:
    """A GraphQL request that changes data (a mutation), as a data catalog's API may send one."""
    stripped = body.lstrip()
    if not stripped.startswith(("{", "[")) or "mutation" not in body[:100_000]:
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    for item in value if isinstance(value, list) else [value]:
        query = item.get("query") if isinstance(item, dict) else None
        if isinstance(query, str) and GRAPHQL_MUTATION.match(query):
            return "the GraphQL request is a mutation"
    return None


def sql_problem(body: str) -> str | None:
    """Superset SQL Lab: None when the request runs one read-only statement."""
    try:
        sql = str(json.loads(body).get("sql") or "")
    except (ValueError, AttributeError):
        return "the SQL Lab request is not JSON with a sql field"
    text = without_terminator(sql).strip()
    if not text:
        return "the SQL is empty"
    code = "".join(c for _, c in _code(text))
    if ";" in code:
        return "SQL Lab runs one statement at a time"
    if not SQL_READ_START.match(code):
        return "only SELECT (or WITH ... SELECT) runs in SQL Lab"
    match = SQL_WRITE.search(code)
    if match:
        return f"the SQL contains {match.group(1).upper()}"
    return None


def click_refusal(descriptor: dict[str, Any]) -> str | None:
    """Why a control must not be clicked (its label, title, value or name, or the last part of its id, names a change),
    or None."""
    label_parts = [str(descriptor.get(k) or "")[:200] for k in ("text", "aria", "title", "value", "name", "alt")]
    element_id = str(descriptor.get("id") or "")
    last = element_id.split(".")[-1].split(":")[0] if element_id else ""
    for text in [*label_parts, last]:
        lowered = re.sub(r"\s+", " ", text.casefold()).strip()
        for phrase in FORBIDDEN_CLICK_PHRASES:
            if phrase in lowered:
                return f"it is labelled '{text.strip()[:60]}'"
        hit = next((w for w in _tokens(text) if w in FORBIDDEN_CLICK_WORDS), None)
        if hit:
            return f"'{text.strip()[:60]}' names '{hit}'"
    return None


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, REDACTED if SECRET_NAME.search(k) else v[:200]) for k, v in
                       parse_qsl(parts.query, keep_blank_values=True)], safe="<>")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def redact_text(text: str, limit: int = 1500) -> str:
    """A request or response body as Gemini may see it: secrets by name replaced, long opaque tokens shortened."""
    if not text:
        return ""
    head = text[:max(limit * 4, 8000)]
    stripped = head.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            head = json.dumps(redact_json(json.loads(text if len(text) < 500_000 else head)), ensure_ascii=False)
        except ValueError:
            pass
    elif stripped.startswith("<"):
        head = re.sub(r"(<Parameter\s+id=\"([^\"]+)\"[^>]*>)([^<]*)(<)",
                      lambda m: m.group(1) + (REDACTED if SECRET_NAME.search(m.group(2)) else m.group(3)) + m.group(4),
                      head, flags=re.I)
    elif FORM_BODY.match(head.strip()):
        head = urlencode([(k, REDACTED if SECRET_NAME.search(k) else v) for k, v in parse_qsl(head, keep_blank_values=True)],
                         safe="<>")
    head = TOKEN_VALUE.sub(lambda m: m.group(0)[:6] + "…" + REDACTED, head)
    return head if len(head) <= limit else head[:limit] + f"… ({len(text):,} characters in all)"


def scrub(text: str) -> str:
    """Free text (an error, a dialog) with long opaque values shortened: a script's error can quote a token."""
    return TOKEN_VALUE.sub(lambda m: m.group(0)[:6] + "…" + REDACTED, text)


def redact_rows(columns: list[str], rows: list[list[Any]]) -> list[list[Any]]:
    """A table as Gemini may see it: columns named like secrets blanked, cells that are a long opaque value shortened."""
    secret = [bool(SECRET_NAME.search(c)) for c in columns]
    return [[REDACTED if index < len(secret) and secret[index] and cell is not None
             else scrub(cell) if isinstance(cell, str) and len(cell) >= 40 else cell
             for index, cell in enumerate(row)] for row in rows]


def redact_json(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "…"
    if isinstance(value, dict):
        return {k: (REDACTED if SECRET_NAME.search(str(k)) else redact_json(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(v, depth + 1) for v in value]
    return value


def table_from(value: Any) -> tuple[list[str], list[list[Any]], int] | None:
    """Columns, rows and the total row count when a script's result is a table: {columns, rows[, total_rows]} or a list
    of objects. Anything else is not a table."""
    if isinstance(value, dict) and isinstance(value.get("rows"), list) and isinstance(value.get("columns"), list):
        columns = [str(c.get("key") or c.get("label") or c.get("id")) if isinstance(c, dict) else str(c)
                   for c in value["columns"]][:200]
        rows: list[list[Any]] = []
        for row in value["rows"]:
            if isinstance(row, dict):
                rows.append([row.get(c) for c in columns])
            elif isinstance(row, list):
                rows.append(list(row[:len(columns)]) + [None] * max(0, len(columns) - len(row)))
            else:
                return None
        total = value.get("total_rows")
        return columns, rows, int(total) if isinstance(total, int) and total >= len(rows) else len(rows)
    if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
        columns = []
        for row in value[:1000]:
            for key in row:
                if key not in columns and len(columns) < 200:
                    columns.append(str(key))
        return columns, [[row.get(c) for c in columns] for row in value], len(value)
    return None


def plain_cell(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:2000]
    return json.dumps(value, ensure_ascii=False, default=str)[:2000]


def column_types(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    described = []
    for index, name in enumerate(columns):
        values = [row[index] for row in rows[:200] if index < len(row) and row[index] not in (None, "")]
        numeric = bool(values) and all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)
        described.append({"key": name, "label": name, "type": "number" if numeric else "string"})
    return described


def digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

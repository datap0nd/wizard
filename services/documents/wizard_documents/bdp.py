"""Read-only discovery of the Big Data Portal's Superset from this PC (`bdp-check`, task 40).

Before any BDP connection is built, it answers what a per-user one would need:
- does Superset answer from this PC, through the proxy and certificate store Wizard itself would use;
- how Superset signs people in: the redirects from its login page name the identity provider and the protocol
  (OAuth 2.0 / OpenID Connect, SAML, Windows integrated sign-in), and show whether a sign-in gateway sits in front of
  Superset (then even its health check redirects);
- whether the REST API answers, and which endpoints its API description lists when that description is public.

It sends anonymous GET requests only: no sign-in, no credentials, no browser cookies, no SQL. Redirects that leave
Superset's host are recorded, never followed. Redirect addresses are kept as host, path and parameter names; parameter
values (state, nonce, client ids) are never kept. Which engines sit behind Superset needs a signed-in view, so task 40
has the user save one page from their own browser instead."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

import wizard_agent.outbound as outbound

TIMEOUT = 15.0
MAX_HOPS = 8
# First path segments of Superset's own pages: an address cut before one of them is Superset's base address.
SUPERSET_PAGES = {"superset", "sqllab", "login", "logout", "dashboard", "explore", "chart", "dataset", "tablemodelview",
                  "databaseview", "savedqueryview", "api", "swagger", "health", "healthcheck", "users", "roles"}
FAB_AUTH_TYPES = {0: "OpenID 2.0", 1: "Superset's own user names and passwords", 2: "LDAP user names and passwords",
                  3: "a sign-in in front of Superset (remote user)", 4: "OAuth 2.0 / OpenID Connect", 5: "SAML 2.0"}
API_FEATURES = {"/api/v1/sqllab/execute": "run SQL as SQL Lab does",
                "/api/v1/security/login": "API sign-in with a user name and password (Superset or LDAP accounts only)",
                "/api/v1/database/{pk}/table_metadata": "table and column metadata",
                "/api/v1/database/{pk}/schemas": "schema lists",
                "/api/v1/me/roles": "the signed-in person's roles and table access"}


@dataclass
class Hop:
    status: int
    host: str
    path: str
    parameters: list[str] = field(default_factory=list)
    authenticate: list[str] = field(default_factory=list)  # WWW-Authenticate schemes (Negotiate, NTLM, Bearer...)
    followed: bool = True  # False: a redirect target off Superset's host, recorded from the Location header only


@dataclass
class Probe:
    name: str
    hops: list[Hop] = field(default_factory=list)
    error: str = ""


@dataclass
class CheckResult:
    base: str
    lines: list[str]
    probes: list[Probe]

    def markdown(self, today: str) -> str:
        out = [f"# Superset check for the Big Data Portal ({today})", "",
               f"Superset base address: {self.base}", "",
               "Made by `.\\docs.ps1 bdp-check`: anonymous GET requests only (no sign-in, no cookies, no SQL). "
               "Parameter values in redirects are left out on purpose.", "", "## Results", "", "```",
               *self.lines, "```", "", "## Requests", ""]
        for probe in self.probes:
            out.append(f"### {probe.name}")
            out.append("")
            if probe.error:
                out += [f"Failed: {probe.error}", ""]
            if probe.hops:
                out += ["| Step | Status | Host | Path | Parameter names | WWW-Authenticate |", "|---|---|---|---|---|---|"]
                for n, hop in enumerate(probe.hops, 1):
                    status = str(hop.status) if hop.followed else "not requested (other host)"
                    out.append(f"| {n} | {status} | {hop.host} | {hop.path[:120]} | {', '.join(hop.parameters) or '-'} "
                               f"| {', '.join(hop.authenticate) or '-'} |")
                out.append("")
        return "\n".join(out) + "\n"


def superset_base(address: str) -> str:
    """The address Superset is served from, cut before its own pages: https://bdp.example.com/sqllab/?id=3 ->
    https://bdp.example.com. A user name or password typed into the address is dropped."""
    raw = address.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"'{address}' is not a web address. Copy the address from the browser tab where SQL Lab is open.")
    kept: list[str] = []
    for segment in (s for s in parts.path.split("/") if s):
        if segment.lower() in SUPERSET_PAGES:
            break
        kept.append(segment)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{host}" + ("/" + "/".join(kept) if kept else "")


def identity_provider(host: str, path: str) -> str | None:
    host, path = host.lower(), path.lower()
    if host in ("login.microsoftonline.com", "login.windows.net", "login.microsoft.com") or host.endswith(".b2clogin.com"):
        return "Microsoft Entra ID"
    if "/adfs/" in path:
        return "AD FS"
    if "/realms/" in path:
        return "Keycloak"
    if host.endswith((".okta.com", ".oktapreview.com", ".okta-emea.com")):
        return "Okta"
    if "/as/authorization.oauth2" in path or "/idp/sso" in path:
        return "PingFederate"
    if host == "accounts.google.com":
        return "Google"
    return None


def _hop(response: httpx.Response) -> Hop:
    url = response.request.url
    schemes = [value.split()[0] for value in response.headers.get_list("www-authenticate") if value.strip()]
    return Hop(response.status_code, url.host, url.path, sorted({k for k, _ in parse_qsl(url.query.decode())}), schemes)


def _location_hop(location: str) -> tuple[Hop, str | None]:
    """A redirect target off Superset's host, recorded without requesting it, plus the protocol its parameters show."""
    parts = urlsplit(location)
    query = dict(parse_qsl(parts.query))
    names = {k.lower() for k in query}
    protocol = None
    if "samlrequest" in names:
        protocol = "SAML 2.0"
    elif {"response_type", "client_id"} <= names:
        scope = next((v for k, v in query.items() if k.lower() == "scope"), "")
        protocol = "OpenID Connect" if "openid" in scope.split() else "OAuth 2.0"
    return Hop(0, parts.hostname or "", parts.path, sorted(query), followed=False), protocol


def follow(client: httpx.Client, url: str, probe: Probe, accept: str = "text/html") -> tuple[httpx.Response | None, str | None]:
    """GET `url`, following redirects on Superset's own host. Returns the last response fetched and the sign-in protocol
    a redirect off the host shows (None when there was none)."""
    home = urlsplit(url).hostname
    for _ in range(MAX_HOPS):
        response = client.get(url, headers={"Accept": accept})
        probe.hops.append(_hop(response))
        location = response.headers.get("location")
        if not (response.is_redirect and location):
            return response, None
        target = urljoin(str(response.request.url), location)
        if urlsplit(target).hostname != home:
            hop, protocol = _location_hop(target)
            probe.hops.append(hop)
            return response, protocol
        url = target
    probe.error = f"more than {MAX_HOPS} redirects"
    return None, None


def page_facts(text: str) -> dict[str, Any]:
    """What a Superset login page says about its sign-in: the auth type and providers in its bootstrap data (Superset 4.1
    and later), or the older page's password form and provider links; plus the version when the page carries it."""
    page = html.unescape(text)
    facts: dict[str, Any] = {}
    if match := re.search(r'"AUTH_TYPE"\s*:\s*(\d)', page):
        facts["auth_type"] = FAB_AUTH_TYPES.get(int(match.group(1)), f"type {match.group(1)}")
    providers = set(re.findall(r'href="[^"]*/login/([A-Za-z0-9_-]+)/?(?:\?[^"]*)?"', page))
    if match := re.search(r'"AUTH_PROVIDERS"\s*:\s*\[(.*?)\]', page, re.S):
        providers |= set(re.findall(r'"name"\s*:\s*"([^"]+)"', match.group(1)))
    if providers:
        facts["providers"] = sorted(providers)
    if re.search(r'type=["\']password["\']|name=["\']password["\']', page, re.I):
        facts["password_form"] = True
    if match := re.search(r'"version_string"\s*:\s*"([^"]+)"', page):
        facts["version"] = match.group(1)
    if re.search(r'name=["\']SAMLRequest["\']', page, re.I):
        action = re.search(r'<form[^>]+action=["\']([^"\']+)', page, re.I)
        facts["saml_form"] = action.group(1) if action else ""
    return facts


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _off_host(probe: Probe) -> Hop | None:
    return next((h for h in probe.hops if not h.followed), None)


def check(address: str, client: httpx.Client | None = None, proxy: str | None = None) -> CheckResult:
    base = superset_base(address)
    lines = [f"INFO  Superset base address: {base}", f"INFO  route from this PC: {outbound.describe(base, proxy)}"]
    if base.startswith("http://"):
        lines.append("WARN  the address is http, not https: a connection for Wizard needs HTTPS")
    own = client is None
    if client is None:
        route, _ = outbound.proxy_for(base, proxy)
        client = httpx.Client(timeout=TIMEOUT, verify=outbound.ssl_context(), proxy=route, trust_env=False,
                              headers={"User-Agent": "wizard-bdp-check"})
    probes: list[Probe] = []
    try:
        health = Probe("Health check (/health)")
        probes.append(health)
        try:
            response, _ = follow(client, f"{base}/health", health)
        except httpx.HTTPError as error:
            health.error = outbound.explain(error, base, proxy)
            lines.append(f"FAIL  {health.error}")
            lines.append("INFO  nothing else was tried. Fix the route (or ask IT which proxy reaches this address), "
                         "then run bdp-check again; the browser steps of task 40 do not need it")
            return CheckResult(base, lines, probes)
        gateway = _off_host(health)
        if gateway:
            lines.append(f"WARN  a sign-in gateway sits in front of Superset: even its health check redirects to "
                         f"{gateway.host}. Any program calling Superset must pass that gateway's sign-in first")
        elif response is not None and response.status_code == 200 and response.text.strip().upper() == "OK":
            lines.append("PASS  Superset answers its health check")
        elif response is not None:
            lines.append(f"WARN  the health check answered {response.status_code}; this may not be Superset's address")
        version = Probe("Version (/version, newer Superset releases)")
        probes.append(version)
        response, _ = follow(client, f"{base}/version", version, "application/json")
        body = _json(response) if response is not None and response.status_code == 200 else None
        release = body.get("version_string") if isinstance(body, dict) else None

        login = Probe("Login page (/login/)")
        probes.append(login)
        response, protocol = follow(client, f"{base}/login/", login)
        facts = page_facts(response.text) if response is not None and "html" in response.headers.get("content-type", "") else {}
        target = _off_host(login)
        if target:
            provider = identity_provider(target.host, target.path)
            lines.append(f"INFO  sign-in: {protocol or 'a redirect'} to {provider or 'an identity provider'} "
                         f"({target.host})")
        if facts.get("auth_type"):
            lines.append(f"INFO  Superset's sign-in setting: {facts['auth_type']}")
        if facts.get("providers"):
            lines.append(f"INFO  sign-in buttons on Superset's login page: {', '.join(facts['providers'])}")
        if facts.get("saml_form") is not None:
            host = urlsplit(urljoin(base, facts["saml_form"])).hostname or "unknown host"
            lines.append(f"INFO  sign-in: SAML 2.0, posted to {host}")
        if facts.get("password_form") and not target:
            lines.append("INFO  the login page asks for a user name and password (Superset or LDAP accounts, not the "
                         "company single sign-on page)")
        windows = sorted({s for h in [*health.hops, *login.hops] for s in h.authenticate if s.lower() in ("negotiate", "ntlm")})
        if windows:
            lines.append(f"INFO  Windows integrated sign-in is offered ({', '.join(windows)}): a program on this PC could "
                         "sign in as the Windows user, without a browser")
        if not (target or facts or windows):
            lines.append("WARN  the sign-in route could not be read from the login page; describe what the browser shows")

        api = Probe("REST API (/api/v1/database/)")
        probes.append(api)
        response, _ = follow(client, f"{base}/api/v1/database/", api, "application/json")
        body = _json(response) if response is not None else None
        redirected = _off_host(api)
        if redirected:
            lines.append(f"WARN  the REST API redirects to a sign-in page ({redirected.host}) instead of answering 401: "
                         "programs cannot use it with a token unless the gateway accepts one")
        elif response is not None and response.status_code == 401 and body is not None:
            lines.append("PASS  the REST API answers (401 without a sign-in token, as expected)")
        elif response is not None and response.status_code == 200 and isinstance(body, dict):
            lines.append(f"WARN  the REST API answers without any sign-in ({body.get('count', '?')} databases listed)")
        elif response is not None:
            kind = "JSON" if body is not None else response.headers.get("content-type", "no content type")
            lines.append(f"WARN  the REST API answered {response.status_code} ({kind}): it may be switched off or blocked")

        spec = Probe("API description (/api/v1/_openapi)")
        probes.append(spec)
        response, _ = follow(client, f"{base}/api/v1/_openapi", spec, "application/json")
        body = _json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(body, dict) and isinstance(body.get("paths"), dict):
            paths = [p.rstrip("/") for p in body["paths"]]
            for prefix, meaning in API_FEATURES.items():
                found = any(p.startswith(prefix) for p in paths)
                lines.append(f"INFO  API {'lists' if found else 'does not list'} {prefix} ({meaning})")
        elif response is not None:
            lines.append(f"INFO  the API description is not public ({response.status_code}); the browser steps cover it")
        if release or facts.get("version"):
            lines.append(f"INFO  Superset version: {release or facts['version']}")
    except httpx.HTTPError as error:
        lines.append(f"FAIL  {outbound.explain(error, base, proxy)}")
    finally:
        if own:
            client.close()
    lines.append("INFO  next: the signed-in browser steps of task 40 (which engines sit behind Superset)")
    return CheckResult(base, lines, probes)


def write(content: Path, result: CheckResult) -> Path:
    folder = content / "inbox" / "bdp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "superset-check.md"
    path.write_text(result.markdown(dt.date.today().isoformat()), encoding="utf-8")
    return path


def describe_databases(saved: Path) -> list[str]:
    """Summarise the database list a user saved from `/api/v1/database/` while signed in: name, engine and settings.
    Raises ValueError when the file is not that page."""
    try:
        data = json.loads(saved.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{saved.name} is not the saved database list ({error})") from None
    rows = data.get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        message = data.get("message") or data.get("msg") if isinstance(data, dict) else None
        raise ValueError(f"{saved.name} is not the database list" + (f": Superset said '{message}'" if message else ""))
    lines = [f"{len(rows)} database(s) in {saved.name}"]
    for row in rows:
        flags = [f"{key} {'yes' if row.get(key) else 'no'}" for key in ("allow_dml", "allow_run_async", "expose_in_sqllab")
                 if key in row]
        lines.append(f"- {row.get('database_name', '?')} (id {row.get('id', '?')}): engine {row.get('backend') or 'not shown'}"
                     + (f"; {', '.join(flags)}" if flags else ""))
    return lines

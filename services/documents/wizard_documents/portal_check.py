"""Read-only discovery of a report portal from this PC (`gscm-check`, `asap-check`, task 41).

Before Wizard explores a portal in its own browser, or before anyone builds an API adapter for it, this answers:
- does the portal answer from this PC, through the proxy and certificate store Wizard itself would use;
- what it is built on (MicroStrategy, SAP BusinessObjects, Power BI Report Server, Tableau, Oracle Analytics, Qlik,
  Cognos, Superset, or a company web application), from its pages, headers, paths and cookie names;
- how it signs people in: the redirect to the identity provider and the protocol, a password form, or Windows
  integrated sign-in;
- for MicroStrategy, whether its Library REST API answers (`/api/status` needs no sign-in).

It sends anonymous GET requests only, like bdp-check: no sign-in, no credentials, no browser cookies. Redirects that
leave the portal's host are recorded, never followed; parameter values and cookie values are never kept."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

import wizard_agent.outbound as outbound

from .bdp import TIMEOUT, Probe, _json, _off_host, follow, identity_provider, page_facts

SYSTEMS = {"gscm": "GSCM", "asap": "ASAP"}
# (product, what to look for in the page, the paths or the headers). Checked in order; the first match names it.
PLATFORMS: list[tuple[str, re.Pattern[str]]] = [
    ("MicroStrategy", re.compile(r"microstrategy|mstrweb|/MicroStrategyLibrary|mstr-", re.I)),
    ("SAP BusinessObjects (BI launch pad)", re.compile(r"BI launch pad|BusinessObjects|/BOE/|InfoView", re.I)),
    ("SAP Analytics Cloud", re.compile(r"sapanalytics\.cloud|SAP Analytics Cloud", re.I)),
    ("SAP Fiori / NetWeaver", re.compile(r"sap-ui-core|/sap/bc/|SAP NetWeaver", re.I)),
    ("Power BI Report Server / SSRS", re.compile(r"Power BI Report Server|/ReportServer|/Reports/powerbi|SQL Server Reporting", re.I)),
    ("Power BI (cloud)", re.compile(r"app\.powerbi\.com", re.I)),
    ("Tableau Server", re.compile(r"vizportal|tableau server|tableau software|tableausoftware", re.I)),
    ("Oracle Analytics / OBIEE", re.compile(r"saw\.dll|Oracle Business Intelligence|Oracle Analytics", re.I)),
    ("Qlik Sense", re.compile(r"qlik|/hub/", re.I)),
    ("IBM Cognos Analytics", re.compile(r"ibmcognos|Cognos", re.I)),
    ("Apache Superset", re.compile(r"superset", re.I)),
    ("Grafana", re.compile(r"grafana", re.I)),
    ("Looker", re.compile(r"\blooker\b", re.I)),
    ("TIBCO Spotfire", re.compile(r"spotfire", re.I)),
]
FRAMEWORKS = [("Angular", re.compile(r"ng-version|angular", re.I)), ("React", re.compile(r"data-reactroot|__NEXT_DATA__|react-dom", re.I)),
              ("Vue", re.compile(r"data-v-|__vue|vue\.(min\.)?js", re.I)), ("ASP.NET", re.compile(r"__VIEWSTATE|asp\.net", re.I)),
              ("Java servlet (JSP/JSF)", re.compile(r"\.jsp\b|javax\.faces|jsessionid", re.I))]
COOKIE_HINTS = {"jsessionid": "Java application server", "asp.net_sessionid": "ASP.NET", "mstrwebsession": "MicroStrategy Web",
                "mstr": "MicroStrategy", "sap-usercontext": "SAP", "workgroup_session_id": "Tableau", "x-qlik-session": "Qlik"}


@dataclass
class PortalCheck:
    system: str
    base: str
    lines: list[str]
    probes: list[Probe]

    def markdown(self, today: str) -> str:
        name = SYSTEMS.get(self.system, self.system.upper())
        out = [f"# {name} portal check ({today})", "", f"Portal address: {self.base}", "",
               f"Made by `.\\docs.ps1 {self.system}-check`: anonymous GET requests only (no sign-in, no cookies). Parameter "
               "and cookie values are left out on purpose.", "", "## Results", "", "```", *self.lines, "```", "",
               "## Requests", ""]
        for probe in self.probes:
            out += [f"### {probe.name}", ""]
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


def portal_base(address: str) -> str:
    """The address as typed, normalised: https:// added when missing, a user name or password in it dropped."""
    raw = address.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"'{address}' is not a web address. Copy it from the browser tab where the portal is open.")
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{host}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


def fingerprint(text: str, paths: list[str], headers: httpx.Headers | None) -> tuple[str | None, list[str]]:
    """The platform a portal runs on and the clues that say so (page text, paths, headers and cookie names)."""
    header_text = " ".join(f"{k}: {v}" for k, v in (headers or {}).items() if k.lower() not in ("set-cookie",))
    haystack = "\n".join([text[:400_000], *paths, header_text])
    clues = []
    platform = next((name for name, pattern in PLATFORMS if pattern.search(haystack)), None)
    cookies = [c.split("=", 1)[0].strip() for c in (headers.get_list("set-cookie") if headers else [])]
    for cookie in cookies:
        hint = next((v for k, v in COOKIE_HINTS.items() if cookie.lower().startswith(k)), None)
        if hint:
            clues.append(f"cookie {cookie} ({hint})")
    for header in ("server", "x-powered-by", "x-aspnet-version"):
        if headers and headers.get(header):
            clues.append(f"{header}: {headers[header][:60]}")
    frameworks = [name for name, pattern in FRAMEWORKS if pattern.search(text[:400_000])]
    if frameworks:
        clues.append("page built with " + ", ".join(frameworks))
    return platform, clues


def library_base(base: str, final_path: str) -> str:
    """Where MicroStrategy Library lives: the path up to MicroStrategyLibrary, else /MicroStrategyLibrary on the host."""
    parts = urlsplit(base)
    match = re.search(r"^(.*?/MicroStrategyLibrary[^/]*)", final_path, re.I)
    root = f"{parts.scheme}://{parts.netloc}"
    return root + (match.group(1) if match else "/MicroStrategyLibrary")


def check(system: str, address: str, client: httpx.Client | None = None, proxy: str | None = None) -> PortalCheck:
    base = portal_base(address)
    name = SYSTEMS.get(system, system.upper())
    lines = [f"INFO  {name} address: {base}", f"INFO  route from this PC: {outbound.describe(base, proxy)}"]
    if base.startswith("http://"):
        lines.append("WARN  the address is http, not https: Wizard's portal browser needs HTTPS")
    own = client is None
    if client is None:
        route, _ = outbound.proxy_for(base, proxy)
        client = httpx.Client(timeout=TIMEOUT, verify=outbound.ssl_context(), proxy=route, trust_env=False,
                              headers={"User-Agent": f"wizard-{system}-check"})
    probes: list[Probe] = []
    try:
        start = Probe("Start page")
        probes.append(start)
        try:
            response, protocol = follow(client, base, start)
        except httpx.HTTPError as error:
            start.error = outbound.explain(error, base, proxy)
            lines.append(f"FAIL  {start.error}")
            lines.append("INFO  nothing else was tried. Fix the route (or ask IT which proxy reaches this address), then "
                         f"run {system}-check again")
            return PortalCheck(system, base, lines, probes)
        if response is not None and response.status_code < 400:
            lines.append(f"PASS  {name} answers ({response.status_code})")
        elif response is not None and response.status_code in (401, 403):
            lines.append(f"INFO  {name} answers {response.status_code} without a sign-in (expected for a portal)")
        elif response is not None:
            lines.append(f"WARN  {name} answered {response.status_code}; check the address")
        text = response.text if response is not None and "html" in response.headers.get("content-type", "") else ""
        paths = [h.path for h in start.hops]
        platform, clues = fingerprint(text, paths, response.headers if response is not None else None)
        lines.append(f"INFO  platform: {platform or 'not recognised (a company web application, or a sign-in page hides it)'}")
        for clue in clues:
            lines.append(f"INFO  clue: {clue}")

        target = _off_host(start)
        if target:
            provider = identity_provider(target.host, target.path)
            lines.append(f"INFO  sign-in: {protocol or 'a redirect'} to {provider or 'an identity provider'} ({target.host})")
            lines.append(f"INFO  if Wizard's portal browser stops on that page, add {target.host} to "
                         "WIZARD_PORTAL_SIGNIN_HOSTS (Settings → Portals)")
        facts = page_facts(text) if text else {}
        if facts.get("password_form") and not target:
            lines.append("INFO  the start page asks for a user name and password (the portal's own sign-in)")
        if facts.get("saml_form") is not None:
            lines.append("INFO  sign-in: SAML 2.0 (a form posted to the identity provider)")
        windows = sorted({s for h in start.hops for s in h.authenticate if s.lower() in ("negotiate", "ntlm")})
        if windows:
            lines.append(f"INFO  Windows integrated sign-in is offered ({', '.join(windows)})")
        if not (target or facts.get("password_form") or windows or facts.get("saml_form") is not None):
            lines.append("INFO  no sign-in was asked for on the start page (it may come when a report opens)")

        if platform == "MicroStrategy" or system == "asap":
            library = library_base(base, start.hops[-1].path if start.hops else "")
            status = Probe("MicroStrategy Library REST API (/api/status)")
            probes.append(status)
            response, _ = follow(client, f"{library}/api/status", status, "application/json")
            body = _json(response) if response is not None else None
            if response is not None and response.status_code == 200 and isinstance(body, dict):
                version = body.get("webVersion") or body.get("version") or body.get("iServerVersion")
                lines.append(f"PASS  MicroStrategy Library REST API answers at {urlsplit(library).path}"
                             + (f" (version {version})" if version else ""))
            elif _off_host(status):
                lines.append("WARN  the Library REST API redirects to a sign-in page: an API adapter would need the "
                             "gateway's sign-in first")
            elif response is not None:
                lines.append(f"INFO  the Library REST API answered {response.status_code} at {urlsplit(library).path} "
                             "(not public here, or Library lives elsewhere)")
    except httpx.HTTPError as error:
        lines.append(f"FAIL  {outbound.explain(error, base, proxy)}")
    finally:
        if own:
            client.close()
    lines.append(f"INFO  next: Settings → Portals → {name} address, then Sources → Portals → {name} → Sign in (task 41)")
    return PortalCheck(system, base, lines, probes)


def write(content: Path, result: PortalCheck) -> Path:
    folder = content / "inbox" / result.system
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "portal-check.md"
    path.write_text(result.markdown(dt.date.today().isoformat()), encoding="utf-8")
    return path

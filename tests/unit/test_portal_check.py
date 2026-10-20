"""gscm-check and asap-check against simulated portals: the platform recognised from pages, paths, headers and cookie
names; the sign-in route read from redirects without visiting the identity provider; MicroStrategy's Library REST
status; the CLI; and that only anonymous GETs to the portal's own host are sent, with parameter and cookie values left
out."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.unit.test_bdp_check import Server, redirect

from wizard_documents import portal_check
from wizard_documents.cli import main

GSCM = "https://gscm.corp.example"
ASAP = "https://asap.corp.example"
ENTRA = ("https://login.microsoftonline.com/tenant-1/oauth2/v2.0/authorize?response_type=code&client_id=a1b2c3"
         "&scope=openid&state=st4te&redirect_uri=https%3A%2F%2Fgscm.corp.example%2Fcallback")


def html(text: str, **headers: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"Content-Type": "text/html; charset=utf-8", **headers})


def client(server: Server, base: str) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(server), base_url=base)


def test_a_company_app_behind_entra_sign_in() -> None:
    server = Server({"/portal/": redirect("/portal/home"), "/portal/home": redirect(ENTRA)})
    result = portal_check.check("gscm", f"{GSCM}/portal/", client=client(server, GSCM))
    text = "\n".join(result.lines)
    assert "INFO  sign-in: OpenID Connect to Microsoft Entra ID (login.microsoftonline.com)" in text
    assert "add login.microsoftonline.com to WIZARD_PORTAL_SIGNIN_HOSTS" in text
    assert "platform: not recognised" in text
    assert {r.url.host for r in server.requests} == {"gscm.corp.example"}, "the identity provider is never requested"
    assert {r.method for r in server.requests} == {"GET"}
    assert not any("authorization" in r.headers or "cookie" in r.headers for r in server.requests)
    markdown = result.markdown("2026-10-20")
    assert markdown.startswith("# GSCM portal check (2026-10-20)") and "not requested (other host)" in markdown
    for value in ("st4te", "a1b2c3", "callback"):
        assert value not in markdown, "parameter values are never kept"


def test_the_platform_is_recognised_from_page_headers_and_cookie_names() -> None:
    page = '<html ng-version="17.1"><title>Supply chain</title><form><input name="u"><input type="password" name="p"></form></html>'
    server = Server({"/": html(page, **{"Server": "Apache-Coyote/1.1", "Set-Cookie": "JSESSIONID=SECRET123; Path=/",
                                        "WWW-Authenticate": "Negotiate"})})
    text = "\n".join(portal_check.check("gscm", GSCM, client=client(server, GSCM)).lines)
    assert "PASS  GSCM answers (200)" in text
    assert "INFO  clue: cookie JSESSIONID (Java application server)" in text and "SECRET123" not in text
    assert "INFO  clue: server: Apache-Coyote/1.1" in text and "INFO  clue: page built with Angular" in text
    assert "the start page asks for a user name and password" in text
    assert "Windows integrated sign-in is offered (Negotiate)" in text
    bo = Server({"/BOE/BI": html("<title>BI launch pad</title>")})
    assert "INFO  platform: SAP BusinessObjects (BI launch pad)" in portal_check.check("gscm", f"{GSCM}/BOE/BI", client=client(bo, GSCM)).lines


def test_asap_on_microstrategy_library_and_its_rest_status() -> None:
    server = Server({"/MicroStrategyLibrary/app": html('<div id="root" class="mstr-library">MicroStrategy Library</div>'),
                     "/MicroStrategyLibrary/api/status": httpx.Response(200, json={"webVersion": "11.4.0900"})})
    text = "\n".join(portal_check.check("asap", f"{ASAP}/MicroStrategyLibrary/app", client=client(server, ASAP)).lines)
    assert "INFO  platform: MicroStrategy" in text
    assert "PASS  MicroStrategy Library REST API answers at /MicroStrategyLibrary (version 11.4.0900)" in text
    gated = Server({}, default=redirect("https://sso.corp.example/adfs/ls/?SAMLRequest=abc"))
    text = "\n".join(portal_check.check("asap", ASAP, client=client(gated, ASAP)).lines)
    assert "INFO  sign-in: SAML 2.0 to AD FS (sso.corp.example)" in text
    assert "WARN  the Library REST API redirects to a sign-in page" in text


def test_addresses_and_unreachable_portals() -> None:
    assert portal_check.portal_base("gscm.corp.example/portal?x=1") == "https://gscm.corp.example/portal?x=1"
    assert portal_check.portal_base("https://me:pw@gscm.corp.example:8443") == "https://gscm.corp.example:8443/"
    with pytest.raises(ValueError, match="not a web address"):
        portal_check.portal_base("ftp://gscm")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)
    result = portal_check.check("gscm", GSCM, client=httpx.Client(transport=httpx.MockTransport(refuse)), proxy="direct")
    assert any(line.startswith("FAIL") for line in result.lines) and len(result.probes) == 1


def test_cli_reads_the_address_from_env_and_writes_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / ".env").write_text(f"WIZARD_PORTAL_GSCM={GSCM}/portal/\nWIZARD_PROXY=direct\n", encoding="utf-8")
    seen: dict[str, object] = {}
    real = portal_check.check

    def fake(system: str, address: str, client: httpx.Client | None = None, proxy: str | None = None) -> portal_check.PortalCheck:
        seen.update(system=system, address=address, proxy=proxy)
        return real(system, address, client=httpx.Client(transport=httpx.MockTransport(Server({"/portal/": html("ok")})),
                                                         base_url=GSCM))
    monkeypatch.setattr(portal_check, "check", fake)
    assert main(["gscm-check", str(content)]) == 0
    assert seen == {"system": "gscm", "address": f"{GSCM}/portal/", "proxy": "direct"}
    assert "PASS  GSCM answers (200)" in (content / "inbox" / "gscm" / "portal-check.md").read_text(encoding="utf-8")
    assert "Written to inbox/gscm/portal-check.md" in capsys.readouterr().out
    assert main(["asap-check", str(content)]) == 2  # no WIZARD_PORTAL_ASAP and no --url
    assert "--url" in capsys.readouterr().out

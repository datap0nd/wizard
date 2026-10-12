"""bdp-check against simulated Superset servers: the base address, the sign-in route read from redirects and login pages,
a gateway in front of Superset, the REST API, the saved database list, the CLI, and that only anonymous GETs to
Superset's own host are ever sent, with redirect parameter values left out."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from wizard_documents import bdp
from wizard_documents.cli import main

BASE = "https://bdp.corp.example"
ENTRA = ("https://login.microsoftonline.com/0f0e0d0c-tenant/oauth2/v2.0/authorize?response_type=code&client_id=c1d2e3"
         "&scope=openid+email&state=s3cr3tstate&redirect_uri=https%3A%2F%2Fbdp.corp.example%2Foauth-authorized%2Fazure")


class Server:
    """Answers by path; records every request."""

    def __init__(self, routes: dict[str, httpx.Response], default: httpx.Response | None = None):
        self.routes, self.default = routes, default or httpx.Response(404)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes.get(request.url.path, self.default)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), base_url=BASE)


def redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"Location": location})


def unauthorized() -> httpx.Response:
    return httpx.Response(401, json={"msg": "Missing Authorization Header"})


def oauth_superset() -> Server:
    return Server({"/health": httpx.Response(200, text="OK"), "/version": httpx.Response(200, json={"version_string": "5.0.0"}),
                   "/login/": redirect("/login/azure"),
                   "/login/azure": redirect(ENTRA), "/api/v1/database/": unauthorized(),
                   "/api/v1/_openapi": unauthorized()})


@pytest.mark.parametrize(("address", "base"), [
    ("https://bdp.corp.example/sqllab/?savedQueryId=3", BASE),
    ("bdp.corp.example/superset/sqllab/", BASE),
    ("https://me:pw@bdp.corp.example:8443/bi/superset/welcome/", "https://bdp.corp.example:8443/bi"),
    ("https://bdp.corp.example/", BASE),
])
def test_base_address_is_cut_before_superset_pages(address, base):
    assert bdp.superset_base(address) == base


def test_not_an_address_is_refused():
    with pytest.raises(ValueError, match="not a web address"):
        bdp.superset_base("ftp://bdp")


def test_oauth_sign_in_is_read_from_redirects_without_visiting_the_identity_provider():
    server = oauth_superset()
    result = bdp.check(f"{BASE}/sqllab/", client=server.client())
    text = "\n".join(result.lines)
    assert "PASS  Superset answers its health check" in text
    assert "INFO  sign-in: OpenID Connect to Microsoft Entra ID (login.microsoftonline.com)" in text
    assert "PASS  the REST API answers (401" in text
    assert "API description is not public (401)" in text
    assert "INFO  Superset version: 5.0.0" in text
    assert {r.url.host for r in server.requests} == {"bdp.corp.example"}, "the identity provider is never requested"
    assert {r.method for r in server.requests} == {"GET"}
    assert not any("authorization" in r.headers or "cookie" in r.headers for r in server.requests)
    markdown = result.markdown("2026-10-12")
    assert "client_id, redirect_uri, response_type, scope, state" in markdown and "not requested (other host)" in markdown
    for value in ("s3cr3tstate", "c1d2e3", "oauth-authorized"):
        assert value not in markdown, "parameter values are never kept"


def test_a_gateway_in_front_of_superset_is_reported():
    saml = "https://sso.corp.example/adfs/ls/?SAMLRequest=fZJdb4IwFIb%2F&RelayState=abc"
    server = Server({}, default=redirect(saml))
    text = "\n".join(bdp.check(BASE, client=server.client()).lines)
    assert "WARN  a sign-in gateway sits in front of Superset: even its health check redirects to sso.corp.example" in text
    assert "INFO  sign-in: SAML 2.0 to AD FS (sso.corp.example)" in text
    assert "WARN  the REST API redirects to a sign-in page (sso.corp.example)" in text


def test_login_page_facts_and_windows_sign_in():
    bootstrap = json.dumps({"common": {"conf": {"AUTH_TYPE": 1, "AUTH_PROVIDERS": []},
                                       "menu_data": {"navbar_right": {"version_string": "4.1.2"}}}})
    page = (f'<div id="app" data-bootstrap="{bootstrap.replace(chr(34), "&#34;")}"></div>'
            '<form method="post"><input name="username"><input type="password" name="password"></form>')
    server = Server({"/health": httpx.Response(200, text="OK"),
                     "/login/": httpx.Response(200, text=page, headers={"Content-Type": "text/html; charset=utf-8",
                                                                         "WWW-Authenticate": "Negotiate"}),
                     "/api/v1/database/": unauthorized(),
                     "/api/v1/_openapi": httpx.Response(200, json={"paths": {"/api/v1/sqllab/execute/": {},
                                                                             "/api/v1/security/login": {}}})})
    text = "\n".join(bdp.check(BASE, client=server.client()).lines)
    assert "INFO  Superset's sign-in setting: Superset's own user names and passwords" in text
    assert "the login page asks for a user name and password" in text
    assert "Windows integrated sign-in is offered (Negotiate)" in text
    assert "INFO  API lists /api/v1/sqllab/execute (run SQL as SQL Lab does)" in text
    assert "INFO  API does not list /api/v1/me/roles" in text
    assert "INFO  Superset version: 4.1.2" in text


def test_oauth_buttons_on_an_older_login_page():
    page = '<a href="/login/azure?next=">Azure</a> <a href="/login/okta">Okta</a>'
    server = Server({"/health": httpx.Response(200, text="OK"),
                     "/login/": httpx.Response(200, text=page, headers={"Content-Type": "text/html"})},
                    default=unauthorized())
    assert "INFO  sign-in buttons on Superset's login page: azure, okta" in bdp.check(BASE, client=server.client()).lines


def test_unreachable_superset_stops_with_a_readable_failure():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = bdp.check(BASE, client=httpx.Client(transport=httpx.MockTransport(refuse)))
    assert result.lines[-2].startswith("FAIL  Wizard could not reach bdp.corp.example: the connection failed")
    assert "nothing else was tried" in result.lines[-1]


def test_saved_database_list_is_summarised(tmp_path: Path):
    saved = tmp_path / "superset-databases.json"
    saved.write_text(json.dumps({"count": 2, "result": [
        {"id": 1, "database_name": "Lake", "backend": "trino", "allow_dml": False, "allow_run_async": True,
         "expose_in_sqllab": True},
        {"id": 4, "database_name": "Legacy", "backend": "hive"}]}), encoding="utf-8")
    assert bdp.describe_databases(saved) == [
        "2 database(s) in superset-databases.json",
        "- Lake (id 1): engine trino; allow_dml no, allow_run_async yes, expose_in_sqllab yes",
        "- Legacy (id 4): engine hive"]
    saved.write_text('{"message": "Forbidden"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Superset said 'Forbidden'"):
        bdp.describe_databases(saved)
    saved.write_text("<html>Sign in</html>", encoding="utf-8")
    with pytest.raises(ValueError, match="not the saved database list"):
        bdp.describe_databases(saved)


def test_cli_writes_the_check_and_adds_the_saved_databases(tmp_path: Path, monkeypatch, capsys):
    content = tmp_path / "content"
    (content / "inbox" / "bdp").mkdir(parents=True)
    (content / "inbox" / "bdp" / "superset-databases.json").write_text(
        json.dumps({"result": [{"id": 1, "database_name": "Lake", "backend": "trino"}]}), encoding="utf-8")
    (tmp_path / ".env").write_text(f"WIZARD_BDP_URL={BASE}/sqllab/\nWIZARD_PROXY=direct\n", encoding="utf-8")
    seen = {}
    real_check = bdp.check

    def fake_check(address, client=None, proxy=None):
        seen.update(address=address, proxy=proxy)
        return real_check(address, client=oauth_superset().client())

    monkeypatch.setattr(bdp, "check", fake_check)
    assert main(["bdp-check", str(content)]) == 0
    assert seen == {"address": f"{BASE}/sqllab/", "proxy": "direct"}
    written = (content / "inbox" / "bdp" / "superset-check.md").read_text(encoding="utf-8")
    assert "INFO  - Lake (id 1): engine trino" in written and "PASS  the REST API answers" in written
    assert "Written to inbox/bdp/superset-check.md" in capsys.readouterr().out


def test_cli_asks_for_the_address(tmp_path: Path, capsys):
    (tmp_path / "content").mkdir()
    assert main(["bdp-check", str(tmp_path / "content")]) == 2
    assert "--url" in capsys.readouterr().out

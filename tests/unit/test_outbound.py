"""Outbound HTTPS from a corporate PC: proxy resolution order, OS certificate store, the CLI's proxy environment."""
from __future__ import annotations

import json
import ssl

import httpx
import pytest

from wizard_agent import outbound
from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime

URL = "https://cloudcode-pa.googleapis.com/"
GITHUB = "https://github.sec.samsung.net/api/v3"
WINDOWS_LOOKUP = outbound._windows_system_proxy  # the real one, before the fixture below replaces it


@pytest.fixture(autouse=True)
def no_windows_lookup(monkeypatch):
    monkeypatch.setattr(outbound, "_windows_system_proxy", lambda url: "http://pac-proxy.example:8080")


def test_proxy_resolution_order(tmp_path):
    profile = tmp_path / "profile"
    (profile / ".gemini").mkdir(parents=True)
    (profile / ".gemini" / "settings.json").write_text(json.dumps({"proxy": "cli-proxy.example:3128"}), encoding="utf-8")
    env = {"USERPROFILE": str(profile), "HTTPS_PROXY": "http://env-proxy.example:80"}
    assert outbound.proxy_for(URL, "http://override.example:1", env) == ("http://override.example:1", "WIZARD_PROXY")
    assert outbound.proxy_for(URL, "direct", env) == (None, "WIZARD_PROXY")
    assert outbound.proxy_for(URL, None, env) == ("http://env-proxy.example:80", "HTTPS_PROXY")
    env.pop("HTTPS_PROXY")
    assert outbound.proxy_for(URL, None, env) == ("http://cli-proxy.example:3128", "your Gemini CLI settings")
    env["USERPROFILE"] = str(tmp_path / "nobody")
    expected = ("http://pac-proxy.example:8080", "Windows proxy settings") if outbound.os.name == "nt" else (None, "direct")
    assert outbound.proxy_for(URL, None, env) == expected
    assert outbound.proxy_for(URL, None, {**env, "NO_PROXY": ".googleapis.com"}) == (None, "NO_PROXY")


def test_os_certificate_store_is_used():
    assert isinstance(outbound.ssl_context(), ssl.SSLContext)
    assert outbound.trust_label() in ("Windows certificate store", "system certificate store")


def test_explain_names_the_cause_and_the_fix():
    tls = outbound.explain(httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]"), "https://oauth2.googleapis.com/token", "direct")
    assert "oauth2.googleapis.com" in tls and "TLS certificate is not trusted" in tls and "WIZARD_PROXY" in tls
    assert "proxy refused" in outbound.explain(httpx.ProxyError("407"), URL, "http://p:1")


def test_cli_gets_the_resolved_proxy_and_system_ca(tmp_path, monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    runtime = GeminiCliRuntime(GeminiCliConfig(model="m", internal_url="http://127.0.0.1:1", proxy="http://corp-proxy:8080"))
    env = runtime._base_env(tmp_path)
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://corp-proxy:8080"
    assert "127.0.0.1" in env["NO_PROXY"] and env["NODE_USE_SYSTEM_CA"] == "1"
    direct = GeminiCliRuntime(GeminiCliConfig(model="m", internal_url="", proxy="direct"))._base_env(tmp_path)
    assert "HTTPS_PROXY" not in direct
    monkeypatch.setenv("HTTPS_PROXY", "http://already-set:1")
    kept = GeminiCliRuntime(GeminiCliConfig(model="m", internal_url=""))._base_env(tmp_path)
    assert kept["HTTPS_PROXY"] == "http://already-set:1", "an explicit environment proxy is kept"


def test_the_company_github_takes_the_route_windows_and_edge_take(tmp_path):
    """Owner, 30 Oct 2026: map uploads went through the proxy in Gemini CLI's settings, a McAfee web gateway that
    refused them, while Edge commits to the same server. The company GitHub is routed the Windows way: Settings' own
    proxy for it, NO_PROXY, the Windows proxy settings, direct; never WIZARD_PROXY or Gemini CLI's proxy."""
    profile = tmp_path / "profile"
    (profile / ".gemini").mkdir(parents=True)
    (profile / ".gemini" / "settings.json").write_text(json.dumps({"proxy": "gateway.example:8080"}), encoding="utf-8")
    env = {"USERPROFILE": str(profile)}
    assert outbound.proxy_for(GITHUB, None, env)[0] == "http://gateway.example:8080", "Google traffic is unchanged"
    assert outbound.windows_route(GITHUB, None, env, windows=True) == ("http://pac-proxy.example:8080", "Windows proxy settings")
    assert outbound.windows_route(GITHUB, "direct", env, windows=True) == (None, "Settings: company GitHub proxy")
    assert outbound.windows_route(GITHUB, "proxy.corp:3128", env, windows=True) == ("http://proxy.corp:3128",
                                                                                    "Settings: company GitHub proxy")
    assert outbound.windows_route(GITHUB, None, {**env, "NO_PROXY": ".samsung.net"}, windows=True) == (None, "NO_PROXY")
    assert outbound.windows_route(GITHUB, None, env, windows=False) == (None, "direct"), "never Gemini CLI's proxy"
    assert outbound.windows_route(GITHUB, None, {**env, "HTTPS_PROXY": "http://dev:1"}, windows=False)[0] == "http://dev:1"
    assert outbound.describe(GITHUB, "direct", windows=True).startswith("direct (Settings: company GitHub proxy)")
    failed = outbound.explain(httpx.ConnectError("refused"), GITHUB, None, windows=True)
    assert "Company GitHub proxy (WIZARD_GITHUB_PROXY)" in failed and "WIZARD_PROXY=" not in failed


def test_windows_proxy_lists_and_bypass_lists_are_read_as_windows_reads_them():
    assert outbound._pick("gw1.corp:8080; gw2.corp:8080", "https://x") == "http://gw1.corp:8080"
    assert outbound._pick("http=gw.corp:80;https=gws.corp:443", "https://x") == "http://gws.corp:443"
    assert outbound._pick("http=gw.corp:80", "https://x") == "http://gw.corp:80"
    assert outbound._pick("", "https://x") is None
    bypass = "*.samsung.net; 10.*;<local>"
    assert outbound._windows_bypassed("github.sec.samsung.net", bypass)
    assert outbound._windows_bypassed("intranet", bypass) and outbound._windows_bypassed("10.1.2.3", bypass)
    assert not outbound._windows_bypassed("oauth2.googleapis.com", bypass)


def test_the_windows_proxy_is_read_in_process_and_powershell_only_if_that_fails(monkeypatch):
    """Owner, 30 Oct 2026: Defender reported Wizard's hidden PowerShell as malware. WinHTTP answers in this process."""
    started: list[list[str]] = []
    monkeypatch.setattr(outbound.subprocess, "run", lambda command, **kwargs: started.append(command) or
                        outbound.subprocess.CompletedProcess(command, 0, "http://ps-proxy.example:8080\n", ""))
    outbound._system_proxy_cache.clear()
    monkeypatch.setattr(outbound, "_winhttp_proxy", lambda url: None)
    assert WINDOWS_LOOKUP(GITHUB) is None and started == [], "WinHTTP said direct: no PowerShell"
    outbound._system_proxy_cache.clear()

    def missing(url):
        raise OSError("winhttp unavailable")

    monkeypatch.setattr(outbound, "_winhttp_proxy", missing)
    assert WINDOWS_LOOKUP(GITHUB) == "http://ps-proxy.example:8080" and len(started) == 1
    assert WINDOWS_LOOKUP(GITHUB) == "http://ps-proxy.example:8080" and len(started) == 1, "asked once per host"
    outbound._system_proxy_cache.clear()

"""Outbound HTTPS from a corporate PC: proxy resolution order, OS certificate store, the CLI's proxy environment."""
from __future__ import annotations

import json
import ssl

import httpx
import pytest

from wizard_agent import outbound
from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime

URL = "https://cloudcode-pa.googleapis.com/"


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

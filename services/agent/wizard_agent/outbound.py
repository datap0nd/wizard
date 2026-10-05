"""Outbound HTTPS to Google from a corporate PC.

Two things break Python there while the browser and Gemini CLI work (the data-governance app hit both on the same PCs):
- TLS inspection re-signs HTTPS with a corporate root that is in the Windows certificate store but not in Python's
  certifi bundle, so every call fails certificate verification. `truststore` verifies against the OS store instead.
- The proxy is often configured only in Windows (frequently a PAC script), which Python does not evaluate. Resolution
  order: WIZARD_PROXY, HTTPS_PROXY/HTTP_PROXY, the `proxy` in the user's own Gemini CLI settings (known to work on this
  PC), the Windows system proxy evaluated for the URL (PAC included), then direct.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import ssl
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("wizard.outbound")
DIRECT = ("direct", "none", "off")
_system_proxy_cache: dict[str, str | None] = {}


@functools.cache
def ssl_context() -> ssl.SSLContext:
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 - not installed or unsupported platform: Python's own bundle
        return httpx.create_ssl_context()


def trust_label() -> str:
    if type(ssl_context()).__module__.startswith("truststore"):
        return "Windows certificate store" if os.name == "nt" else "system certificate store"
    return "Python certificate bundle"


def _normalize(value: str) -> str | None:
    value = value.strip().rstrip("/")
    if not value or value.lower() in DIRECT:
        return None
    return value if "://" in value else f"http://{value}"


def _bypassed(host: str, env: dict[str, str]) -> bool:
    raw = env.get("NO_PROXY") or env.get("no_proxy") or ""
    for entry in (e.strip().lower().lstrip("*") for e in raw.split(",")):
        if entry and (host == entry.lstrip(".") or host.endswith(entry if entry.startswith(".") else f".{entry}")):
            return True
    return False


def _gemini_cli_proxy(user_profile: str | None) -> str | None:
    if not user_profile:
        return None
    try:
        settings = json.loads((Path(user_profile) / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    proxy = settings.get("proxy") if isinstance(settings, dict) else None
    return proxy if isinstance(proxy, str) and proxy.strip() else None


def _windows_system_proxy(url: str) -> str | None:
    host = urlsplit(url).netloc
    if host in _system_proxy_cache:
        return _system_proxy_cache[host]
    proxy = None
    script = ("$ErrorActionPreference='SilentlyContinue';"
              f"$u=[Uri]'{url}';"
              "$p=[System.Net.WebRequest]::GetSystemWebProxy().GetProxy($u);"
              "if ($p -and $p.AbsoluteUri -ne $u.AbsoluteUri) { Write-Output $p.AbsoluteUri }")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        proxy = _normalize(lines[-1]) if lines else None
    except (OSError, subprocess.SubprocessError):
        log.exception("could not read the Windows system proxy for %s", host)
    _system_proxy_cache[host] = proxy
    return proxy


def proxy_for(url: str, override: str | None = None, env: dict[str, str] | None = None) -> tuple[str | None, str]:
    """(proxy URL or None for direct, where it came from)."""
    env = dict(os.environ) if env is None else env
    if override is not None and override.strip():
        return _normalize(override), "WIZARD_PROXY"
    if _bypassed(urlsplit(url).hostname or "", env):
        return None, "NO_PROXY"
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if env.get(name):
            return _normalize(env[name]), name
    cli = _gemini_cli_proxy(env.get("USERPROFILE") or env.get("HOME"))
    if cli:
        return _normalize(cli), "your Gemini CLI settings"
    if os.name == "nt":
        proxy = _windows_system_proxy(url)
        if proxy:
            return proxy, "Windows proxy settings"
    return None, "direct"


def client(url: str, *, override: str | None = None, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
    """An HTTP client for `url`'s host that trusts the OS certificate store and uses the resolved proxy."""
    proxy, _ = proxy_for(url, override)
    return httpx.AsyncClient(timeout=timeout, verify=ssl_context(), proxy=proxy, trust_env=False)


def describe(url: str, override: str | None = None) -> str:
    proxy, source = proxy_for(url, override)
    route = f"proxy {proxy} (from {source})" if proxy else ("direct (WIZARD_PROXY=direct)" if source == "WIZARD_PROXY"
                                                             else "direct, no proxy configured")
    return f"{route}; certificates: {trust_label()}"


def explain(error: httpx.HTTPError, url: str, override: str | None = None) -> str:
    """A sentence a user can act on, instead of a stack trace."""
    host = urlsplit(url).hostname or url
    text = f"{type(error).__name__}: {error}"
    if "CERTIFICATE_VERIFY_FAILED" in text or "certificate" in text.lower():
        cause = ("the connection's TLS certificate is not trusted (corporate TLS inspection). Wizard checks certificates "
                 "against " + trust_label())
    elif isinstance(error, httpx.ProxyError):
        cause = "the proxy refused the connection"
    elif isinstance(error, httpx.TimeoutException):
        cause = "the connection timed out (a proxy is probably required)"
    elif isinstance(error, httpx.ConnectError):
        cause = "the connection failed (blocked, or a proxy is required)"
    else:
        cause = "the request failed"
    return (f"Wizard could not reach {host}: {cause}. Route: {describe(url, override)}. If your network needs a "
            f"different proxy, set WIZARD_PROXY=http://host:port in .env and restart. ({text[:200]})")

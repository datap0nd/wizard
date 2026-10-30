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


def _pick(proxies: str | None, url: str) -> str | None:
    """The proxy for this address from a Windows proxy list: "host:port; other:port", or per scheme
    "http=host:port;https=host:port" (the https one for an https address, else http, else the first)."""
    entries = [e.strip() for e in (proxies or "").replace(" ", ";").split(";") if e.strip()]
    scheme = urlsplit(url).scheme or "https"
    by_scheme = {e.split("=", 1)[0].lower(): e.split("=", 1)[1] for e in entries if "=" in e}
    plain = [e for e in entries if "=" not in e]
    chosen = by_scheme.get(scheme) or by_scheme.get("http") or (plain[0] if plain else None)
    return _normalize(chosen) if chosen else None


def _windows_bypassed(host: str, bypass: str | None) -> bool:
    """A fixed Windows proxy's bypass list ("*.corp.example;10.*;<local>"): <local> is any name without a dot."""
    import fnmatch
    for entry in (e.strip().lower() for e in (bypass or "").replace(" ", ";").split(";")):
        if entry == "<local>" and "." not in host:
            return True
        if entry and entry != "<local>" and fnmatch.fnmatch(host.lower(), entry.removeprefix("http://").removeprefix("https://")):
            return True
    return False


def _winhttp_proxy(url: str) -> str | None:
    """Windows' proxy for this address, resolved in this process by WinHTTP from the person's Internet settings, as Edge
    and other Windows apps resolve it: a PAC script or automatic detection, else a fixed proxy and its bypass list. No
    PowerShell (owner, 30 Oct 2026: Defender reported Wizard's hidden PowerShell as malware). None: direct."""
    import ctypes
    from ctypes import wintypes

    winhttp = ctypes.WinDLL("winhttp", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    class IEConfig(ctypes.Structure):
        _fields_ = [("fAutoDetect", wintypes.BOOL), ("lpszAutoConfigUrl", ctypes.c_void_p),
                    ("lpszProxy", ctypes.c_void_p), ("lpszProxyBypass", ctypes.c_void_p)]

    class AutoProxyOptions(ctypes.Structure):
        _fields_ = [("dwFlags", wintypes.DWORD), ("dwAutoDetectFlags", wintypes.DWORD), ("lpszAutoConfigUrl", wintypes.LPCWSTR),
                    ("lpvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD), ("fAutoLogonIfChallenged", wintypes.BOOL)]

    class ProxyInfo(ctypes.Structure):
        _fields_ = [("dwAccessType", wintypes.DWORD), ("lpszProxy", ctypes.c_void_p), ("lpszProxyBypass", ctypes.c_void_p)]

    winhttp.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(IEConfig)]
    winhttp.WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL
    winhttp.WinHttpOpen.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    winhttp.WinHttpOpen.restype = ctypes.c_void_p
    winhttp.WinHttpGetProxyForUrl.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(AutoProxyOptions),
                                              ctypes.POINTER(ProxyInfo)]
    winhttp.WinHttpGetProxyForUrl.restype = wintypes.BOOL
    winhttp.WinHttpCloseHandle.argtypes = [ctypes.c_void_p]
    winhttp.WinHttpCloseHandle.restype = wintypes.BOOL

    def take(pointer: int | None) -> str | None:  # read a string WinHTTP allocated, then free it
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalFree(pointer)

    config = IEConfig()
    if not winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(config)):
        raise OSError(ctypes.get_last_error(), "WinHttpGetIEProxyConfigForCurrentUser failed")  # type: ignore[attr-defined]
    script, fixed, bypass = take(config.lpszAutoConfigUrl), take(config.lpszProxy), take(config.lpszProxyBypass)
    if script or config.fAutoDetect:
        session = winhttp.WinHttpOpen("Wizard", 1, None, None, 0)  # WINHTTP_ACCESS_TYPE_NO_PROXY
        if not session:
            raise OSError(ctypes.get_last_error(), "WinHttpOpen failed")  # type: ignore[attr-defined]
        try:
            # The PAC script first, then automatic detection (DHCP, DNS), as Windows tries them.
            for flags, detect, address in ((0x2, 0, script), (0x1, 0x3, None)):
                if (flags == 0x2 and not script) or (flags == 0x1 and not config.fAutoDetect):
                    continue
                options = AutoProxyOptions(dwFlags=flags, dwAutoDetectFlags=detect, lpszAutoConfigUrl=address,
                                           fAutoLogonIfChallenged=True)
                info = ProxyInfo()
                if winhttp.WinHttpGetProxyForUrl(session, url, ctypes.byref(options), ctypes.byref(info)):
                    proxies, _ = take(info.lpszProxy), take(info.lpszProxyBypass)
                    return _pick(proxies, url) if info.dwAccessType == 3 else None  # 3: a named proxy; else DIRECT
        finally:
            winhttp.WinHttpCloseHandle(session)
    if fixed and not _windows_bypassed(urlsplit(url).hostname or "", bypass):
        return _pick(fixed, url)
    return None


def _windows_system_proxy(url: str) -> str | None:
    host = urlsplit(url).netloc
    if host in _system_proxy_cache:
        return _system_proxy_cache[host]
    try:
        proxy = _winhttp_proxy(url)
    except Exception:  # noqa: BLE001 - WinHTTP missing or refusing: ask .NET, as before, rather than guess
        log.exception("WinHTTP could not resolve the Windows proxy for %s; asking PowerShell", host)
        proxy = _powershell_proxy(url)
    _system_proxy_cache[host] = proxy
    return proxy


def _powershell_proxy(url: str) -> str | None:
    script = ("$ErrorActionPreference='SilentlyContinue';"
              f"$u=[Uri]'{url}';"
              "$p=[System.Net.WebRequest]::GetSystemWebProxy().GetProxy($u);"
              "if ($p -and $p.AbsoluteUri -ne $u.AbsoluteUri) { Write-Output $p.AbsoluteUri }")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return _normalize(lines[-1]) if lines else None
    except (OSError, subprocess.SubprocessError):
        log.exception("could not read the Windows system proxy for %s", urlsplit(url).netloc)
        return None


def windows_route(url: str, override: str | None = None, env: dict[str, str] | None = None,
                  windows: bool | None = None) -> tuple[str | None, str]:
    """(proxy URL or None for direct, where it came from) for a company host, the way Edge and other Windows apps reach
    it: the override (Settings' proxy for that host) if set, NO_PROXY, then the Windows proxy settings for this address
    (a PAC script included), else direct. Never WIZARD_PROXY or the proxy in Gemini CLI's settings: those are for
    Google, and sent the company GitHub's uploads through a web gateway that refuses them from Wizard (owner, 30 Oct
    2026: "It got blocked by macafee web gateway"; Edge commits there). Off Windows (development) the environment's
    HTTPS_PROXY stands in for the Windows settings."""
    env = dict(os.environ) if env is None else env
    if override is not None and override.strip():
        return _normalize(override), "Settings: company GitHub proxy"
    if _bypassed(urlsplit(url).hostname or "", env):
        return None, "NO_PROXY"
    if os.name == "nt" if windows is None else windows:
        proxy = _windows_system_proxy(url)
        return (proxy, "Windows proxy settings") if proxy else (None, "Windows proxy settings: direct")
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if env.get(name):
            return _normalize(env[name]), name
    return None, "direct"


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


def describe(url: str, override: str | None = None, windows: bool = False) -> str:
    """The route a request to `url` takes; `windows`: a company host, routed by windows_route."""
    proxy, source = windows_route(url, override) if windows else proxy_for(url, override)
    if proxy:
        route = f"proxy {proxy} (from {source})"
    elif windows:
        route = f"direct ({source})"
    else:
        route = "direct (WIZARD_PROXY=direct)" if source == "WIZARD_PROXY" else "direct, no proxy configured"
    return f"{route}; certificates: {trust_label()}"


def explain(error: httpx.HTTPError, url: str, override: str | None = None, windows: bool = False) -> str:
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
    where = ("set Settings → Network → Company GitHub proxy (WIZARD_GITHUB_PROXY)" if windows
             else "set WIZARD_PROXY=http://host:port in .env and restart")
    return (f"Wizard could not reach {host}: {cause}. Route: {describe(url, override, windows)}. If your network needs a "
            f"different proxy, {where}. ({text[:200]})")

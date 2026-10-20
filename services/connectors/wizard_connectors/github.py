"""Where the knowledge-base repository's GitHub API is: github.com, or the company's GitHub Enterprise Server.

WIZARD_KB_API names it. Empty means github.com (https://api.github.com). A GitHub Enterprise Server serves its API at
https://<host>/api/v3; the host is company configuration, so it reaches a PC in the provisioning file or .env and is
never written into this public code."""
from __future__ import annotations

from urllib.parse import urlsplit

PUBLIC_API = "https://api.github.com"
EXAMPLE = "https://github.example.com/api/v3"


def api_root(value: str | None) -> str:
    """The REST API root for WIZARD_KB_API. A GitHub Enterprise Server may be given as its host, its address or its
    API address: github.example.com, https://github.example.com and https://github.example.com/api/v3 are the same."""
    text = (value or "").strip().rstrip("/")
    if not text:
        return PUBLIC_API
    parts = urlsplit(text if "://" in text else f"https://{text}")
    path = parts.path.rstrip("/")
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query
            or parts.fragment or path not in ("", "/api/v3")):
        raise ValueError(f"must be the GitHub Enterprise Server API address, for example {EXAMPLE} (empty: github.com)")
    host = parts.netloc.lower()
    if host in ("github.com", "api.github.com"):
        return PUBLIC_API
    return f"https://{host}/api/v3"


def web_root(api: str) -> str:
    """The address people open in a browser for the same server: https://github.com or https://<host>."""
    return "https://github.com" if api == PUBLIC_API else api.removesuffix("/api/v3")

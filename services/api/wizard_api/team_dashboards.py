"""The Dashboards system's link to the company GitHub (owner, 16 Nov 2026: "Our dashboards are all in github enterprise,
I want to map them and then I want wizard to reference them. I am a collaborator on all of them").

One place builds it for the service, `run.py --check` and Settings → Dashboards → Find dashboards: the read-only token,
the repositories (empty: every one the token's account owns or is a collaborator on), and the company GitHub reached
the way the knowledge base reaches it (Settings → Network → Company GitHub proxy, else the route Windows and Edge take).
Wizard's own repositories (the knowledge base, the Pages site, the feedback repository) are never dashboards."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import httpx

from wizard_agent import outbound
from wizard_connectors.dashboards import REQUEST_S, Dashboards
from wizard_connectors.github import API

from .config import Settings


def client_factory(proxy: str | None, transport: httpx.BaseTransport | None = None) -> Callable[[], httpx.Client]:
    def make() -> httpx.Client:
        if transport is not None:
            return httpx.Client(transport=transport, timeout=REQUEST_S, follow_redirects=True)
        route, _ = outbound.windows_route(API, proxy)
        return httpx.Client(timeout=REQUEST_S, verify=outbound.ssl_context(), proxy=route, trust_env=False,
                            follow_redirects=True)
    return make


def build(settings: Settings, data_dir: Path | None, *, token: str | None = None, repos: Iterable[str] | None = None,
          proxy: str | None = None, transport: httpx.BaseTransport | None = None) -> Dashboards | None:
    """The dashboards with these settings (or the ones given, for Find dashboards); None without a token."""
    token = token if token is not None else settings.dashboards_token
    if not token:
        return None
    route = proxy if proxy is not None else settings.github_proxy
    return Dashboards(token, tuple(repos if repos is not None else settings.dashboards_repos), data_dir,
                      settings.dashboards_name, client=client_factory(route, transport),
                      exclude=(settings.kb_repo, settings.site_repo, settings.feedback_repo),
                      explain=lambda error: outbound.explain(error, API, route, windows=True)
                      if isinstance(error, httpx.HTTPError) else str(error))

"""The company's GitHub Enterprise Server, where the knowledge-base repository lives.

Fixed by the owner (20 October 2026): the desktop sync, Settings' Test connection and docs.ps1 kb-publish / kb-check
talk only to this server, never to public github.com, and no setting, provisioning file or .env value changes it. The
app's own updates are different: they come from the public release of this repository on github.com."""
from __future__ import annotations

WEB = "https://github.sec.samsung.net"
API = f"{WEB}/api/v3"


def refused(message: str, headers: dict[str, str] | None, repo: str, write: bool = False) -> str:
    """Why GitHub answered 403, from its own message and headers, and what to do about it. A guess at the cause is
    worse than none (owner, 30 Oct 2026: publishing a map with a classic token was refused, and Wizard named Contents
    read and write and SSO approval, neither of which a classic token on this server has to do with)."""
    text = message.lower()
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    access = "Contents: Read and write" if write else "Contents: Read-only"
    fine_grained = f"a fine-grained token instead: resource owner = the organisation, only {repo}, {access}"
    if "lifetime" in text:
        cause = "the organisation refuses tokens that live this long: make one with a shorter expiry."
    elif "classic" in text:
        cause = f"the organisation does not accept classic personal access tokens. Make {fine_grained}."
    elif "x-github-sso" in headers or "saml" in text:
        cause = ("the token is not authorised for the organisation's single sign-on: on GitHub, Settings → Developer "
                 "settings → the token → Configure SSO → Authorize.")
    elif "rate limit" in text:
        cause = "GitHub's rate limit was reached: try again in a few minutes."
    elif "approv" in text or "pending" in text:
        cause = "the token waits for an organisation owner to approve it."
    elif "x-accepted-github-permissions" in headers or "not accessible by" in text:
        wanted = headers.get("x-accepted-github-permissions")
        cause = (f"the token lacks a permission{f' (GitHub asks for {wanted})' if wanted else ''}: give it {access} on "
                 f"{repo}.")
    else:
        cause = (f"the token, or the organisation's rules for tokens, does not allow this. A classic token needs the repo "
                 f"scope, and some organisations refuse classic tokens: then make {fine_grained}.")
    return cause + (f' GitHub said: "{message}"' if message else "")

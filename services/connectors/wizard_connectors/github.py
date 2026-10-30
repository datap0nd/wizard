"""The company's GitHub Enterprise Server, where the knowledge-base repository lives.

Fixed by the owner (20 October 2026): the desktop sync, Settings' Test connection and docs.ps1 kb-publish / kb-check
talk only to this server, never to public github.com, and no setting, provisioning file or .env value changes it. The
app's own updates are different: they come from the public release of this repository on github.com."""
from __future__ import annotations

WEB = "https://github.sec.samsung.net"
API = f"{WEB}/api/v3"


# Where a fine-grained token's permissions are changed. GitHub preselects "Read-only" when Contents is added, so a write
# token made in a hurry reads the repository and is refused its first write (owner, 30 Oct 2026: "github refused the
# write token HTTP 403 while uploading a file (POST /git/blobs)").
FINE_GRAINED_STEPS = ('On GitHub: Settings → Developer settings → Personal access tokens → Fine-grained tokens → this '
                      'token → Edit → Repository permissions → Contents: "Read and write" (GitHub preselects "Read-only") '
                      '→ Update. The token itself stays the same, so nothing changes in Wizard; if the organisation '
                      'approves tokens, an owner approves the change first.')


def refused(message: str, headers: dict[str, str] | None, repo: str, write: bool = False, write_request: bool = False) -> str:
    """Why GitHub answered 403, from its own message and headers, and what to do about it. A guess at the cause is
    worse than none (owner, 30 Oct 2026: publishing a map with a classic token was refused, and Wizard named Contents
    read and write and SSO approval, neither of which a classic token on this server has to do with). `write_request`:
    the refused request was a write by a token that had just read the repository, so the token reads but may not write."""
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
    elif "archived" in text:
        cause = f"{repo} is archived, so GitHub keeps it read-only: a repository admin can unarchive it."
    elif "x-accepted-github-permissions" in headers or "not accessible by" in text:
        wanted = headers.get("x-accepted-github-permissions")
        cause = (f"the token lacks a permission{f' (GitHub asks for {wanted})' if wanted else ''}: give it {access} on "
                 f"{repo}." + (f" {FINE_GRAINED_STEPS}" if write else ""))
    elif write and write_request:
        cause = (f"the token reads {repo} but may not write to it. A fine-grained token needs {access}. "
                 f"{FINE_GRAINED_STEPS} A classic token needs the whole repo scope.")
    else:
        cause = (f"the token, or the organisation's rules for tokens, does not allow this. A classic token needs the repo "
                 f"scope, and some organisations refuse classic tokens: then make {fine_grained}.")
    return cause + (f' GitHub said: "{message}"' if message else "")

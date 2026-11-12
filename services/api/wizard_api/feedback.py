"""Feedback on the Cases site (owner, 12 November 2026, docs/decisions/2026-11-12-case-feedback-and-quiz.md).

People who open the Cases site rate each answer from 1 to 5 stars, leave a comment, and answer the quiz Gemini prepared
from what the knowledge base is unsure of, without signing in and without a name. The site is static (GitHub Pages), so
its pages send each submission straight to the company GitHub as an issue in a repository of its own (the feedback
repository), with a token published beside the pages: everyone who can open the site can read that token. The owner
accepted that, so Wizard publishes it only when the token can do nothing but open and read issues there:

- a fine-grained token (a classic token reaches every repository its account can, so it is refused);
- the repository is not public, and is neither the knowledge base's nor the site's;
- the token may not change files, in the feedback repository, the knowledge base's or the site's (asked the way
  kb.check_write asks: GitHub refuses a token without that right before it looks at the request);
- it may open issues there: Wizard keeps one issue of its own, the case edits made in the site's admin pane, and
  creates it with the token the first time.

Every issue the site opens is signed by the token's account, so a submission names no one. The admin pane (top right on
the site, behind a PIN) reads those issues back. The PIN only hides the pane: anyone with the token can read the issues."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from wizard_connectors.github import API, WEB, token_kind

FORMAT = 1
EDITS_MARKER = "<!-- wizard:edits -->"
EDITS_TITLE = "Wizard: case edits (the Cases site reads this issue)"
EDITS_BODY = (f"{EDITS_MARKER}\nThe Cases site's admin pane keeps its edits to the cases here (titles, takeaways, notes "
              "from the editors, hidden cases). The site reads this issue: change it from the admin pane, not by hand.\n\n"
              "```json\n{\"format\": 1, \"cases\": {}}\n```\n")
EDITS_PAGES = 5  # the edits issue is among the repository's first: found in its oldest 500 issues
PIN_SALT = "wizard-cases:"


class FeedbackError(Exception):
    """The feedback set-up is not safe or not usable: Wizard does not publish the token."""


@dataclass(frozen=True)
class Ready:
    repo: str
    edits_issue: int
    created: bool  # Wizard opened the edits issue just now


def pin_digest(pin: str) -> str:
    return hashlib.sha256(f"{PIN_SALT}{pin}".encode()).hexdigest()


def site_file(repo: str, token: str, pin: str, edits_issue: int) -> bytes:
    """cases/feedback.json: what the site's pages need to send and read feedback."""
    return (json.dumps({"format": FORMAT, "api": API, "web": WEB, "repo": repo, "token": token, "pin": pin_digest(pin),
                        "edits_issue": edits_issue}, indent=1) + "\n").encode("utf-8")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Wizard-Feedback"}


def _said(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    message = str(body.get("message", ""))[:200] if isinstance(body, dict) else ""
    return f' GitHub said: "{message}"' if message else ""


def _can_write_files(http: httpx.Client, repo: str, headers: dict[str, str]) -> bool:
    """Asks GitHub to create a branch at a commit that does not exist: a token that may change files is told the commit
    does not exist (422) and nothing is created; any other token is refused first (403, or 404 for a repository it
    cannot see)."""
    probe = http.post(f"{API}/repos/{repo}/git/refs", headers=headers,
                      json={"ref": "refs/heads/wizard-feedback-check", "sha": "0" * 40})
    return probe.status_code == 422


def _edits_issue(http: httpx.Client, repo: str, headers: dict[str, str]) -> int | None:
    for page in range(1, EDITS_PAGES + 1):
        response = http.get(f"{API}/repos/{repo}/issues", headers=headers,
                            params={"state": "all", "sort": "created", "direction": "asc", "per_page": 100, "page": page})
        if response.status_code == 410:
            raise FeedbackError(f"Issues are turned off in {repo}: on GitHub, {repo} → Settings → General → Features → "
                                "Issues.")
        if response.status_code != 200:
            raise FeedbackError(f"The feedback token cannot read the issues of {repo} (HTTP {response.status_code}): give "
                                f"it Issues \"Read and write\".{_said(response)}")
        found = response.json() if isinstance(response.json(), list) else []
        for issue in found:
            if (isinstance(issue, dict) and "pull_request" not in issue and issue.get("title") == EDITS_TITLE
                    and EDITS_MARKER in str(issue.get("body") or "")):
                return int(issue["number"])
        if len(found) < 100:
            return None
    return None


def prepare(repo: str, token: str, guarded: list[str], *, client: httpx.Client) -> Ready:
    """Checks the token before it is published with the site (see the module's text) and finds or opens the edits issue.
    `guarded`: the knowledge base's and the site's repositories, which the token must not be able to change."""
    headers = _headers(token)
    with client as http:
        info = http.get(f"{API}/repos/{repo}", headers=headers)
        if info.status_code == 401:
            raise FeedbackError("GitHub refused the feedback token (HTTP 401): it is invalid or expired.")
        if info.status_code == 404:
            raise FeedbackError(f"GitHub says {repo} does not exist for the feedback token (HTTP 404): create the "
                                "repository, and give the token access to it (Repository access → Only select "
                                "repositories).")
        if info.status_code != 200:
            raise FeedbackError(f"GitHub answered HTTP {info.status_code} for {repo}.{_said(info)}")
        classic = token_kind(dict(info.headers))
        if classic:
            raise FeedbackError(f"The feedback token is {classic}. The site publishes this token, and a classic token "
                                "reaches every repository its account can: make a fine-grained token instead, resource "
                                f"owner the organisation, only {repo}, Issues \"Read and write\" and nothing else.")
        repository = info.json() if isinstance(info.json(), dict) else {}
        if not repository.get("private") and repository.get("visibility") != "internal":
            raise FeedbackError(f"{repo} is public: people's comments and answers are company content. Make it private.")
        if repository.get("archived"):
            raise FeedbackError(f"{repo} is archived, so GitHub keeps it read-only: a repository admin can unarchive it.")
        if repository.get("has_issues") is False:
            raise FeedbackError(f"Issues are turned off in {repo}: on GitHub, {repo} → Settings → General → Features → "
                                "Issues.")
        for target in dict.fromkeys([repo, *guarded]):
            if _can_write_files(http, target, headers):
                raise FeedbackError(f"The feedback token can change files in {target}. The site publishes this token, so "
                                    "it must not: edit the token on GitHub (Settings → Developer settings → Personal "
                                    "access tokens → Fine-grained tokens → the token → Edit) and leave it only Issues "
                                    f"\"Read and write\" on {repo}.")
        number = _edits_issue(http, repo, headers)
        if number is not None:
            return Ready(repo, number, False)
        made = http.post(f"{API}/repos/{repo}/issues", headers=headers, json={"title": EDITS_TITLE, "body": EDITS_BODY})
        if made.status_code == 410:
            raise FeedbackError(f"Issues are turned off in {repo}: on GitHub, {repo} → Settings → General → Features → "
                                "Issues.")
        if made.status_code != 201:
            raise FeedbackError(f"The feedback token may not open issues in {repo} (HTTP {made.status_code}): give it "
                                f"Issues \"Read and write\".{_said(made)}")
        return Ready(repo, int(made.json()["number"]), True)


def outcome_text(ready: Ready, guarded: list[str]) -> str:
    others = ", ".join(dict.fromkeys(g for g in guarded if g != ready.repo))
    return (f"The feedback token is fine-grained and can open issues in {ready.repo} but change no files there"
            + (f" or in {others}" if others else "") + "."
            + (" Wizard opened the issue that keeps the admin pane's case edits." if ready.created else ""))


def candidate(settings: Any, values: dict[str, str]) -> tuple[str | None, str | None, str]:
    """(repository, token, PIN) as config.load_settings would read them from these values."""
    token = values.get("WIZARD_FEEDBACK_TOKEN") or None
    repo = (values.get("WIZARD_FEEDBACK_REPO") or "").strip() or None
    site_repo = values.get("WIZARD_SITE_REPO") or values.get("WIZARD_KB_REPO") or settings.site_repo
    if not repo and token and site_repo:
        repo = f"{site_repo.split('/')[0]}/wizard-feedback"
    return repo, token, (values.get("WIZARD_FEEDBACK_PIN") or "2323").strip()

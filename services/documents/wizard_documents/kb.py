"""Publish the company knowledge base to the private GitHub repository the desktop app syncs from (task 50).

Only what Wizard reads is published: content/knowledge/**/*.md and content/contracts/sources/*.json, plus a README the
first time. The inbox (raw documents), digests, registers, quiz logs and stakeholder lists stay on this PC, because
every file in the repository reaches every PC that syncs it.

Work PCs have no git, so this writes one commit through GitHub's API: unchanged files are not uploaded again (their
git blob ids match), notes deleted here are deleted there, and anything else in the repository is left alone. Before
writing it checks that the repository is private, that the token can push, and that the content passes Wizard's own
validation. The publishing token (WIZARD_KB_PUBLISH_TOKEN: Contents read and write) stays in this PC's .env; it is
never the read-only token handed to users."""
from __future__ import annotations

import base64
import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors.content import errors, validate_content

API = "https://api.github.com"
MANAGED = ("knowledge/", "contracts/sources/")
MAX_FILE_BYTES = 2 * 1024 * 1024
README = """# Wizard knowledge base

Private. Wizard's desktop app reads `knowledge/` (company notes) and `contracts/sources/` (report catalogs) from this
repository with a read-only token, and checks every commit with the same rules as `docs.ps1 validate` before using it.

Published from the Wizard documentation kit on the owner's work PC (`.\\docs.ps1 kb-publish`, task 50). Files under
`knowledge/` and `contracts/sources/` are replaced by the next publish, so edit them on the work PC, not here.

Never add credentials, raw documents, exports or personal data: every file here reaches every PC that uses Wizard.
"""


class PublishError(Exception):
    pass


@dataclass
class Outcome:
    lines: list[str] = field(default_factory=list)
    commit: str | None = None
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def collect(content: Path) -> dict[str, bytes]:
    """The files Wizard reads, keyed by their path in the repository."""
    files: dict[str, bytes] = {}
    for folder, pattern in (("knowledge", "*.md"), ("contracts/sources", "*.json")):
        root = content / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob(pattern)):
            relative = path.relative_to(content)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise PublishError(f"{relative.as_posix()} is larger than 2 MB; a note should never be that big")
            files[relative.as_posix()] = path.read_bytes()
    return files


def validate(files: dict[str, bytes]) -> list[str]:
    """Wizard's start-up checks on exactly what would be published."""
    scratch = Path(tempfile.mkdtemp(prefix="wizard-kb-"))
    try:
        for name, data in files.items():
            target = scratch / PurePosixPath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return [str(problem) for problem in errors(validate_content(scratch))]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


class GitHub:
    def __init__(self, repo: str, token: str, client: httpx.Client):
        self.repo, self.client = repo, client
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Publish"}

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, ok: tuple[int, ...] = (200, 201)) -> Any:
        response = self.client.request(method, f"{API}/repos/{self.repo}{path}", headers=self.headers, json=body)
        if response.status_code not in ok:
            raise PublishError(explain(response, self.repo))
        return response.json() if response.content else None


def explain(response: httpx.Response, repo: str) -> str:
    code = response.status_code
    try:
        detail = str(response.json().get("message", ""))[:200]
    except ValueError:
        detail = ""
    if code == 401:
        return "GitHub refused the publishing token (HTTP 401): it is invalid or expired."
    if code == 404:
        return (f"GitHub says {repo} does not exist for this token (HTTP 404): check the name, and that the token's "
                "repository access includes it.")
    if code == 403:
        return f"GitHub refused the request (HTTP 403: {detail}): the token needs Contents read and write, and SSO approval."
    return f"GitHub answered HTTP {code} ({detail})."


def _client(proxy: str | None) -> httpx.Client:
    route, _ = outbound.proxy_for(API, proxy)
    return httpx.Client(timeout=60, verify=outbound.ssl_context(), proxy=route, trust_env=False)


def publish(content: Path, repo: str, token: str, *, branch: str | None = None, message: str | None = None,
            dry_run: bool = False, proxy: str | None = None, client: httpx.Client | None = None) -> Outcome:
    outcome = Outcome()
    files = collect(content)
    if not files:
        raise PublishError(f"Nothing to publish: {content / 'knowledge'} has no notes yet.")
    problems = validate(files)
    if problems:
        raise PublishError(f"{len(problems)} problem(s) in the notes; fix them first (docs.ps1 validate). First: {problems[0]}")
    outcome.lines.append(f"PASS  {len(files)} file(s) pass Wizard's checks")
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http)
        info = gh.call("GET", "")
        if not info.get("private"):
            raise PublishError(f"{repo} is not private. Company notes must never go to a public repository: make it "
                               "private on GitHub (Settings → General → Danger Zone → Change visibility) first.")
        if not (info.get("permissions") or {}).get("push"):  # the account's role: a token can still lack write
            raise PublishError("This account cannot write to the repository: ask an organisation owner for write access.")
        branch = branch or info.get("default_branch") or "main"
        outcome.lines.append(f"PASS  {repo} is private and the token can write; branch {branch}")
        ref = http.get(f"{API}/repos/{repo}/git/ref/heads/{branch}", headers=gh.headers)
        if ref.status_code in (404, 409):  # an empty repository has no branch yet: its first commit is the README
            if dry_run:
                outcome.added = sorted(files) + ["README.md"]
                outcome.lines.append(f"DRY RUN  the repository is empty: {len(outcome.added)} file(s) would be added")
                return outcome
            gh.call("PUT", "/contents/README.md", {"message": "Start the Wizard knowledge base", "branch": branch,
                                                    "content": base64.b64encode(README.encode("utf-8")).decode("ascii")})
            ref = http.get(f"{API}/repos/{repo}/git/ref/heads/{branch}", headers=gh.headers)
        if ref.status_code != 200:
            raise PublishError(explain(ref, repo))
        parent = ref.json()["object"]["sha"]
        base_tree = gh.call("GET", f"/git/commits/{parent}")["tree"]["sha"]
        tree = gh.call("GET", f"/git/trees/{base_tree}?recursive=1")
        existing = {entry["path"]: entry["sha"] for entry in tree.get("tree", []) if entry.get("type") == "blob"}
        if tree.get("truncated"):
            existing = {}
            outcome.lines.append("INFO  the repository is large: every file is uploaded again")
        if "README.md" not in existing:
            files = {**files, "README.md": README.encode("utf-8")}
        entries: list[dict[str, Any]] = []
        for name, data in files.items():
            if existing.get(name) == blob_id(data):
                continue
            (outcome.changed if name in existing else outcome.added).append(name)
            if not dry_run:
                blob = gh.call("POST", "/git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        for name in sorted(existing):
            if name.startswith(MANAGED) and name not in files:
                outcome.removed.append(name)
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": None})
        summary = f"{len(outcome.added)} added, {len(outcome.changed)} changed, {len(outcome.removed)} removed"
        if not (outcome.added or outcome.changed or outcome.removed):
            outcome.lines.append("PASS  nothing changed: the repository already matches content\\")
            return outcome
        if dry_run:
            outcome.lines.append(f"DRY RUN  would publish {summary}")
            return outcome
        new_tree = gh.call("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
        commit = gh.call("POST", "/git/commits", {"message": message or f"Publish the knowledge base ({summary})",
                                                   "tree": new_tree["sha"], "parents": [parent]})
        gh.call("PATCH", f"/git/refs/heads/{branch}", {"sha": commit["sha"], "force": False})
        outcome.commit = commit["sha"]
        outcome.lines.append(f"PASS  published {summary}: https://github.com/{repo}/commit/{commit['sha']}")
    return outcome


def check_read(repo: str, token: str, ref: str = "main", *, proxy: str | None = None,
               client: httpx.Client | None = None) -> tuple[bool, str]:
    """Can the read-only token (the one users get) read the repository? The same request the desktop app makes."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.sha",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Sync"}
    with client or _client(proxy) as http:
        response = http.get(f"{API}/repos/{repo}/commits/{ref}", headers=headers)
        if response.status_code != 200:
            return False, explain(response, repo).replace("publishing token", "read-only token")
        commit = response.text.strip()
    # GitHub cannot be asked whether a fine-grained token may write without writing, so the person checks the
    # token's settings page: Contents read-only, this repository only.
    return True, f"The read-only token reads {repo}: {ref} is at commit {commit[:12]}."

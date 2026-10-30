"""Publish the company knowledge base to the private GitHub repository the desktop app syncs from (task 50).

Only what Wizard reads is published: content/knowledge/**/*.md and content/contracts/sources/*.json, plus a README the
first time. The inbox (raw documents), digests, registers, quiz logs and stakeholder lists stay on this PC, because
every file in the repository reaches every PC that syncs it.

Work PCs have no git, so this writes one commit through the API of the company's GitHub Enterprise Server (fixed:
wizard_connectors.github): unchanged files are not uploaded again (their git blob ids match), notes deleted here
are deleted there, and anything else in the repository is left alone. Before writing it checks that the repository is
private, that the token can push, and that the content passes Wizard's own validation. The publishing token
(WIZARD_KB_PUBLISH_TOKEN: Contents read and write) stays in this PC's .env; it is never the read-only token handed to
users."""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from wizard_agent import outbound
from wizard_connectors.content import errors, validate_content
from wizard_connectors.github import API, WEB, refused

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


ARCHIVED = "{repo} is archived, so GitHub keeps it read-only: a repository admin can unarchive it (Settings → General)."


class GitHub:
    def __init__(self, repo: str, token: str, client: httpx.Client, label: str = "publishing token"):
        self.repo, self.client, self.label = repo, client, label
        self.visibility: str | None = None  # private, internal or public, once the repository was read
        self.route: str | None = None       # how the requests travel, for a refusal that did not come from GitHub
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Publish"}

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, ok: tuple[int, ...] = (200, 201)) -> Any:
        response = self.client.request(method, f"{API}/repos/{self.repo}{path}", headers=self.headers, json=body)
        if response.status_code not in ok:
            raise PublishError(explain(response, self.repo, self.label, self.visibility, self.route))
        found = response.json() if response.content else None
        if method == "GET" and path == "" and isinstance(found, dict):
            self.visibility = found.get("visibility") or ("private" if found.get("private") else "public")
        return found


# What Wizard was doing, by the request GitHub refused: (method, path under /repos/{repo}, words). First match wins.
STEPS = (("GET", "/git/ref/", "reading the branch"), ("GET", "/git/commits/", "reading the latest commit"),
         ("GET", "/git/trees/", "reading the repository's files"), ("GET", "/contents/", "reading a file"),
         ("PUT", "/contents/", "creating the README"), ("POST", "/git/blobs", "uploading a file"),
         ("POST", "/git/trees", "preparing the commit"), ("POST", "/git/commits", "creating the commit"),
         ("POST", "/git/refs", "checking that the token can write"),
         ("PATCH", "/git/refs/", "moving the branch to the new commit"), ("GET", "", "reading the repository"))


def _step(response: httpx.Response, repo: str) -> str:
    try:
        request = response.request
    except RuntimeError:  # a response built by hand
        return ""
    path = request.url.path.split(f"/repos/{repo}", 1)[-1]
    words = next((w for method, prefix, w in STEPS if request.method == method and path.startswith(prefix)), None)
    return f" while {words} ({request.method} {path or '/'})" if words else ""


def explain(response: httpx.Response, repo: str, label: str = "publishing token", visibility: str | None = None,
            route: str | None = None) -> str:
    code = response.status_code
    try:
        body = response.json()
        detail = str(body.get("message", ""))[:200] if isinstance(body, dict) else ""
    except ValueError:
        detail = ""
    step = _step(response, repo)
    if code == 401:
        return f"GitHub refused the {label} (HTTP 401){step}: it is invalid or expired."
    if code == 404:
        return (f"GitHub says {repo} does not exist for this token (HTTP 404){step}: check the name, and that the token's "
                "repository access includes it.")
    if code == 403:
        try:
            writing = response.request.method in ("POST", "PUT", "PATCH", "DELETE")
        except RuntimeError:  # a response built by hand
            writing = False
        if "x-github-request-id" not in response.headers:
            # Every answer from GitHub's API carries X-GitHub-Request-Id: without it, something on the way refused.
            server = response.headers.get("server", "")
            title = re.search(r"<title>([^<]{1,120})</title>", response.text, re.IGNORECASE) if response.content else None
            said = "; ".join(x for x in (f"server {server}" if server else "", f'page "{title.group(1).strip()}"' if title else "") if x)
            return (f"Wizard's request was refused (HTTP 403){step}, but not by GitHub: GitHub's answers carry an "
                    f"X-GitHub-Request-Id, and this one has none{f' ({said})' if said else ''}"
                    f"{f'; the request went by {route}' if route else ''}. Something between this PC "
                    f"and {WEB} refused it, such as the proxy or a security gateway that blocks uploads; the token is "
                    f"not the cause. Wizard takes the route Windows and Edge take (Settings → Network → Company GitHub "
                    f"proxy changes it); Edge signs in to a web gateway as you and Wizard cannot, so if Edge gets through "
                    f"on this route, ask IT to let this PC send {response.request.method if writing else 'requests'} to "
                    f"{WEB}/api/v3.")
        return f"GitHub refused the {label} (HTTP 403){step}: " + refused(detail, dict(response.headers), repo,
                                                                         write=label != "read-only token", write_request=writing,
                                                                         visibility=visibility)
    if code == 409 and "empty" in detail.lower():
        return f"{repo} is empty: nothing has been published to it yet. Run .\\docs.ps1 kb-publish first."
    if code in (409, 422) and ("protected" in detail.lower() or "rule" in detail.lower()):
        return (f"GitHub refused the commit (HTTP {code}){step}: the branch is protected, and Wizard commits straight to "
                f'it. A repository admin can allow this account to push to it. GitHub said: "{detail}"')
    return f"GitHub answered HTTP {code}{step}" + (f' ("{detail}").' if detail else ".")


def _client(proxy: str | None) -> httpx.Client:
    """The company GitHub, reached the way Windows and Edge reach it (outbound.windows_route): `proxy` is Settings'
    company GitHub proxy, never the one for Google."""
    route, _ = outbound.windows_route(API, proxy)
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
        gh.route = outbound.describe(API, proxy, windows=True)
        info = gh.call("GET", "")
        if not info.get("private"):
            raise PublishError(f"{repo} is not private. Company notes must never go to a public repository: make it "
                               "private on GitHub (Settings → General → Danger Zone → Change visibility) first.")
        if info.get("archived"):
            raise PublishError(ARCHIVED.format(repo=repo))
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
        outcome.lines.append(f"PASS  published {summary}: {WEB}/{repo}/commit/{commit['sha']}")
    return outcome


def check_write(repo: str, token: str, *, proxy: str | None = None, client: httpx.Client | None = None) -> tuple[bool, str]:
    """Can this token write to the repository (the settings pane's write token)? Writes nothing. The account's role is
    not enough (owner, 30 Oct 2026: Test connection passed, then publishing a map was refused), so it also asks GitHub
    to create a branch at a commit that does not exist: GitHub checks the token's rights first and refuses a token
    that may not write (403); one that may is told the commit does not exist (422), and nothing is created."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        try:
            info = gh.call("GET", "")
        except PublishError as error:
            return False, f"Write token: {error}"
        if not info.get("private"):
            return False, f"Write token: {repo} is not private; Wizard writes only to a private repository."
        if info.get("archived"):
            return False, f"Write token: {ARCHIVED.format(repo=repo)}"
        if not (info.get("permissions") or {}).get("push"):
            return False, "Write token: this account cannot write to the repository; ask an organisation owner for write access."
        probe = http.post(f"{API}/repos/{repo}/git/refs", headers=gh.headers,
                          json={"ref": "refs/heads/wizard-write-check", "sha": "0" * 40})
    if probe.status_code == 422:
        return True, "The write token can write to it."
    return False, f"Write token: {explain(probe, repo, 'write token', gh.visibility, gh.route)}"


def write_files(repo: str, token: str, files: dict[str, bytes], *, branch: str, message: str,
                proxy: str | None = None, client: httpx.Client | None = None) -> str | None:
    """Commit these files in one commit, leaving every other file in the repository alone (Wizard's own files, such as
    its portal maps). Returns the commit, or None when the repository already has them. Refuses a public repository."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        info = gh.call("GET", "")
        if not info.get("private"):
            raise PublishError(f"{repo} is not private: Wizard never writes company notes to a public repository.")
        if info.get("archived"):
            raise PublishError(ARCHIVED.format(repo=repo))
        if not (info.get("permissions") or {}).get("push"):
            raise PublishError(f"This account cannot write to {repo}: ask an organisation owner for write access.")
        for attempt in range(2):  # another commit may land in between: start again from the new head once
            ref = http.get(f"{API}/repos/{repo}/git/ref/heads/{branch}", headers=gh.headers)
            if ref.status_code != 200:
                raise PublishError(explain(ref, repo, gh.label, gh.visibility, gh.route))
            parent = ref.json()["object"]["sha"]
            base_tree = gh.call("GET", f"/git/commits/{parent}")["tree"]["sha"]
            entries: list[dict[str, Any]] = []
            for name, data in files.items():
                current = http.get(f"{API}/repos/{repo}/contents/{quote(name, safe='/')}", params={"ref": parent},
                                   headers=gh.headers)
                if current.status_code == 200 and isinstance(current.json(), dict) and current.json().get("sha") == blob_id(data):
                    continue
                blob = gh.call("POST", "/git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            if not entries:
                return None
            tree = gh.call("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
            commit = gh.call("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})
            moved = http.patch(f"{API}/repos/{repo}/git/refs/heads/{branch}", headers=gh.headers,
                               json={"sha": commit["sha"], "force": False})
            if moved.status_code == 200:
                return str(commit["sha"])
            if moved.status_code != 422 or attempt:
                raise PublishError(explain(moved, repo, gh.label, gh.visibility, gh.route))
    return None


# Builds a commit's files from the branch as it stands: (paths on the branch, read one of them) -> files by path, where
# None removes that path. Called again from the new head when another commit landed in between.
Make = Callable[[set[str], Callable[[str], bytes | None]], dict[str, bytes | None]]


def update_branch(repo: str, token: str, branch: str, make: Make, *, message: str, proxy: str | None = None,
                  client: httpx.Client | None = None) -> str | None:
    """One commit on `branch` with what `make` returns, every other file left alone; a branch that does not exist yet
    starts with that commit alone (an orphan: the Pages site's branch shares no history with the notes). Returns the
    commit, or None when nothing changed. Refuses a public repository, like every write Wizard makes."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        info = gh.call("GET", "")
        if not info.get("private"):
            raise PublishError(f"{repo} is not private: Wizard never writes company content to a public repository.")
        if info.get("archived"):
            raise PublishError(ARCHIVED.format(repo=repo))
        if not (info.get("permissions") or {}).get("push"):
            raise PublishError(f"This account cannot write to {repo}: ask an organisation owner for write access.")
        for attempt in range(3):  # another commit may land in between: build again from the new head
            ref = http.get(f"{API}/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}", headers=gh.headers)
            parent: str | None = None
            existing: dict[str, str] = {}
            base_tree: str | None = None
            if ref.status_code == 200:
                parent = ref.json()["object"]["sha"]
                base_tree = gh.call("GET", f"/git/commits/{parent}")["tree"]["sha"]
                tree = gh.call("GET", f"/git/trees/{base_tree}?recursive=1")
                if tree.get("truncated"):
                    raise PublishError(f"The {branch} branch of {repo} has too many files for Wizard to update.")
                existing = {e["path"]: e["sha"] for e in tree.get("tree", []) if e.get("type") == "blob"}
            elif ref.status_code != 404:
                raise PublishError(explain(ref, repo, gh.label, gh.visibility, gh.route))

            def read(path: str, existing: dict[str, str] = existing) -> bytes | None:
                if path not in existing:
                    return None
                blob = gh.call("GET", f"/git/blobs/{existing[path]}")
                return base64.b64decode(blob.get("content") or "")

            files = make(set(existing), read)
            entries: list[dict[str, Any]] = []
            for name, data in sorted(files.items()):
                if data is None:
                    if name in existing:
                        entries.append({"path": name, "mode": "100644", "type": "blob", "sha": None})
                    continue
                if len(data) > MAX_FILE_BYTES * 4:
                    raise PublishError(f"{name} is larger than {MAX_FILE_BYTES * 4 // (1024 * 1024)} MB.")
                if existing.get(name) == blob_id(data):
                    continue
                blob = gh.call("POST", "/git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            if not entries:
                return None
            if parent is None:
                tree = gh.call("POST", "/git/trees", {"tree": [e for e in entries if e["sha"]]})
                commit = gh.call("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": []})
                made = http.post(f"{API}/repos/{repo}/git/refs", headers=gh.headers,
                                 json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
                if made.status_code == 201:
                    return str(commit["sha"])
                moved = made
            else:
                tree = gh.call("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
                commit = gh.call("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})
                moved = http.patch(f"{API}/repos/{repo}/git/refs/heads/{quote(branch, safe='/')}", headers=gh.headers,
                                   json={"sha": commit["sha"], "force": False})
                if moved.status_code == 200:
                    return str(commit["sha"])
            if moved.status_code != 422 or attempt == 2:
                raise PublishError(explain(moved, repo, gh.label, gh.visibility, gh.route))
    return None


def pages_url(repo: str, token: str, *, proxy: str | None = None, client: httpx.Client | None = None) -> str | None:
    """The address of the repository's GitHub Pages site, when Pages is on and the token may read its settings (a
    Contents-only token may not: then None, and the person enters the address in Settings)."""
    with client or _client(proxy) as http:
        response = http.get(f"{API}/repos/{repo}/pages", headers={"Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                            "User-Agent": "Wizard-Knowledge-Publish"})
    if response.status_code != 200:
        return None
    found = response.json().get("html_url") if isinstance(response.json(), dict) else None
    return str(found) if isinstance(found, str) and found.startswith("https://") else None


def check_read(repo: str, token: str, ref: str = "main", *, proxy: str | None = None,
               client: httpx.Client | None = None) -> tuple[bool, str]:
    """Can the read-only token (the one users get) read the repository? The same request the desktop app makes."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.sha",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Sync"}
    with client or _client(proxy) as http:
        response = http.get(f"{API}/repos/{repo}/commits/{ref}", headers=headers)
        if response.status_code != 200:
            return False, explain(response, repo, "read-only token")
        commit = response.text.strip()
    # That it cannot write is the person's check, on the token's settings page: Contents read-only, this repository only.
    return True, f"The read-only token reads {repo}: {ref} is at commit {commit[:12]}."

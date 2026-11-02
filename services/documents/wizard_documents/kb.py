"""Wizard's writes to the company's knowledge-base repository: the notes a task saves and the portal maps
(write_files), the Pages site's branch (update_branch), and the write token's own check (check_write).

The repository is the master copy of the notes (owner, 2 November 2026); only a task run writes them. Work PCs have no
git, so each write is one commit built through the API of the company's GitHub Enterprise Server (fixed:
wizard_connectors.github), moved onto the branch as a fast-forward only: a commit that landed in between is never
overwritten. Every write refuses a public or archived repository and an account without write access. GitHub's Git
data API needs a first commit to build on, so an empty repository gets one, a README, from Wizard's first write or from
Test connection with the write token (start)."""
from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from wizard_agent import outbound
from wizard_connectors.github import API, WEB, refused

MAX_FILE_BYTES = 2 * 1024 * 1024
README = """# Wizard knowledge base

Private. Wizard's desktop app reads `knowledge/` (company notes) and `contracts/sources/` (report catalogs) from this
repository with a read-only token, and checks every commit with Wizard's content rules before using it.

This repository is the master copy of the notes. Wizard's tasks (Settings → Tasks) save them here, one checked commit
per save, and Wizard keeps its portal maps in `portal-maps/`. A note changed here directly reaches every PC at its next
sync.

Never add credentials, raw documents, exports or personal data: every file here reaches every PC that uses Wizard.
"""


class PublishError(Exception):
    pass


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


ARCHIVED ="{repo} is archived, so GitHub keeps it read-only: a repository admin can unarchive it (Settings → General)."


class GitHub:
    def __init__(self, repo: str, token: str, client: httpx.Client, label: str = "write token"):
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


def explain(response: httpx.Response, repo: str, label: str = "write token", visibility: str | None = None,
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
        return (f"{repo} is empty: nothing has been saved to it yet. Test connection in Settings → Knowledge base, with "
                "the write token, gives it its first commit.")
    if code in (409, 422) and ("protected" in detail.lower() or "rule" in detail.lower()):
        return (f"GitHub refused the commit (HTTP {code}){step}: the branch is protected, and Wizard commits straight to "
                f'it. A repository admin can allow this account to push to it. GitHub said: "{detail}"')
    return f"GitHub answered HTTP {code}{step}" + (f' ("{detail}").' if detail else ".")


def _client(proxy: str | None) -> httpx.Client:
    """The company GitHub, reached the way Windows and Edge reach it (outbound.windows_route): `proxy` is Settings'
    company GitHub proxy, never the one for Google."""
    route, _ = outbound.windows_route(API, proxy)
    return httpx.Client(timeout=60, verify=outbound.ssl_context(), proxy=route, trust_env=False)


def _writable(gh: GitHub) -> dict[str, Any]:
    """The repository, read with the write token. Refuses a public or archived one, and an account that cannot push
    (the account's role: a token can still lack write, which GitHub says at the first write)."""
    info = gh.call("GET", "")
    if not info.get("private"):
        raise PublishError(f"{gh.repo} is not private: Wizard never writes company content to a public repository.")
    if info.get("archived"):
        raise PublishError(ARCHIVED.format(repo=gh.repo))
    if not (info.get("permissions") or {}).get("push"):
        raise PublishError(f"This account cannot write to {gh.repo}: ask an organisation owner for write access.")
    return dict(info)


def _empty(response: httpx.Response) -> bool:
    """GitHub's answer for a repository without a commit: its Git data API answers 409 "Git Repository is empty"."""
    if response.status_code != 409:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "empty" in str(body.get("message", "")).lower()


def _first_commit(gh: GitHub) -> None:
    """An empty repository's first commit, the README, on its default branch: the contents API works on an empty
    repository, the Git data API every other write uses does not."""
    gh.call("PUT", "/contents/README.md", {"message": "Start the Wizard knowledge base",
                                           "content": base64.b64encode(README.encode("utf-8")).decode("ascii")})


def _ref(gh: GitHub, branch: str) -> httpx.Response:
    """The branch's ref, as GitHub answers it. An empty repository gets its first commit first."""
    url = f"{API}/repos/{gh.repo}/git/ref/heads/{quote(branch, safe='/')}"
    ref = gh.client.get(url, headers=gh.headers)
    if _empty(ref):
        _first_commit(gh)
        ref = gh.client.get(url, headers=gh.headers)
    return ref


def start(repo: str, token: str, *, proxy: str | None = None, client: httpx.Client | None = None) -> bool:
    """Settings' Test connection with the write token: give an empty repository its first commit (the README), so the
    read-only token reads it and every PC syncs it. True when it did; False when the repository already has commits."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        info = _writable(gh)
        branch = str(info.get("default_branch") or "main")
        ref = http.get(f"{API}/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}", headers=gh.headers)
        if not _empty(ref):
            return False
        _first_commit(gh)
        return True


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
    """Commit these files in one commit, leaving every other file in the repository alone (the notes a task saves, a
    portal map). Returns the commit, or None when the repository already has them. Refuses a public repository; an
    empty one gets its first commit (the README) first."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        _writable(gh)
        for attempt in range(2):  # another commit may land in between: start again from the new head once
            ref = _ref(gh, branch)
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
            moved = http.patch(f"{API}/repos/{repo}/git/refs/heads/{quote(branch, safe='/')}", headers=gh.headers,
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
    commit, or None when nothing changed. Refuses a public repository, like every write Wizard makes; an empty one gets
    its first commit (the README, on its default branch) first."""
    with client or _client(proxy) as http:
        gh = GitHub(repo, token, http, "write token")
        gh.route = outbound.describe(API, proxy, windows=True)
        _writable(gh)
        for attempt in range(3):  # another commit may land in between: build again from the new head
            ref = _ref(gh, branch)
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


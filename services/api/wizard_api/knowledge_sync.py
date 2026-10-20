"""The knowledge base, synced from a private GitHub repository the owner maintains.

Users never get the repository: each PC holds a read-only token (from the provisioning file) that lets Wizard download
the content. The repository is on github.com or, with WIZARD_KB_API, on the company's GitHub Enterprise Server. A sync
asks GitHub for the commit at WIZARD_KB_REF (a conditional request, so an unchanged repository costs no rate limit),
downloads that commit's archive only when it changed, unpacks the WIZARD_KB_PATH folder into
data/knowledge/snapshots/<commit>, and validates it with the same checks as WIZARD_CONTENT_DIR. Only a valid snapshot
becomes active; the previous one is kept. With no network the last good snapshot stays in use.

The running service keeps the content it started with. A newer snapshot applies on the next start; in the desktop app
the service restarts itself when idle (see app.py)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from wizard_agent import outbound
from wizard_connectors.content import errors, validate_content
from wizard_connectors.github import PUBLIC_API

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 500 * 1024 * 1024
MAX_FILES = 20_000
COMMIT = re.compile(r"^[0-9a-f]{40}$")
log = logging.getLogger("wizard.knowledge_sync")
_lock = threading.Lock()


@dataclass(frozen=True)
class Source:
    repo: str
    ref: str
    path: str
    token: str | None
    api: str = PUBLIC_API  # the REST API root: https://api.github.com or https://<enterprise host>/api/v3


@dataclass(frozen=True)
class Result:
    outcome: str  # updated | current | invalid | failed | not_configured
    message: str
    commit: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("updated", "current")


def folder(data_dir: Path) -> Path:
    return data_dir / "knowledge"


def read_state(data_dir: Path) -> dict[str, Any]:
    try:
        state = json.loads((folder(data_dir) / "state.json").read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(data_dir: Path, state: dict[str, Any]) -> None:
    target = folder(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    pending = target / f"state.{uuid.uuid4().hex}.tmp"
    pending.write_text(json.dumps(state, indent=2), encoding="utf-8")
    pending.replace(target / "state.json")


def _snapshot(data_dir: Path, name: object) -> Path | None:
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{12}", name):
        return None
    path = folder(data_dir) / "snapshots" / name
    return path if path.is_dir() else None


def _same(state: dict[str, Any], source: Source, ref: bool = True) -> bool:
    """The state describes this repository (on this GitHub server), folder and, with `ref`, branch."""
    return (state.get("api", PUBLIC_API) == source.api and state.get("repo") == source.repo
            and state.get("path", "") == source.path and (not ref or state.get("ref") == source.ref))


def active_content(data_dir: Path, source: Source | None = None) -> Path | None:
    """The validated snapshot to load, or None. With `source`, a snapshot of another repository or folder is ignored."""
    state = read_state(data_dir)
    if source and not _same(state, source, ref=False):
        return None
    return _snapshot(data_dir, state.get("active"))


def status(data_dir: Path, source: Source | None, loaded: Path | None) -> dict[str, Any]:
    """For readiness views and the desktop control API. Never includes the token."""
    if source is None:
        return {"configured": False}
    state = read_state(data_dir)
    active = active_content(data_dir, source)
    return {"configured": True, "api": source.api, "repo": source.repo, "ref": source.ref, "path": source.path or None,
            "token": bool(source.token), "commit": state.get("commit") if active else None,
            "synced_at": state.get("synced_at"), "checked_at": state.get("checked_at"), "last_error": state.get("last_error"),
            "loaded": bool(loaded),
            "restart_pending": bool(active and (loaded is None or active.resolve() != loaded.resolve()))}


def _record(data_dir: Path, source: Source, **changes: Any) -> None:
    state = read_state(data_dir)
    if not _same(state, source):
        state = {key: state[key] for key in ("active", "previous", "commit", "synced_at") if key in state}
        state["etag"] = None
    state.update({"api": source.api, "repo": source.repo, "ref": source.ref, "path": source.path, **changes})
    _write_state(data_dir, state)


def _explain(response: httpx.Response, source: Source) -> str:
    code = response.status_code
    if code == 401:
        return "GitHub refused the knowledge-base token (HTTP 401): it is invalid or expired. Ask for a new provisioning file."
    if code == 404:
        return (f"GitHub says {source.repo} or {source.ref} does not exist for this token (HTTP 404): the token must have "
                "Contents: read on that repository.")
    if code == 403:
        return ("GitHub refused the request (HTTP 403): the token awaits the organisation's approval or needs SSO "
                "authorization, or the rate limit was reached.")
    if code == 409:
        return (f"The token works, but {source.repo} is empty: nothing has been published to it yet. Publish the notes "
                "from the work PC first (task 50: .\\docs.ps1 kb-publish).")
    return f"GitHub answered HTTP {code} for the knowledge base."


def _unpack(archive: Path, target: Path, subpath: str) -> int:
    """Unpack the repository archive's `subpath` folder into `target`; returns the file count. Refuses unsafe paths."""
    count, total = 0, 0
    with ZipFile(archive) as bundle:
        members = [m for m in bundle.infolist() if not m.filename.endswith("/")]
        tops = {PurePosixPath(m.filename).parts[0] for m in bundle.infolist() if PurePosixPath(m.filename).parts}
        if len(tops) != 1:
            raise ValueError("unexpected archive layout")
        prefix = PurePosixPath(tops.pop(), *PurePosixPath(subpath.replace("\\", "/")).parts)
        target.mkdir(parents=True)
        root = target.resolve()
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError(f"unsafe path in archive: {member.filename}")
            try:
                relative = path.relative_to(prefix)
            except ValueError:
                continue
            count += 1
            total += member.file_size
            if count > MAX_FILES or total > MAX_UNPACKED_BYTES:
                raise ValueError("the knowledge base is too large to unpack")
            destination = (root / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"unsafe path in archive: {member.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as stream, destination.open("wb") as output:
                shutil.copyfileobj(stream, output)
    if count == 0:
        raise ValueError(f"the repository has no files under {subpath or 'its root'}")
    return count


def _clean(data_dir: Path, keep: set[str]) -> None:
    snapshots = folder(data_dir) / "snapshots"
    if not snapshots.is_dir():
        return
    for entry in snapshots.iterdir():
        if entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)


def check(source: Source, *, proxy: str | None = None, timeout: float = 30.0,
          transport: httpx.BaseTransport | None = None) -> Result:
    """Can this token read the repository at this ref? One request, nothing downloaded or stored."""
    url = f"{source.api}/repos/{source.repo}/commits/{source.ref}"
    headers = {"Authorization": f"Bearer {source.token}", "Accept": "application/vnd.github.sha",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Sync"}
    try:
        if transport is not None:
            http = httpx.Client(transport=transport, timeout=timeout)
        else:
            route, _ = outbound.proxy_for(url, proxy)
            http = httpx.Client(timeout=timeout, verify=outbound.ssl_context(), proxy=route, trust_env=False)
        with http:
            response = http.get(url, headers=headers)
    except httpx.HTTPError as error:
        return Result("failed", outbound.explain(error, url, proxy))
    if response.status_code != 200:
        return Result("failed", _explain(response, source))
    commit = response.text.strip()
    if not COMMIT.match(commit):
        return Result("failed", "GitHub did not return a commit id for the knowledge base.")
    return Result("current", f"The token can read {source.repo}: {source.ref} is at commit {commit[:12]}.", commit)


def sync(source: Source | None, data_dir: Path, *, proxy: str | None = None, timeout: float = 60.0,
         transport: httpx.BaseTransport | None = None) -> Result:
    """Bring the active snapshot up to date with the repository. Safe to call from several threads."""
    if source is None:
        return Result("not_configured", "No knowledge-base repository is configured (WIZARD_KB_REPO).")
    if not source.token:
        return Result("failed", "WIZARD_KB_REPO is set but WIZARD_KB_TOKEN is missing: import the provisioning file again.")
    with _lock:
        return _sync(source, data_dir, proxy, timeout, transport)


def _sync(source: Source, data_dir: Path, proxy: str | None, timeout: float,
          transport: httpx.BaseTransport | None) -> Result:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    state = read_state(data_dir)
    same_source = _same(state, source)
    current = active_content(data_dir, source)
    headers = {"Authorization": f"Bearer {source.token}", "Accept": "application/vnd.github.sha",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Wizard-Knowledge-Sync"}
    if same_source and current and state.get("etag"):
        headers["If-None-Match"] = str(state["etag"])
    url = f"{source.api}/repos/{source.repo}/commits/{source.ref}"
    try:
        if transport is not None:
            http = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
        else:
            route, _ = outbound.proxy_for(url, proxy)
            http = httpx.Client(timeout=timeout, verify=outbound.ssl_context(), proxy=route, trust_env=False,
                                follow_redirects=True)
        with http:
            response = http.get(url, headers=headers)
            if response.status_code == 304 and current:
                _record(data_dir, source, checked_at=now, last_error=None)
                return Result("current", "The knowledge base is up to date.", state.get("commit"))
            if response.status_code != 200:
                message = _explain(response, source)
                _record(data_dir, source, checked_at=now, last_error=message)
                return Result("failed", message)
            commit = response.text.strip()
            if not COMMIT.match(commit):
                message = "GitHub did not return a commit id for the knowledge base."
                _record(data_dir, source, checked_at=now, last_error=message)
                return Result("failed", message)
            etag = response.headers.get("ETag")
            if current and same_source and state.get("commit") == commit:
                _record(data_dir, source, checked_at=now, etag=etag, last_error=None)
                return Result("current", "The knowledge base is up to date.", commit)
            staging = folder(data_dir) / "staging"
            staging.mkdir(parents=True, exist_ok=True)
            archive = staging / f"{commit[:12]}-{uuid.uuid4().hex}.zip"
            try:
                zip_headers = {**headers, "Accept": "application/vnd.github+json"}
                zip_headers.pop("If-None-Match", None)
                with http.stream("GET", f"{source.api}/repos/{source.repo}/zipball/{commit}", headers=zip_headers) as download:
                    if download.status_code != 200:
                        message = _explain(download, source)
                        _record(data_dir, source, checked_at=now, last_error=message)
                        return Result("failed", message)
                    size = 0
                    with archive.open("wb") as output:
                        for chunk in download.iter_bytes():
                            size += len(chunk)
                            if size > MAX_ARCHIVE_BYTES:
                                raise ValueError("the knowledge-base archive is larger than 200 MB")
                            output.write(chunk)
                name = commit[:12]
                unpacked = staging / f"{name}-{uuid.uuid4().hex}"
                files = _unpack(archive, unpacked, source.path)
                problems = validate_content(unpacked)
                for problem in problems:
                    log.warning("knowledge base %s: %s", name, problem)
                if errors(problems):
                    shutil.rmtree(unpacked, ignore_errors=True)
                    message = (f"Knowledge-base commit {name} was not applied: {len(errors(problems))} error(s), first: "
                               f"{errors(problems)[0]}. The previous version stays in use.")
                    _record(data_dir, source, checked_at=now, last_error=message)
                    return Result("invalid", message, commit)
                snapshots = folder(data_dir) / "snapshots"
                snapshots.mkdir(parents=True, exist_ok=True)
                final = snapshots / name
                if final.exists() and final != current:
                    shutil.rmtree(final, ignore_errors=True)
                if not final.exists():
                    unpacked.rename(final)
                else:
                    shutil.rmtree(unpacked, ignore_errors=True)
                previous = state.get("active") if current and state.get("active") != name else state.get("previous")
                _record(data_dir, source, active=name, previous=previous, commit=commit, etag=etag, files=files,
                        synced_at=now, checked_at=now, last_error=None)
                _clean(data_dir, {name, *([previous] if isinstance(previous, str) else [])})
                log.info("knowledge base %s@%s: commit %s active (%d files)", source.repo, source.ref, name, files)
                return Result("updated", f"Knowledge base updated to commit {name} ({files} files).", commit)
            finally:
                archive.unlink(missing_ok=True)
                for leftover in staging.glob("*"):
                    if leftover.is_dir():
                        shutil.rmtree(leftover, ignore_errors=True)
    except (ValueError, BadZipFile, OSError) as error:
        message = f"The knowledge base could not be unpacked: {error}. The previous version stays in use."
    except httpx.HTTPError as error:
        message = outbound.explain(error, url, proxy) + " The previous knowledge-base version stays in use."
    _record(data_dir, source, checked_at=now, last_error=message)
    return Result("failed", message)

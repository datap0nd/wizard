"""Task 50's publisher: content\\knowledge and contracts -> the private knowledge-base repository as one commit through
GitHub's API (work PCs have no git). A fake GitHub keeps a real tree so the tests see what the repository ends up with."""
from __future__ import annotations

import base64
import hashlib
import json
import re

import httpx
import pytest

from wizard_documents import kb
from wizard_documents.cli import main as docs_main

NOTE = """---
id: company-overview
title: Company overview
area: company
type: overview
status: DRAFT_UNSIGNED
owner: Owner
updated: 2026-10-01
tags: [company]
summary: Who we are.
---
## Who we are

We sell phones.
"""
TOKEN = "github_pat_" + "w" * 40


class FakeGitHub:
    def __init__(self, private: bool = True, push: bool = True, empty: bool = True):
        self.private, self.push = private, push
        self.blobs: dict[str, bytes] = {}
        self.commits: dict[str, dict] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.head: str | None = None
        self.writes: list[str] = []
        self.calls: list[str] = []
        self.hosts: set[str] = set()
        if not empty:
            self._commit({"README.md": self._blob(b"# hand-written readme\n"), ".github/CODEOWNERS": self._blob(b"* @owner\n")},
                         "start", None)

    def _blob(self, data: bytes) -> str:
        sha = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
        self.blobs[sha] = data
        return sha

    def _commit(self, files: dict[str, str], message: str, parent: str | None) -> str:
        tree = hashlib.sha1(json.dumps(files, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
        self.trees[tree] = dict(files)
        sha = hashlib.sha1(f"{tree}{message}{parent}".encode(), usedforsecurity=False).hexdigest()
        self.commits[sha] = {"tree": tree, "message": message, "parents": [parent] if parent else []}
        self.head = sha
        return sha

    def files(self) -> dict[str, bytes]:
        return {path: self.blobs[sha] for path, sha in self.trees[self.commits[self.head]["tree"]].items()}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        self.hosts.add(request.url.host)
        path = request.url.path.removeprefix("/api/v3").removeprefix("/repos/acme/kb")
        body = json.loads(request.content) if request.content else None
        self.calls.append(f"{request.method} {path}")
        if request.method != "GET":
            self.writes.append(f"{request.method} {path}")
        if request.method == "GET" and path == "":
            return httpx.Response(200, json={"private": self.private, "default_branch": "main", "permissions": {"push": self.push}})
        if request.method == "GET" and path == "/git/ref/heads/main":
            if self.head is None:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if request.method == "PUT" and path == "/contents/README.md":
            self._commit({"README.md": self._blob(base64.b64decode(body["content"]))}, body["message"], None)
            return httpx.Response(201, json={})
        if request.method == "GET" and (m := re.fullmatch(r"/git/commits/(\w+)", path)):
            return httpx.Response(200, json={"tree": {"sha": self.commits[m.group(1)]["tree"]}})
        if request.method == "GET" and (m := re.fullmatch(r"/git/trees/(\w+)", path)):
            return httpx.Response(200, json={"tree": [{"path": p, "type": "blob", "sha": s} for p, s in self.trees[m.group(1)].items()],
                                             "truncated": False})
        if request.method == "POST" and path == "/git/blobs":
            return httpx.Response(201, json={"sha": self._blob(base64.b64decode(body["content"]))})
        if request.method == "POST" and path == "/git/trees":
            files = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                if entry["sha"] is None:
                    files.pop(entry["path"], None)
                else:
                    files[entry["path"]] = entry["sha"]
            tree = hashlib.sha1(json.dumps(files, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
            self.trees[tree] = files
            return httpx.Response(201, json={"sha": tree})
        if request.method == "POST" and path == "/git/commits":
            sha = hashlib.sha1(f"{body['tree']}{body['message']}".encode(), usedforsecurity=False).hexdigest()
            self.commits[sha] = {"tree": body["tree"], "message": body["message"], "parents": body["parents"]}
            return httpx.Response(201, json={"sha": sha})
        if request.method == "PATCH" and path == "/git/refs/heads/main":
            assert self.commits[body["sha"]]["parents"] == [self.head], "a fast-forward of the current head"
            self.head = body["sha"]
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": "Not Found"})


def content_folder(tmp_path, notes: dict[str, str] | None = None):
    root = tmp_path / "content"
    for name, text in (notes or {"knowledge/company/overview.md": NOTE}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    for private in ("inbox/_text/mail-001.md", "register/stakeholders.csv", "inbox/_digests/d.md"):
        (root / private).parent.mkdir(parents=True, exist_ok=True)
        (root / private).write_text("internal: name@company.example", encoding="utf-8")
    return root


def publish(root, github, **kw):
    return kb.publish(root, "acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(github)), **kw)


def test_first_publish_of_an_empty_repository_sends_only_what_wizard_reads(tmp_path):
    github = FakeGitHub()
    outcome = publish(content_folder(tmp_path), github)
    assert outcome.commit and outcome.added == ["knowledge/company/overview.md"]
    files = github.files()
    assert set(files) == {"README.md", "knowledge/company/overview.md"}, "no inbox, digests or registers"
    assert files["knowledge/company/overview.md"].decode() == NOTE
    assert any("published 1 added" in line for line in outcome.lines)


def test_unchanged_files_are_not_uploaded_and_deletions_follow(tmp_path):
    github = FakeGitHub(empty=False)
    root = content_folder(tmp_path, {"knowledge/company/overview.md": NOTE,
                                     "knowledge/company/history.md": NOTE.replace("company-overview", "company-history")})
    publish(root, github)
    assert set(github.files()) == {"README.md", ".github/CODEOWNERS", "knowledge/company/overview.md",
                                   "knowledge/company/history.md"}
    assert github.files()["README.md"] == b"# hand-written readme\n", "a README edited on GitHub is kept"
    github.writes.clear()
    again = publish(root, github)
    assert again.commit is None and github.writes == [] and "nothing changed" in again.lines[-1]
    (root / "knowledge" / "company" / "history.md").unlink()
    (root / "knowledge" / "company" / "overview.md").write_text(NOTE.replace("phones", "phones and tablets"), encoding="utf-8")
    github.calls.clear()
    third = publish(root, github)
    assert third.changed == ["knowledge/company/overview.md"] and third.removed == ["knowledge/company/history.md"]
    assert github.calls.count("POST /git/blobs") == 1, "only the changed note is uploaded"
    assert set(github.files()) == {"README.md", ".github/CODEOWNERS", "knowledge/company/overview.md"}


def test_publishing_to_the_companys_github_enterprise_server(tmp_path):
    github = FakeGitHub()
    outcome = publish(content_folder(tmp_path), github, api="https://github.example.com/api/v3")
    assert github.hosts == {"github.example.com"}
    assert outcome.lines[-1].endswith(f"https://github.example.com/acme/kb/commit/{outcome.commit}")


def test_dry_run_writes_nothing(tmp_path):
    github = FakeGitHub(empty=False)
    outcome = publish(content_folder(tmp_path), github, dry_run=True)
    assert github.writes == [] and outcome.added == ["knowledge/company/overview.md"]
    assert "DRY RUN" in outcome.lines[-1]


@pytest.mark.parametrize(("github", "notes", "words"), [
    (FakeGitHub(private=False), None, "not private"),
    (FakeGitHub(push=False), None, "cannot write"),
    (FakeGitHub(), {"knowledge/company/overview.md": "no front matter"}, "problem(s) in the notes"),
    (FakeGitHub(), {"knowledge/company/overview.md": NOTE + '\ntoken = "' + "ghp_" + "a" * 36 + '"\n'}, "problem(s)"),
])
def test_refusals_happen_before_any_write(tmp_path, github, notes, words):
    with pytest.raises(kb.PublishError, match=re.escape(words)):
        publish(content_folder(tmp_path, notes), github)
    assert github.writes == []


def test_the_read_check_uses_the_users_token(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="f" * 40)
                                    if request.url.path.endswith("/commits/main") else httpx.Response(404))
    ok, text = kb.check_read("acme/kb", TOKEN, client=httpx.Client(transport=transport))
    assert ok and "ffffffffffff" in text
    refused = httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "Bad credentials"}))
    ok, text = kb.check_read("acme/kb", TOKEN, client=httpx.Client(transport=refused))
    assert not ok and "read-only token" in text
    empty = httpx.MockTransport(lambda request: httpx.Response(409, json={"message": "Git Repository is empty."}))
    ok, text = kb.check_read("acme/kb", TOKEN, client=httpx.Client(transport=empty))
    assert not ok and "is empty" in text and "kb-publish" in text


def test_the_command_reads_repo_and_tokens_from_env_and_never_prints_them(tmp_path, capsys, monkeypatch):
    root = content_folder(tmp_path)
    (tmp_path / ".env").write_text("WIZARD_KB_PUBLISH_REPO=acme/kb\nWIZARD_KB_API=github.example.com\n", encoding="utf-8")
    assert docs_main(["kb-publish", str(root)]) == 2
    assert "WIZARD_KB_PUBLISH_TOKEN" in capsys.readouterr().out
    github = FakeGitHub()
    original = kb.publish
    monkeypatch.setattr(kb, "publish", lambda *a, **k: original(*a, **{**k, "client": httpx.Client(transport=httpx.MockTransport(github))}))
    monkeypatch.setenv("WIZARD_KB_PUBLISH_TOKEN", TOKEN)
    assert docs_main(["kb-publish", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "added    knowledge/company/overview.md" in out and TOKEN not in out and github.writes == []
    assert github.hosts == {"github.example.com"}, "WIZARD_KB_API in .env names the server"
    monkeypatch.setenv("WIZARD_KB_API", "http://github.example.com")
    assert docs_main(["kb-publish", str(root), "--dry-run"]) == 2
    assert "FAIL  WIZARD_KB_API must be" in capsys.readouterr().out

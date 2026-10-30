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
    def __init__(self, private: bool = True, push: bool = True, empty: bool = True,
                 refuse: dict[str, tuple[str, dict[str, str]]] | None = None, protected: tuple[int, str] | None = None,
                 archived: bool = False, visibility: str | None = None, gateway: set[str] | None = None):
        self.private, self.push, self.archived = private, push, archived
        self.visibility = visibility or ("private" if private else "public")
        self.gateway = gateway or set()  # "METHOD path" refused on the way, by a proxy, not by GitHub
        self.refuse = refuse or {}  # "METHOD path": (GitHub's message, headers) answered with 403
        self.protected = protected  # (status, message) for moving main
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
        if f"{request.method} {request.url.path.removeprefix('/api/v3/repos/acme/kb')}" in self.gateway:
            return httpx.Response(403, text="<html><head><title>Access Denied</title></head><body>Upload blocked</body></html>",
                                  headers={"Server": "Proxy-Gateway"})
        response = self.answer(request)
        response.headers["X-GitHub-Request-Id"] = "ABCD:1234:5678"  # every answer from GitHub's API carries one
        return response

    def answer(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        self.hosts.add(request.url.host)
        path = request.url.path.removeprefix("/api/v3/repos/acme/kb")
        body = json.loads(request.content) if request.content else None
        self.calls.append(f"{request.method} {path}")
        if request.method != "GET":
            self.writes.append(f"{request.method} {path}")
        if f"{request.method} {path}" in self.refuse:
            message, headers = self.refuse[f"{request.method} {path}"]
            return httpx.Response(403, json={"message": message}, headers=headers)
        if request.method == "POST" and path == "/git/refs":  # only ever Test connection's probe, which creates nothing
            assert body == {"ref": "refs/heads/wizard-write-check", "sha": "0" * 40}
            return httpx.Response(422, json={"message": "Object does not exist"})
        if request.method == "PATCH" and self.protected:
            return httpx.Response(self.protected[0], json={"message": self.protected[1]})
        if request.method == "GET" and path == "":
            return httpx.Response(200, json={"private": self.private, "default_branch": "main", "permissions": {"push": self.push},
                                             "archived": self.archived, "visibility": self.visibility})
        if request.method == "GET" and path == "/git/ref/heads/main":
            if self.head is None:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if request.method == "PUT" and path == "/contents/README.md":
            self._commit({"README.md": self._blob(base64.b64decode(body["content"]))}, body["message"], None)
            return httpx.Response(201, json={})
        if request.method == "GET" and path.startswith("/contents/"):
            ref = request.url.params.get("ref") or self.head
            found = self.trees[self.commits[ref]["tree"]].get(path.removeprefix("/contents/")) if ref else None
            return httpx.Response(200, json={"sha": found}) if found else httpx.Response(404, json={"message": "Not Found"})
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
    assert github.hosts == {"github.sec.samsung.net"}, "only the company's GitHub Enterprise Server"
    assert outcome.lines[-1].endswith(f"https://github.sec.samsung.net/acme/kb/commit/{outcome.commit}")


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
    (tmp_path / ".env").write_text("WIZARD_KB_PUBLISH_REPO=acme/kb\n", encoding="utf-8")
    assert docs_main(["kb-publish", str(root)]) == 2
    assert "WIZARD_KB_PUBLISH_TOKEN" in capsys.readouterr().out
    github = FakeGitHub()
    original = kb.publish
    monkeypatch.setattr(kb, "publish", lambda *a, **k: original(*a, **{**k, "client": httpx.Client(transport=httpx.MockTransport(github))}))
    monkeypatch.setenv("WIZARD_KB_PUBLISH_TOKEN", TOKEN)
    assert docs_main(["kb-publish", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "added    knowledge/company/overview.md" in out and TOKEN not in out and github.writes == []


def test_wizard_writes_only_its_own_files_in_one_commit_and_skips_unchanged_ones():
    """The settings pane's write token: Wizard commits its portal maps and leaves every other file alone."""
    github = FakeGitHub(empty=False)
    client = httpx.Client(transport=httpx.MockTransport(github))
    files = {"portal-maps/gscm.json": b'{"system": "gscm"}', "portal-maps/gscm.md": b"# GSCM map\n"}
    commit = kb.write_files("acme/kb", TOKEN, files, branch="main", message="Wizard: GSCM map", client=client)
    assert commit and github.head == commit and github.commits[commit]["message"] == "Wizard: GSCM map"
    assert github.files() == {"README.md": b"# hand-written readme\n", ".github/CODEOWNERS": b"* @owner\n", **files}
    writes = list(github.writes)
    again = kb.write_files("acme/kb", TOKEN, files, branch="main", message="again",
                           client=httpx.Client(transport=httpx.MockTransport(github)))
    assert again is None and github.writes == writes, "an unchanged map makes no commit"
    changed = kb.write_files("acme/kb", TOKEN, {**files, "portal-maps/gscm.md": b"# GSCM map v2\n"}, branch="main",
                             message="v2", client=httpx.Client(transport=httpx.MockTransport(github)))
    assert changed and [w for w in github.writes[len(writes):] if w == "POST /git/blobs"] == ["POST /git/blobs"]


def test_wizard_never_writes_to_a_public_repository_or_without_write_access():
    for github, words in ((FakeGitHub(private=False, empty=False), "not private"), (FakeGitHub(push=False, empty=False), "cannot write")):
        with pytest.raises(kb.PublishError, match=words):
            kb.write_files("acme/kb", TOKEN, {"portal-maps/x.json": b"{}"}, branch="main", message="m",
                           client=httpx.Client(transport=httpx.MockTransport(github)))
        assert not github.writes
    github = FakeGitHub(empty=False)
    head = github.head
    ok, message = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(github)))
    assert ok and "can write" in message and github.head == head and github.writes == ["POST /git/refs"]
    ok, message = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(FakeGitHub(push=False))))
    assert not ok and "cannot write" in message


CLASSIC = ("The `acme` organization forbids access via a personal access token (classic). Please use a GitHub App, "
           "OAuth App, or a fine-grained personal access token.")
READ_ONLY = ("Resource not accessible by personal access token", {"X-Accepted-GitHub-Permissions": "contents=write"})


def test_test_connection_asks_github_whether_the_token_itself_can_write():
    """Owner, 30 Oct 2026: Test connection passed on the account's role, then publishing a map was refused (403). The
    token's own right to write is checked too, by a request that cannot create anything."""
    github = FakeGitHub(empty=False, refuse={"POST /git/refs": READ_ONLY})
    ok, message = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(github)))
    assert not ok and message.startswith("Write token: GitHub refused the write token (HTTP 403) while checking that the "
                                         "token can write (POST /git/refs): the token lacks a permission (GitHub asks "
                                         "for contents=write): give it Contents: Read and write on acme/kb.")
    ok, message = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(
        FakeGitHub(empty=False, refuse={"GET ": (CLASSIC, {})}))))
    assert not ok and "does not accept classic personal access tokens" in message and "while reading the repository" in message


@pytest.mark.parametrize(("refuse", "words"), [
    ({"GET ": (CLASSIC, {})},
     ["(HTTP 403) while reading the repository (GET /): the organisation does not accept classic personal access tokens. "
      "Make a fine-grained token instead: resource owner = the organisation, only acme/kb, Contents: Read and write.",
      'GitHub said: "The `acme` organization forbids access via a personal access token (classic).']),
    ({"POST /git/blobs": READ_ONLY},
     ["while uploading a file (POST /git/blobs): the token lacks a permission (GitHub asks for contents=write)",
      'Fine-grained tokens → this token → Edit → Repository permissions → Contents: "Read and write"']),
    # Owner, 30 Oct 2026: "github refused the write token HTTP 403 while uploading a file (POST /git/blobs)". The same token
    # had just read the repository, its branch and its files: it reads but may not write.
    ({"POST /git/blobs": ("Forbidden", {})},
     ["while uploading a file (POST /git/blobs): the token reads acme/kb but may not write to it. A fine-grained token "
      "needs Contents: Read and write.", '(GitHub preselects "Read-only")', "The token itself stays the same",
      "A classic token needs the whole repo scope.", 'GitHub said: "Forbidden"']),
    ({"GET ": ("Resource protected by organization SAML enforcement. You must grant your Personal Access token access "
               "to this organization.", {"X-GitHub-SSO": "required; url=https://github.example/orgs/acme/sso"})},
     ["Configure SSO → Authorize"]),
    ({"GET ": ("API rate limit exceeded for user ID 1.", {})}, ["rate limit was reached"]),
    ({"GET ": ("Forbidden", {})}, ["some organisations refuse classic tokens", 'GitHub said: "Forbidden"']),
])
def test_a_refused_map_says_which_request_github_refused_and_why(refuse, words):
    """GitHub's own message and headers name the cause; Wizard no longer guesses Contents and SSO approval."""
    github = FakeGitHub(empty=False, refuse=refuse)
    head = github.head
    with pytest.raises(kb.PublishError) as refused:
        kb.write_files("acme/kb", TOKEN, {"portal-maps/x.json": b"{}"}, branch="main", message="m",
                       client=httpx.Client(transport=httpx.MockTransport(github)))
    assert str(refused.value).startswith("GitHub refused the write token (HTTP 403) while ")
    for part in words:
        assert part in str(refused.value)
    assert github.head == head
    if "Configure SSO" not in words[0]:
        assert "SSO" not in str(refused.value)


@pytest.mark.parametrize("protected", [(422, "Protected branch update failed for refs/heads/main."),
                                       (409, "Repository rule violations found\n\nChanges must be made through a pull request.")])
def test_a_protected_branch_is_named_not_called_empty(protected):
    github = FakeGitHub(empty=False, protected=protected)
    with pytest.raises(kb.PublishError, match="the branch is protected") as refused:
        kb.write_files("acme/kb", TOKEN, {"portal-maps/x.json": b"{}"}, branch="main", message="m",
                       client=httpx.Client(transport=httpx.MockTransport(github)))
    assert "while moving the branch to the new commit (PATCH /git/refs/heads/main)" in str(refused.value)
    assert "empty" not in str(refused.value)


def test_an_archived_repository_is_named_before_any_write():
    github = FakeGitHub(empty=False, archived=True)
    with pytest.raises(kb.PublishError, match="acme/kb is archived, so GitHub keeps it read-only"):
        kb.write_files("acme/kb", TOKEN, {"portal-maps/x.json": b"{}"}, branch="main", message="m",
                       client=httpx.Client(transport=httpx.MockTransport(github)))
    assert github.writes == []
    ok, message = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(FakeGitHub(empty=False, archived=True))))
    assert not ok and "is archived" in message



def write(github: FakeGitHub) -> str:
    with pytest.raises(kb.PublishError) as refused:
        kb.write_files("acme/kb", TOKEN, {"portal-maps/x.json": b"{}"}, branch="main", message="m",
                       client=httpx.Client(transport=httpx.MockTransport(github)))
    return str(refused.value)


def test_an_internal_repository_proves_nothing_about_the_tokens_access():
    """Owner, 30 Oct 2026: "My token already has all contents read and write." On GitHub Enterprise every account reads an
    internal repository, so a token whose resource owner is the person (or whose repositories leave this one out) reads
    it and is refused its first write."""
    message = write(FakeGitHub(empty=False, visibility="internal", refuse={"POST /git/blobs": READ_ONLY}))
    assert "while uploading a file (POST /git/blobs): the token may not write to acme/kb. acme/kb is internal, so every " \
           "account in the company can read it: that the token reads it does not show the token has access to it." in message
    assert "Resource owner is acme, not your own account" in message and "Repository access includes acme/kb" in message
    assert 'GitHub said: "Resource not accessible by personal access token"' in message
    ok, tested = kb.check_write("acme/kb", TOKEN, client=httpx.Client(transport=httpx.MockTransport(
        FakeGitHub(empty=False, visibility="internal", refuse={"POST /git/refs": READ_ONLY}))))
    assert not ok and "acme/kb is internal" in tested and "Resource owner is acme" in tested, "Test connection says the same"


def test_a_classic_token_is_named_with_its_scopes():
    message = write(FakeGitHub(empty=False, refuse={"POST /git/blobs": ("Forbidden", {"X-OAuth-Scopes": "repo, workflow"})}))
    assert "the token reads acme/kb but may not write to it. It is a classic token (scopes: repo, workflow)" in message
    assert "Fine-grained tokens" not in message


def test_a_refusal_that_did_not_come_from_github_says_so():
    """A proxy or security gateway that blocks uploads answers 403 itself: no X-GitHub-Request-Id, and the token is not
    the cause."""
    github = FakeGitHub(empty=False, gateway={"POST /git/blobs"})
    message = write(github)
    assert message.startswith("Wizard's request was refused (HTTP 403) while uploading a file (POST /git/blobs), but not by "
                              "GitHub: GitHub's answers carry an X-GitHub-Request-Id, and this one has none (server "
                              'Proxy-Gateway; page "Access Denied").')
    assert "the token is not the cause" in message and "send POST to https://github.sec.samsung.net/api/v3" in message
    assert "POST /git/trees" not in github.calls, "nothing after the refused upload"

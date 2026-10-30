"""The Pages site (site.py): Brain and Cases published to a branch of their own with this PC's write token, at the
person's click. A fake GitHub keeps real branches, so the tests see what the site's branch ends up holding and that the
notes' branch is never touched."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.helpers import CEO_QUESTION, HEADERS, ask, login, make_settings

from wizard_api.app import create_app
from wizard_api.site import SiteError, build_case, case_id, page_html
from wizard_documents import kb

TOKEN = "github_pat_" + "s" * 40
REPO = "acme/kb"


class FakeHub:
    """Branches, commits, trees and blobs, answered the way GitHub's REST API does for the calls Wizard makes."""

    def __init__(self, pages_url: str | None = None):
        self.blobs: dict[str, bytes] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.refs: dict[str, str] = {}
        self.writes: list[str] = []
        self.pages_url = pages_url
        self.refs["main"] = self._commit({"README.md": self._blob(b"# notes\n")}, [])

    def _blob(self, data: bytes) -> str:
        sha = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
        self.blobs[sha] = data
        return sha

    def _tree(self, files: dict[str, str]) -> str:
        sha = hashlib.sha1(json.dumps(files, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
        self.trees[sha] = dict(files)
        return sha

    def _commit(self, files: dict[str, str], parents: list[str], message: str = "start") -> str:
        tree = self._tree(files)
        sha = hashlib.sha1(f"{tree}{message}{parents}{len(self.commits)}".encode(), usedforsecurity=False).hexdigest()
        self.commits[sha] = {"tree": tree, "parents": parents, "message": message}
        return sha

    def files(self, branch: str) -> dict[str, bytes]:
        return {p: self.blobs[s] for p, s in self.trees[self.commits[self.refs[branch]]["tree"]].items()}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        path = request.url.path.removeprefix(f"/api/v3/repos/{REPO}")
        body = json.loads(request.content) if request.content else None
        if request.method != "GET":
            self.writes.append(f"{request.method} {path}")
        if request.method == "GET" and path == "":
            return httpx.Response(200, json={"private": True, "visibility": "private", "permissions": {"push": True}})
        if request.method == "GET" and path == "/pages":
            return httpx.Response(200, json={"html_url": self.pages_url}) if self.pages_url else httpx.Response(404, json={})
        if request.method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path.removeprefix("/git/ref/heads/")
            if branch not in self.refs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": self.refs[branch]}})
        if request.method == "GET" and path.startswith("/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": self.commits[path.rsplit("/", 1)[1]]["tree"]}})
        if request.method == "GET" and path.startswith("/git/trees/"):
            tree = self.trees[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"tree": [{"path": p, "type": "blob", "sha": s} for p, s in tree.items()],
                                             "truncated": False})
        if request.method == "GET" and path.startswith("/git/blobs/"):
            data = self.blobs[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if request.method == "POST" and path == "/git/blobs":
            return httpx.Response(201, json={"sha": self._blob(base64.b64decode(body["content"]))})
        if request.method == "POST" and path == "/git/trees":
            files = dict(self.trees[body["base_tree"]]) if body.get("base_tree") else {}
            for entry in body["tree"]:
                if entry["sha"] is None:
                    files.pop(entry["path"], None)
                else:
                    files[entry["path"]] = entry["sha"]
            return httpx.Response(201, json={"sha": self._tree(files)})
        if request.method == "POST" and path == "/git/commits":
            tree = self.trees[body["tree"]]
            return httpx.Response(201, json={"sha": self._commit(tree, body["parents"], body["message"])})
        if request.method == "POST" and path == "/git/refs":
            branch = body["ref"].removeprefix("refs/heads/")
            if branch in self.refs:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.refs[branch] = body["sha"]
            return httpx.Response(201, json={})
        if request.method == "PATCH" and path.startswith("/git/refs/heads/"):
            branch = path.removeprefix("/git/refs/heads/")
            if self.commits[body["sha"]]["parents"] != [self.refs[branch]]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.refs[branch] = body["sha"]
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected {request.method} {path}")


def client_for(hub: FakeHub) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(hub))


def test_a_new_site_branch_starts_alone_and_the_notes_branch_is_never_touched():
    hub = FakeHub()
    main = hub.refs["main"]
    commit = kb.update_branch(REPO, TOKEN, "gh-pages", lambda existing, read: {"a.txt": b"one", "gone.txt": None},
                              message="first", client=client_for(hub))
    assert commit and hub.refs["main"] == main
    assert hub.commits[commit]["parents"] == []  # an orphan: no history shared with the notes
    assert hub.files("gh-pages") == {"a.txt": b"one"}


def test_a_later_commit_reads_the_branch_removes_and_skips_what_is_unchanged():
    hub = FakeHub()
    kb.update_branch(REPO, TOKEN, "gh-pages", lambda e, r: {"a.txt": b"one", "b.txt": b"two"}, message="1", client=client_for(hub))
    seen: dict[str, Any] = {}

    def make(existing: set[str], read: Any) -> dict[str, bytes | None]:
        seen["existing"], seen["a"] = existing, read("a.txt")
        return {"a.txt": b"one", "b.txt": None, "c.txt": b"three"}

    kb.update_branch(REPO, TOKEN, "gh-pages", make, message="2", client=client_for(hub))
    assert seen == {"existing": {"a.txt", "b.txt"}, "a": b"one"}
    assert hub.files("gh-pages") == {"a.txt": b"one", "c.txt": b"three"}
    writes = len(hub.writes)
    assert kb.update_branch(REPO, TOKEN, "gh-pages", lambda e, r: {"a.txt": b"one"}, message="3", client=client_for(hub)) is None
    assert len(hub.writes) == writes  # nothing changed: nothing written


def test_the_page_knows_which_page_it_is_and_finds_the_shared_code_one_level_up():
    html = page_html('<html lang="en" data-page=""><title>Wizard</title><script src="./assets/site.js"></script>'
                     '<link href="./assets/site.css"></html>', "cases").decode()
    assert 'data-page="cases"' in html and '"../assets/site.js"' in html and '"../assets/site.css"' in html
    assert "<title>Cases · Wizard</title>" in html


def test_a_case_never_carries_a_credential():
    turn = {"run_id": "r1", "kind": "ask", "prompt": "q", "asked_at": "2026-10-30T10:00:00Z",
            "answer": "Use password=hunter2-secret-value and token ghp_" + "a" * 36, "data_mode": "SYNTHETIC",
            "check": {"status": "NOT_CHECKED", "summary": None}, "visuals": [], "sources": [], "steps": []}
    with pytest.raises(SiteError, match="Not published"):
        build_case({"id": "cnv_x", "title": "t"}, [turn], "t", "", None)


def owner_app(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, hub: FakeHub, **env: str) -> TestClient:
    monkeypatch.setattr(kb, "_client", lambda proxy: client_for(hub))
    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_KB_WRITE_TOKEN=TOKEN,
                             WIZARD_LOCAL_USER_EMAIL="owner@example.com", **env)
    settings.install_mode = True
    return TestClient(create_app(settings))


def test_share_as_case_publishes_the_answers_and_source_names_never_the_rows(tmp_path, monkeypatch):
    hub = FakeHub(pages_url="https://pages.github.example.com/acme/kb/")
    with owner_app(tmp_path, monkeypatch, hub) as client:
        login(client, "local-owner")
        assert client.get("/api/v1/bootstrap").json()["site"] == {"enabled": True}
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "succeeded"
        conversation = run["conversation_id"]
        preview = client.get(f"/api/v1/conversations/{conversation}/case").json()
        case = preview["case"]
        assert preview["published"] is None and preview["site"]["pages"]["cases"] == "https://pages.github.example.com/acme/kb/cases/"
        assert [t["prompt"] for t in case["turns"]] == [CEO_QUESTION] and case["turns"][0]["run_id"] == run["id"]
        assert case["turns"][0]["sources"] and case["turns"][0]["steps"]
        published = client.post(f"/api/v1/conversations/{conversation}/case", headers=HEADERS,
                                json={"title": "Marketing return by market", "takeaway": "Egypt leads.", "run_ids": []})
        assert published.status_code == 200, published.text
        cid = case_id(conversation)
        assert published.json()["url"] == f"https://pages.github.example.com/acme/kb/cases/?case={cid}"
        assert hub.refs["main"] and "cases/cases.json" not in hub.files("main")
        site = hub.files("gh-pages")
        assert {".nojekyll", "README.md", "cases/index.html", "cases/cases.json", f"cases/{cid}.json"} <= set(site)
        assert "brain/index.html" not in site  # Brain is published on its own, by its own button
        assert any(p.startswith("assets/") and p.endswith(".js") for p in site)
        assert 'data-page="cases"' in site["cases/index.html"].decode()
        index = json.loads(site["cases/cases.json"])
        assert [(e["id"], e["title"], e["takeaway"], e["prompts"]) for e in index["cases"]] == [
            (cid, "Marketing return by market", "Egypt leads.", 1)]
        stored = json.loads(site[f"cases/{cid}.json"])
        source_keys = {k for t in stored["turns"] for s in t["sources"] for k in s}
        assert source_keys <= {"id", "system", "system_name", "report_name", "data_mode", "as_of", "total_rows", "truncated"}
        assert "run_id" not in stored["turns"][0] and stored["turns"][0]["answer"] == run["answer"]
        # Published again: still one case, at the same address, first published when it first was.
        again = client.post(f"/api/v1/conversations/{conversation}/case", headers=HEADERS,
                            json={"title": "Marketing return, Q3", "takeaway": "", "run_ids": [run["id"]]})
        assert again.status_code == 200
        index = json.loads(hub.files("gh-pages")["cases/cases.json"])
        assert [e["title"] for e in index["cases"]] == ["Marketing return, Q3"]
        assert client.get(f"/api/v1/conversations/{conversation}/case").json()["published"]["title"] == "Marketing return, Q3"
        removed = client.delete(f"/api/v1/conversations/{conversation}/case", headers=HEADERS)
        assert removed.status_code == 200 and removed.json()["outcome"] == "removed"
        site = hub.files("gh-pages")
        assert f"cases/{cid}.json" not in site and json.loads(site["cases/cases.json"])["cases"] == []


def test_the_brain_is_published_as_a_snapshot_without_the_notes_text(tmp_path, monkeypatch):
    hub = FakeHub()
    with owner_app(tmp_path, monkeypatch, hub) as client:
        login(client, "local-owner")
        response = client.post("/api/v1/site/brain", headers=HEADERS, json={})
        assert response.status_code == 200, response.text
        assert response.json()["url"] is None  # Pages' address unknown: the person enters it in Settings
        site = hub.files("gh-pages")
        assert 'data-page="brain"' in site["brain/index.html"].decode() and "cases/index.html" not in site
        snapshot = json.loads(site["brain/brain.json"])
        assert snapshot["map"]["notes"] and snapshot["published_at"]
        assert all(set(n) <= {"id", "title", "area", "type", "stage", "summary", "tags", "terms", "words", "updated"}
                   for n in snapshot["map"]["notes"])
        status = client.get("/api/v1/site").json()
        assert status["enabled"] and status["url"] is None and "Settings → Pages" in status["setup"]


def test_only_the_person_at_this_pc_publishes_and_only_with_a_write_token(tmp_path, monkeypatch):
    hub = FakeHub()
    with owner_app(tmp_path, monkeypatch, hub) as client:
        login(client, "u-ceo")  # a fixture identity, not the person at this PC
        assert client.get("/api/v1/bootstrap").json()["site"] == {"enabled": False}
        assert client.post("/api/v1/site/brain", headers=HEADERS, json={}).status_code == 403
    settings = make_settings(tmp_path / "other", WIZARD_SITE_REPO=REPO, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        assert client.get("/api/v1/bootstrap").json()["site"] == {"enabled": False}
        refused = client.post("/api/v1/site/brain", headers=HEADERS, json={})
        assert refused.status_code == 409 and "write token" in refused.json()["error"]
    assert hub.writes == []


def test_the_site_branch_is_never_the_notes_branch(tmp_path):
    from wizard_api.config import ConfigError
    with pytest.raises(ConfigError, match="WIZARD_SITE_BRANCH"):  # the knowledge base's repository, on its own branch
        make_settings(tmp_path, WIZARD_AGENT_RUNTIME="code-assist", WIZARD_KB_REPO=REPO, WIZARD_SITE_BRANCH="main")
    shared = make_settings(tmp_path, WIZARD_AGENT_RUNTIME="code-assist", WIZARD_KB_REPO=REPO)
    assert (shared.site_repo, shared.site_branch) == (REPO, "gh-pages")
    settings = make_settings(tmp_path, WIZARD_SITE_REPO=REPO, WIZARD_SITE_URL="https://pages.github.example.com/acme/kb")
    assert settings.site_url == "https://pages.github.example.com/acme/kb/" and settings.site_branch == "gh-pages"
    with pytest.raises(ConfigError, match="WIZARD_SITE_URL"):
        make_settings(tmp_path, WIZARD_SITE_URL="http://insecure.example.com/")
    assert re.fullmatch(r"c[0-9a-f]{14}", case_id("cnv_abc"))

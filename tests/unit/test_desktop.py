"""Desktop app back end: the provisioning file, the knowledge base synced from a private GitHub repository, desktop
start-up (run.py --desktop) and the control API WizardBar uses."""
from __future__ import annotations

import functools
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS

from wizard_api import desktop, knowledge_sync, provisioning, settings_pane
from wizard_api.app import create_app
from wizard_api.config import ConfigError, kb_source, load_settings

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "github_pat_" + "x" * 40
CONTROL = "c" * 40
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
GUIDE = """---
id: platform-asap
title: ASAP platform guide
status: DRAFT_UNSIGNED
owner: TBD
tags: [asap]
---
**What it is.** The BI portal.
"""


def provision_file(path: Path, **settings: str) -> Path:
    values = {"WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN, "WIZARD_PG_HOST": "db.corp.example",
              "WIZARD_PG_USER": "wizard_ro", "WIZARD_PG_PASSWORD": "s3cret-pass", "WIZARD_PG_DATABASE": "bi",
              "GOOGLE_CLOUD_PROJECT": "corp-gemini", **settings}
    path.write_text(json.dumps({"wizard_provision": 1, "name": "ACME pilot", "settings": values}), encoding="utf-8")
    return path


# Provisioning -----------------------------------------------------------------------------------------------------------
def test_provisioning_is_imported_once_and_secrets_are_kept_apart(tmp_path):
    offered = provision_file(tmp_path / "wizard.provision")
    data = tmp_path / "data"
    provision = provisioning.import_file(offered, data)
    assert not offered.exists(), "the plaintext file is deleted after the import"
    assert set(provision.secrets) == {"WIZARD_KB_TOKEN", "WIZARD_PG_PASSWORD"}
    stored = (data / "provision" / "settings.json").read_text(encoding="utf-8")
    assert "s3cret-pass" not in stored and TOKEN not in stored, "secrets never go to the plain settings file"
    status = provisioning.status(data)
    assert status["imported"] and status["name"] == "ACME pilot" and status["unreadable_secrets"] == []
    assert "s3cret-pass" not in json.dumps(status) and "WIZARD_PG_PASSWORD" in status["secrets"]


def test_provisioned_values_sit_under_the_pcs_own_env(tmp_path):
    provisioning.import_file(provision_file(tmp_path / "p.json"), tmp_path / "data")
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=code-assist\nWIZARD_PG_DATABASE=other\n", encoding="utf-8")
    settings = load_settings(env={}, home=tmp_path)
    assert settings.postgres and settings.postgres.host == "db.corp.example" and settings.postgres.password == "s3cret-pass"
    assert settings.postgres.database == "other", ".env wins over the provisioning file"
    assert settings.kb_repo == "acme/wizard-content" and settings.kb_token == TOKEN
    assert settings.google_cloud_project == "corp-gemini"
    assert settings.provision["imported"] is True
    assert load_settings(env={"WIZARD_PG_HOST": "db2.example"}, home=tmp_path).postgres.host == "db2.example"


@pytest.mark.parametrize(("body", "message"), [
    ("not json", "not valid JSON"),
    (json.dumps({"settings": {"WIZARD_KB_REPO": "a/b"}}), "not a Wizard provisioning file"),
    (json.dumps({"wizard_provision": 1, "settings": {}}), "no settings"),
    (json.dumps({"wizard_provision": 1, "settings": {"PATH": "x"}}), "not a Wizard setting"),
    (json.dumps({"wizard_provision": 1, "settings": {"WIZARD_DATA_DIR": "x"}}), "set on each PC"),
    (json.dumps({"wizard_provision": 1, "settings": {"WIZARD_PG_HOST": "a\nb"}}), "one-line"),
])
def test_a_bad_provisioning_file_is_refused(tmp_path, body, message):
    path = tmp_path / "wizard.provision"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(provisioning.ProvisionError, match=message):
        provisioning.import_file(path, tmp_path / "data")
    assert path.exists(), "a refused file is left for the person to fix"


def test_run_py_imports_a_provisioning_file(tmp_path):
    offered = provision_file(tmp_path / "company.provision")
    result = subprocess.run([sys.executable, str(ROOT / "run.py"), "--home", str(tmp_path), "--import-provision",
                             str(offered)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "WIZARD_PG_PASSWORD" in result.stdout and "s3cret" not in result.stdout
    assert (tmp_path / "data" / "provision" / "secrets.bin").is_file()


# Knowledge base sync ----------------------------------------------------------------------------------------------------
def archive(commit: str, files: dict[str, str], top: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        prefix = top if top is not None else f"acme-wizard-content-{commit[:7]}/"
        for name, text in files.items():
            bundle.writestr(prefix + name, text)
    return buffer.getvalue()


class FakeGitHub:
    """The two GitHub calls a sync makes: the commit at a ref (with ETags) and the commit's zipball (via codeload)."""

    def __init__(self, commit: str, files: dict[str, str]):
        self.commit, self.files, self.status = commit, files, 200
        self.calls: list[tuple[str, str, str | None]] = []
        self.zip: bytes | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url, request.headers.get("authorization")))
        if self.status != 200:
            return httpx.Response(self.status)
        if url.endswith("/repos/acme/wizard-content/commits/main"):
            assert request.headers["accept"] == "application/vnd.github.sha"
            etag = f'"{self.commit}"'
            if request.headers.get("if-none-match") == etag:
                return httpx.Response(304)
            return httpx.Response(200, text=self.commit, headers={"ETag": etag})
        if url.endswith(f"/repos/acme/wizard-content/zipball/{self.commit}"):
            return httpx.Response(302, headers={"Location": f"https://codeload.github.com/acme/legacy.zip/{self.commit}?token=t"})
        if url.startswith("https://codeload.github.com/"):
            return httpx.Response(200, content=self.zip or archive(self.commit, self.files))
        return httpx.Response(404)


def kb(path: str = "") -> knowledge_sync.Source:
    return knowledge_sync.Source("acme/wizard-content", "main", path, TOKEN)


def test_sync_downloads_validates_and_then_only_checks(tmp_path):
    github = FakeGitHub("a" * 40, {"knowledge/company/overview.md": NOTE, "README.md": "# content"})
    sync = functools.partial(knowledge_sync.sync, kb(), tmp_path, transport=httpx.MockTransport(github))
    first = sync()
    assert first.outcome == "updated" and first.commit == "a" * 40
    active = knowledge_sync.active_content(tmp_path, kb())
    assert active == tmp_path / "knowledge" / "snapshots" / ("a" * 12)
    assert (active / "knowledge" / "company" / "overview.md").read_text(encoding="utf-8") == NOTE
    codeload = [c for c in github.calls if "codeload" in c[1]]
    assert codeload and codeload[0][2] is None, "the token is not sent to the redirect target"
    api = [c for c in github.calls if "codeload" not in c[1]]
    assert [c[1] for c in api] == ["https://github.sec.samsung.net/api/v3/repos/acme/wizard-content/commits/main",
                                   f"https://github.sec.samsung.net/api/v3/repos/acme/wizard-content/zipball/{'a' * 40}"]
    assert all(c[2] == f"Bearer {TOKEN}" for c in api)
    before = len(github.calls)
    assert sync().outcome == "current"
    assert len(github.calls) == before + 1, "an unchanged repository costs one conditional request"
    state = knowledge_sync.read_state(tmp_path)
    assert TOKEN not in json.dumps(state)


def test_the_github_server_is_fixed_and_older_snapshots_are_not_used(tmp_path):
    env = {"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN,
           "WIZARD_KB_API": "https://api.github.com", "WIZARD_GITHUB_API": "https://api.github.com"}
    github = FakeGitHub("a" * 40, {"knowledge/company/overview.md": NOTE})
    source = kb_source(load_settings(env=env, home=tmp_path))
    assert knowledge_sync.sync(source, tmp_path / "data", transport=httpx.MockTransport(github)).outcome == "updated"
    assert all(c[1].startswith(("https://github.sec.samsung.net/api/v3/", "https://codeload.")) for c in github.calls)
    assert knowledge_sync.status(tmp_path / "data", source, None)["api"] == "https://github.sec.samsung.net/api/v3"
    state = knowledge_sync.read_state(tmp_path / "data")
    del state["api"]  # a snapshot synced before the server was fixed came from github.com
    (tmp_path / "data" / "knowledge" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert knowledge_sync.active_content(tmp_path / "data", source) is None


def test_an_invalid_commit_keeps_the_previous_version(tmp_path):
    github = FakeGitHub("a" * 40, {"knowledge/company/overview.md": NOTE})
    transport = httpx.MockTransport(github)
    assert knowledge_sync.sync(kb(), tmp_path, transport=transport).outcome == "updated"
    github.commit = "b" * 40
    github.files = {"knowledge/company/overview.md": NOTE + '\npassword = "hunter22"\n'}
    result = knowledge_sync.sync(kb(), tmp_path, transport=transport)
    assert result.outcome == "invalid" and "previous version stays in use" in result.message
    assert knowledge_sync.active_content(tmp_path, kb()).name == "a" * 12
    assert "credentials" in knowledge_sync.read_state(tmp_path)["last_error"]
    github.files = {"knowledge/company/overview.md": NOTE.replace("We sell phones.", "We sell phones and tablets.")}
    assert knowledge_sync.sync(kb(), tmp_path, transport=transport).outcome == "updated"
    state = knowledge_sync.read_state(tmp_path)
    assert state["active"] == "b" * 12 and state["previous"] == "a" * 12 and state["last_error"] is None
    assert {p.name for p in (tmp_path / "knowledge" / "snapshots").iterdir()} == {"a" * 12, "b" * 12}


def test_sync_uses_the_configured_folder_and_refuses_unsafe_archives(tmp_path):
    github = FakeGitHub("c" * 40, {"content/knowledge/platforms/asap.md": GUIDE, "tools/build.py": "print()"})
    transport = httpx.MockTransport(github)
    assert knowledge_sync.sync(kb("content"), tmp_path, transport=transport).outcome == "updated"
    active = knowledge_sync.active_content(tmp_path, kb("content"))
    assert (active / "knowledge" / "platforms" / "asap.md").is_file() and not (active / "tools").exists()
    assert knowledge_sync.active_content(tmp_path, kb("other")) is None, "a snapshot of another folder is not used"
    github.commit = "d" * 40
    github.zip = archive("d" * 40, {"knowledge/../../evil.md": "x"})
    result = knowledge_sync.sync(kb(), tmp_path / "second", transport=transport)
    assert result.outcome == "failed" and "unsafe path" in result.message
    github.zip = archive("d" * 40, {"README.md": "x", "knowledge/a.md": "x"}, top="")
    assert "unexpected archive layout" in knowledge_sync.sync(kb(), tmp_path / "third", transport=transport).message


@pytest.mark.parametrize(("status", "words"), [(401, "invalid or expired"), (404, "Contents: read"), (403, "SSO"),
                                               (409, "is empty: nothing has been published")])
def test_github_refusals_are_explained(tmp_path, status, words):
    github = FakeGitHub("a" * 40, {})
    github.status = status
    result = knowledge_sync.sync(kb(), tmp_path, transport=httpx.MockTransport(github))
    assert result.outcome == "failed" and words in result.message
    assert knowledge_sync.status(tmp_path, kb(), None)["last_error"] == result.message


def test_no_token_and_no_repository(tmp_path):
    assert knowledge_sync.sync(None, tmp_path).outcome == "not_configured"
    no_token = knowledge_sync.Source("acme/wizard-content", "main", "", None)
    assert "WIZARD_KB_TOKEN is missing" in knowledge_sync.sync(no_token, tmp_path).message


def test_settings_load_the_synced_snapshot_and_never_the_synthetic_examples(tmp_path):
    env = {"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN}
    settings = load_settings(env=env, home=tmp_path)
    assert settings.content_dir is None
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        assert client.get("/api/v1/sources").json()["sources"] == [], "no synthetic ASAP/GSCM/NERP before the first sync"
        boot = client.get("/api/v1/bootstrap").json()
        assert boot["suggestions"] == [] and "SYNTHETIC" not in boot["data_modes"]
        ready = client.get("/api/v1/ready").json()
        assert ready["checks"]["content"] == "knowledge base not synced yet"
        assert ready["checks"]["knowledge_base"]["configured"] and TOKEN not in json.dumps(ready)
    github = FakeGitHub("a" * 40, {"knowledge/platforms/asap.md": GUIDE})
    knowledge_sync.sync(kb(), settings.data_dir, transport=httpx.MockTransport(github))
    settings = load_settings(env=env, home=tmp_path)
    assert settings.content_dir == settings.data_dir / "knowledge" / "snapshots" / ("a" * 12)
    with pytest.raises(ConfigError, match="not both"):
        load_settings(env={**env, "WIZARD_CONTENT_DIR": "content"}, home=tmp_path)
    with pytest.raises(ConfigError, match="owner/name"):
        load_settings(env={**env, "WIZARD_KB_REPO": "not a repo"}, home=tmp_path)
    with pytest.raises(ConfigError, match="inside the repository"):
        load_settings(env={**env, "WIZARD_KB_PATH": "../etc"}, home=tmp_path)


# Desktop start-up and control API ---------------------------------------------------------------------------------------
def test_desktop_start_adds_defaults_imports_the_file_and_syncs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    provision_file(home / "wizard.provision", WIZARD_PG_HOST="db.corp.example")
    github = FakeGitHub("e" * 40, {"knowledge/company/overview.md": NOTE})
    monkeypatch.setattr(knowledge_sync, "sync", functools.partial(knowledge_sync.sync, transport=httpx.MockTransport(github)))
    settings = desktop.prepare(home, env={})
    text = (home / ".env").read_text(encoding="utf-8")
    assert "WIZARD_AGENT_RUNTIME=code-assist" in text and "WIZARD_PORT=8771" in text and "WIZARD_DIAGNOSTICS=false" in text
    assert settings.desktop and settings.runtime == "code-assist" and settings.port == 8771
    assert not (home / "wizard.provision").exists()
    assert settings.content_dir and settings.content_dir.name == "e" * 12
    assert (home / "logs" / "wizard.log").is_file()
    (home / ".env").write_text(text.replace("WIZARD_PORT=8771", "WIZARD_PORT=9000"), encoding="utf-8")
    assert desktop.ensure_env(home) == [], "existing values are never changed"
    assert "WIZARD_PORT=9000" in (home / ".env").read_text(encoding="utf-8")


def test_a_bad_provisioning_file_stops_desktop_start_with_a_reason(tmp_path):
    (tmp_path / "wizard.provision").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="could not be imported"):
        desktop.prepare(tmp_path, env={})


def desktop_app(tmp_path, **env: str):
    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_CONTROL_TOKEN": CONTROL,
                                  "WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN, **env}, home=tmp_path)
    settings.desktop = True
    return create_app(settings)


def test_desktop_signs_in_only_the_person_at_this_pc(tmp_path):
    with TestClient(desktop_app(tmp_path, WIZARD_LOCAL_USER_NAME="Rafael")) as client:
        identities = client.get("/api/v1/session/identities").json()["identities"]
        assert [i["id"] for i in identities] == ["local-owner"], "no synthetic test identities in the desktop app"


def test_control_api_needs_the_launch_token(tmp_path):
    with TestClient(create_app(load_settings(env={}, home=tmp_path))) as client:
        assert client.get("/internal/v1/desktop/status").status_code == 404, "off unless WizardBar set a token"
    with TestClient(desktop_app(tmp_path / "d")) as client:
        assert client.get("/internal/v1/desktop/status").status_code == 401
        assert client.get("/internal/v1/desktop/status", headers={"X-Wizard-Control": "w" * 40}).status_code == 401
        status = client.get("/internal/v1/desktop/status", headers={"X-Wizard-Control": CONTROL}).json()
        assert status["knowledge_base"]["repo"] == "acme/wizard-content" and status["active_runs"] == 0
        assert client.post("/internal/v1/desktop/stop", headers={"X-Wizard-Control": CONTROL}).status_code == 409
    with pytest.raises(ConfigError, match="at least 32"):
        load_settings(env={"WIZARD_CONTROL_TOKEN": "short"}, home=tmp_path)


def test_a_file_dropped_on_wizardbar_can_be_attached_once_from_where_it_is(tmp_path):
    elsewhere = tmp_path / "Shared drive" / "Q3"
    elsewhere.mkdir(parents=True)
    (elsewhere / "sell-in.csv").write_bytes(b"Market,Units\nEG,1200\n")
    (elsewhere / "scan.pdf").write_bytes(b"%PDF")
    headers = {**HEADERS, "X-Wizard-Control": CONTROL}
    with TestClient(desktop_app(tmp_path / "home", WIZARD_ATTACHMENT_FOLDERS="none")) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        path = str(elsewhere / "sell-in.csv")
        assert client.post("/api/v1/attachments/local", json={"path": path}, headers=HEADERS).status_code == 403, "not dropped"
        body = {"paths": [path, str(elsewhere / "scan.pdf"), str(elsewhere / "gone.xlsx")]}
        assert client.post("/internal/v1/desktop/drop", json=body, headers=HEADERS).status_code == 401, "only WizardBar grants"
        files = client.post("/internal/v1/desktop/drop", json=body, headers=headers).json()["files"]
        assert files[0] == {"path": str((elsewhere / "sell-in.csv").resolve()), "name": "sell-in.csv"}
        assert "PDF" in files[1]["error"] and files[2]["error"] == "That file could not be opened."
        added = client.post("/api/v1/attachments/local", json={"path": files[0]["path"]}, headers=HEADERS).json()["attachment"]
        assert added["origin"] == "local" and added["status"] == "ok" and added["filename"] == "sell-in.csv"
        again = client.post("/api/v1/attachments/local", json={"path": files[0]["path"]}, headers=HEADERS)
        assert again.status_code == 403, "a drop allows one attach"


def test_sync_now_restarts_the_service_on_a_new_version(tmp_path, monkeypatch):
    github = FakeGitHub("a" * 40, {"knowledge/company/overview.md": NOTE})
    monkeypatch.setattr(knowledge_sync, "sync", functools.partial(knowledge_sync.sync, transport=httpx.MockTransport(github)))
    app = desktop_app(tmp_path)
    asked: list[str] = []
    app.state.request_restart = lambda: asked.append("restart")
    app.state.request_stop = lambda: asked.append("stop")
    headers = {**HEADERS, "X-Wizard-Control": CONTROL}
    with TestClient(app) as client:
        first = client.post("/internal/v1/desktop/sync", headers=headers).json()
        assert first["outcome"] == "updated" and first["restarting"] is True and asked == ["restart"]
        assert first["knowledge_base"]["restart_pending"] and first["knowledge_base"]["commit"] == "a" * 40
        again = client.post("/internal/v1/desktop/sync", headers=headers).json()
        assert again["outcome"] == "current" and again["restarting"], "still on the old content: asks again"
        assert client.post("/internal/v1/desktop/stop", headers=headers).json() == {"stopping": True}
        assert asked == ["restart", "restart", "stop"]


def test_company_domains_limit_which_google_accounts_link(tmp_path):
    def google(email: str) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if "token" in str(request.url):
                return httpx.Response(200, json={"access_token": "ya29.x", "refresh_token": "1//r", "expires_in": 3600})
            return httpx.Response(200, json={"email": email})
        return httpx.MockTransport(handler)

    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_GOOGLE_DOMAINS": "corp.example, @Corp.Asia"},
                             home=tmp_path)
    assert settings.google_domains == ["corp.asia", "corp.example"]
    for email, code in (("someone@gmail.com", 403), ("rafael@corp.asia", 200)):
        with TestClient(create_app(settings, google_transport=google(email))) as client:
            client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
            state = client.post("/api/v1/account/gemini/link", headers=HEADERS).json()["state"]
            linked = client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS)
            assert linked.status_code == code, linked.text
            if code == 403:
                assert "work Google account" in linked.json()["error"]


def test_run_py_desktop_serves_and_stops_when_the_bar_asks(tmp_path):
    import os
    import time

    from tests.helpers import free_port

    port = free_port()
    env = {**os.environ, "WIZARD_PORT": str(port), "WIZARD_CONTROL_TOKEN": CONTROL, "WIZARD_PROXY": "direct"}
    process = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "--home", str(tmp_path), "--desktop"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        status = httpx.get(f"http://127.0.0.1:{port}/internal/v1/desktop/status", headers={"X-Wizard-Control": CONTROL}).json()
        assert status["runtime"] == "code-assist" and status["content"] == "synthetic"
        httpx.post(f"http://127.0.0.1:{port}/internal/v1/desktop/stop", headers={"X-Wizard-Control": CONTROL, **HEADERS})
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.kill()
    assert (tmp_path / "logs" / "wizard.log").is_file()


def test_make_provision_script_writes_a_file_wizard_accepts(tmp_path):
    source = tmp_path / "company.env"
    source.write_text(f"WIZARD_KB_REPO=acme/wizard-content\nWIZARD_KB_TOKEN={TOKEN}\nWIZARD_PG_PASSWORD=x\nWIZARD_KB_PATH=\n",
                      encoding="utf-8")
    out = tmp_path / "wizard.provision"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_provision.py"), str(source), "--name", "ACME",
                             "--out", str(out)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert TOKEN not in result.stdout and "2 secret(s)" in result.stdout
    provision = provisioning.import_file(out, tmp_path / "data")
    assert provision.name == "ACME" and "WIZARD_KB_PATH" not in provision.settings, "empty values are left out"
    source.write_text("WIZARD_DATA_DIR=elsewhere\n", encoding="utf-8")
    refused = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_provision.py"), str(source), "--out", str(out)],
                             capture_output=True, text=True, timeout=60)
    assert refused.returncode == 2 and "set on each PC" in refused.stderr


def test_the_desktop_pieces_agree_with_each_other():
    """WizardBar (C#), the installer, CI and the Python service name the same release, files, codes and port."""
    import re

    sys.path.insert(0, str(ROOT / "scripts"))
    from build_desktop_payload import source_files

    bar = ROOT / "apps" / "desktop" / "WizardBar"
    updater = (bar / "Updater.cs").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    setup = (ROOT / "installer" / "Wizard.iss").read_text(encoding="utf-8")
    tag = re.search(r"releases/download/([a-z-]+)/", updater).group(1)
    assert f"gh release upload {tag} dist/WizardSetup.exe" in workflow and f"gh release upload {tag} dist/wizard-desktop.json" in workflow
    assert '"wizard-desktop.json"' in updater and '"WizardSetup.exe"' in updater and "OutputBaseFilename=WizardSetup" in setup
    # The mirror the updater reads first (as Metronome's setup.ps1 reads its branch) is the branch CI pushes.
    assert "git init -q -b desktop-download" in workflow and "cp dist/WizardSetup.exe dist/wizard-desktop.json" in workflow
    assert "contents/wizard-desktop.json?ref=desktop-download" in updater and "archive/refs/heads/desktop-download.zip" in updater
    assert "contents/wizard-desktop.json?ref=desktop-download" in settings_pane.MIRROR_MANIFEST
    assert f"public const int Attempts = {settings_pane.UPDATE_ATTEMPTS};" in updater
    assert f"RestartExitCode = {desktop.RESTART_EXIT_CODE};" in (bar / "Backend.cs").read_text(encoding="utf-8")
    assert f"return {desktop.DEFAULT_PORT};" in (bar / "Paths.cs").read_text(encoding="utf-8")
    assert f'"{provisioning.FILENAME}"' in (bar / "Paths.cs").read_text(encoding="utf-8")
    assert f"{{src}}\\{provisioning.FILENAME}" in setup and "{localappdata}\\Wizard" in setup
    assert (ROOT / "apps" / "desktop" / "assets" / "wizard.ico").is_file()
    files = set(source_files())
    assert {"run.py", "apps/web/dist/index.html", "fixtures/identities.json", "services/api/wizard_api/app.py"} <= files
    assert not any(f.startswith(("tests/", "apps/desktop/", "apps/web/src/", ".github/")) for f in files)



def test_page_polling_does_not_count_as_someone_using_wizard(tmp_path):
    import time

    app = desktop_app(tmp_path)
    asked: list[str] = []
    with TestClient(app) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        github = FakeGitHub("a" * 40, {"knowledge/company/overview.md": NOTE})
        knowledge_sync.sync(kb(), app.state.settings.data_dir, transport=httpx.MockTransport(github))
        app.state.request_restart = lambda: asked.append("restart")
        client.get("/api/v1/bootstrap")
        assert app.state.restart_if_idle(5) is False and asked == [], "someone just used Wizard"
        time.sleep(0.3)
        client.get("/api/v1/account/gemini/quota")
        client.get("/api/v1/health")
        assert app.state.restart_if_idle(0.2) is True and asked == ["restart"], "the quota ring and probes are not use"


def test_bootstrap_lists_the_systems_for_the_stage_with_the_database_display_name(tmp_path):
    from wizard_api.runs import tool_label

    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_PG_HOST": "db.example", "WIZARD_PG_USER": "ro",
                                  "WIZARD_LOCAL_USER_NAME": "Rafael"}, home=tmp_path)
    assert settings.pg_name == "AI Team Database"
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        systems = {s["id"]: s for s in client.get("/api/v1/bootstrap").json()["systems"]}
        assert {"asap", "gscm", "nerp", "postgresql", "knowledge", "attachment"} <= set(systems)
        assert systems["postgresql"] == {"id": "postgresql", "name": "AI Team Database", "kind": "database", "data_mode": "LIVE"}
        assert systems["knowledge"]["notes"] > 0
        services = client.app.state.manager.services
        assert tool_label("wizard_query_postgresql", {"sql": "select 1"}, services) == "Queried the AI Team Database"
    renamed = load_settings(env={"WIZARD_AGENT_RUNTIME": "code-assist", "WIZARD_PG_HOST": "db.example", "WIZARD_PG_USER": "ro",
                                 "WIZARD_PG_NAME": "Sales Data Hub"}, home=tmp_path)
    with TestClient(create_app(renamed)) as client:
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        ids = [s["id"] for s in client.get("/api/v1/bootstrap").json()["systems"]]
        assert "postgresql" not in ids, "only systems this person may use"
        assert client.app.state.manager.services.postgres_name == "Sales Data Hub"

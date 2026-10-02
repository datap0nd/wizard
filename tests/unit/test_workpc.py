"""Work-PC installation pieces: install-relative settings, the local owner identity, run.py --check, the wheel vendoring
step, the Gemini CLI task kit, and the PowerShell scripts' syntax."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS

from wizard_api.app import create_app
from wizard_api.config import ConfigError, load_settings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_install_folder_settings_resolve_relative_paths(tmp_path):
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=gemini-cli\nWIZARD_CONTENT_DIR=content\nWIZARD_LOCAL_USER_EMAIL=Me@Corp.test\n",
                                   encoding="utf-8")
    settings = load_settings(env={}, home=tmp_path)
    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.content_dir == (tmp_path / "content").resolve()
    assert settings.local_user_email == "Me@Corp.test" and settings.local_user_name == "Me"
    with pytest.raises(ConfigError):
        load_settings(env={"WIZARD_LOCAL_USER_EMAIL": "not-an-email"}, home=tmp_path)


def test_local_owner_identity_signs_in_with_the_real_email(tmp_path):
    settings = load_settings(env={"WIZARD_LOCAL_USER_EMAIL": "Rafael@Corp.test", "WIZARD_LOCAL_USER_NAME": "Rafael"}, home=tmp_path)
    with TestClient(create_app(settings)) as client:
        identities = client.get("/api/v1/session/identities").json()["identities"]
        assert identities[0] == {"id": "local-owner", "name": "Rafael", "role": "Owner (local test)", "email": "rafael@corp.test"}
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        assert {s["id"] for s in client.get("/api/v1/sources").json()["sources"]} == {"asap", "gscm", "nerp"}
        assert client.get("/api/v1/bootstrap").json()["identity"]["email"] == "rafael@corp.test"


def test_run_check_on_a_fresh_install_folder(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "run.py"), "--home", str(tmp_path), "--check"], capture_output=True,
                            text=True, timeout=120, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS  application starts; platforms: ASAP, GSCM, NERP" in result.stdout
    assert (tmp_path / "data" / "wizard.sqlite3").is_file(), "data lives in the install folder, not the release"


def _wheel(path: Path, files: dict[str, str]) -> dict:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return {"name": path.name.split("-")[0], "version": "1.0", "filename": path.name, "url": "",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_vendor_dependencies_verifies_and_reuses_archives(tmp_path):
    from vendor_dependencies import vendor
    cache, store = tmp_path / "cache", tmp_path / "store"
    cache.mkdir()
    packages = [_wheel(cache / "alpha-1.0-py3-none-any.whl", {"alpha/__init__.py": "A = 1\n"}),
                _wheel(cache / "beta-1.0-cp313-cp313-win_amd64.whl", {"beta/__init__.py": "B = 2\n"})]
    lock = tmp_path / "dependencies.lock.json"
    lock.write_text(json.dumps({"format": 2, "packages": packages}), encoding="utf-8")
    assert vendor(cache, store, tmp_path / "release" / "vendor", lock) == {"unpacked": 2, "reused": 0}
    assert (tmp_path / "release" / "vendor" / "alpha" / "__init__.py").read_text() == "A = 1\n"
    assert vendor(cache, store, tmp_path / "release2" / "vendor", lock) == {"unpacked": 0, "reused": 2}
    (cache / "alpha-1.0-py3-none-any.whl").write_bytes(b"tampered")
    shutil.rmtree(store)
    with pytest.raises(ValueError, match="invalid downloaded archive"):
        vendor(cache, store, tmp_path / "release3" / "vendor", lock)
    lock.write_text(json.dumps({"format": 2, "packages": [{**packages[0], "filename": "evil-1.0-cp313-cp313-linux_x86_64.whl"}]}))
    with pytest.raises(ValueError, match="Only pure-Python"):
        vendor(cache, store, tmp_path / "release4" / "vendor", lock)


def test_portable_locks_are_consistent():
    assets = json.loads((ROOT / "portable_assets.lock.json").read_text(encoding="utf-8"))
    for name, key in (("runtime.lock.json", "runtime_lock_sha256"), ("dependencies.lock.json", "dependency_lock_sha256")):
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == assets[key]
    runtime = json.loads((ROOT / "runtime.lock.json").read_text(encoding="utf-8"))
    assert runtime["filename"] == f"python-{runtime['version']}-embed-amd64.zip"
    names = {p["name"] for p in json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))["packages"]}
    assert {"fastapi", "uvicorn", "pydantic", "pydantic-core", "httpx", "starlette"} <= names


def test_gemini_task_kit_is_complete():
    tasks = ROOT / "workpc" / "tasks"
    files = sorted(p for p in tasks.glob("[0-9][0-9]-*.md"))
    start = (tasks / "START_HERE.md").read_text(encoding="utf-8")
    for task in files:
        text = task.read_text(encoding="utf-8")
        number = task.name[:2]
        assert text.startswith(f"# Task {number} "), task.name
        for marker in ("**Goal:**", "**Output", "Shareable", "**Done when:**"):
            assert marker in text, f"{task.name} lacks {marker}"
        assert re.search(rf"^\| {number} ", start, re.M), f"START_HERE status table lacks task {number}"
    command = tomllib.loads((ROOT / "workpc" / ".gemini" / "commands" / "wizard" / "tasks.toml").read_text(encoding="utf-8"))
    assert "{{args}}" in command["prompt"] and "START_HERE" in command["prompt"]
    ignore = (ROOT / "workpc" / ".geminiignore").read_text(encoding="utf-8").split()
    assert {"data/", ".env", "releases/"} <= set(ignore), "Gemini sessions must not read sign-ins or secrets"


@pytest.mark.skipif(not (shutil.which("pwsh") or shutil.which("powershell")), reason="BLOCKED: no PowerShell available")
@pytest.mark.parametrize("script", ["setup.ps1", "start.ps1", "update_app.ps1", "scripts/dev.ps1"])
def test_powershell_scripts_parse(script):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    command = ("$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
               f"'{ROOT / script}', [ref]$null, [ref]$errors) | Out-Null; "
               "if ($errors) { $errors | ForEach-Object { $_.ToString() }; exit 1 }")
    result = subprocess.run([shell, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

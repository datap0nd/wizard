from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from wizard_agent import google_oauth
from wizard_agent.secret_box import SecretBox
from wizard_api.config import ConfigError, load_settings
from wizard_api.security import run_token, session_token, sign, verify


def test_link_url_is_pkce_user_code_flow():
    url, state, verifier = google_oauth.start_link()
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == ["https://codeassist.google.com/authcode"]
    assert query["code_challenge_method"] == ["S256"] and query["state"] == [state] and len(state) == 64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert "cloud-platform" in query["scope"][0] and query["access_type"] == ["offline"]


def test_code_exchange_and_cli_credentials(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["code_verifier"] == ["v"] and form["redirect_uri"] == [google_oauth.USER_CODE_REDIRECT]
        return httpx.Response(200, json={"access_token": "ya29.a", "refresh_token": "1//r", "expires_in": 3600})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await google_oauth.exchange_code(http, " code ", "v")

    tokens = asyncio.run(go())
    path = google_oauth.write_cli_credentials(tmp_path, tokens)
    saved = json.loads(path.read_text())
    assert saved["refresh_token"] == "1//r" and saved["token_type"] == "Bearer" and saved["expiry_date"] > time.time() * 1000
    google_oauth.clear_cli_credentials(tmp_path)
    assert not path.exists()


def test_secret_box_round_trip(tmp_path):
    for box in (SecretBox(), SecretBox(force_plain=True)):
        target = tmp_path / box.kind / "secret.bin"
        box.write(target, "1//refresh")
        assert box.read(target) == "1//refresh"
        if box.kind == "dpapi":
            assert b"1//refresh" not in target.read_bytes()


def test_signed_tokens():
    secret = b"k" * 32
    token = session_token(secret, "u-ceo", 1)
    assert verify(secret, "session", token)["u"] == "u-ceo"
    assert verify(secret, "run", token) is None, "a session cookie is not a run token"
    assert verify(b"x" * 32, "session", token) is None
    body, mac = token.split(".")
    assert verify(secret, "session", body[:-2] + "AA." + mac) is None
    assert verify(secret, "session", sign(secret, "session", {"u": "x", "exp": time.time() - 1})) is None
    assert verify(secret, "run", run_token(secret, "run_1", "u-ceo", 60))["r"] == "run_1"


def test_config_validation(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(env={"WIZARD_DATA_DIR": str(tmp_path), "WIZARD_AGENT_RUNTIME": "magic"}, env_file=tmp_path / "x")
    with pytest.raises(ConfigError):
        load_settings(env={"WIZARD_DATA_DIR": str(tmp_path), "WIZARD_PORT": "99999"}, env_file=tmp_path / "x")
    env_file = tmp_path / ".env"
    env_file.write_text("WIZARD_GEMINI_MODEL='gemini-3.8-flash'\nWIZARD_PORT=8800\n# comment\n")
    settings = load_settings(env={"WIZARD_DATA_DIR": str(tmp_path), "WIZARD_PORT": "8801"}, env_file=env_file)
    assert settings.model == "gemini-3.8-flash" and settings.port == 8801 and settings.runtime == "replay"
    assert settings.user_home("u-a") != settings.user_home("u-b")

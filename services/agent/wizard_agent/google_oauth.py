"""Per-user Google sign-in for Gemini (enterprise), ported from Scribble's working implementation.

Source: datap0nd/scribble commit 41ab532 (27 Aug 2026), src/Scribble/Configuration/GoogleSignInFlow.cs and
src/Scribble/Chat/GeminiCodeAssistGateway.cs - the last revision before b0889a4 put direct Gemini behind a build flag.
Scribble used the installed-app PKCE flow with a loopback redirect on the user's own PC. Wizard is a web app used from
other machines, so it uses the Gemini CLI's own "user code" variant (verified in gemini-cli-core 0.62.0 oauth2.js
authWithUserCode): redirect to https://codeassist.google.com/authcode, which shows the code; the user pastes it into
Wizard. Same OAuth client, same scopes, same PKCE S256 - so whatever an admin allowed for Gemini CLI applies here.

The user's password never reaches Wizard: Google's pages handle sign-in, Wizard receives tokens only.
Tokens are stored per user (SecretBox) and can also seed that user's own Gemini CLI home (oauth_creds.json), which the
CLI migrates into its per-home encrypted file store on first use."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

# Published installed-app OAuth client of the open-source Gemini CLI (Apache-2.0; packages/core/src/code_assist/oauth2.ts).
# Installed-app client secrets are not confidential. Override with an enterprise-registered client if IT prefers.
GEMINI_CLI_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
GEMINI_CLI_CLIENT_SECRET = "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"  # noqa: S105  gitleaks:allow (public installed-app client)
AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint URL, not a secret
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"
USER_CODE_REDIRECT = "https://codeassist.google.com/authcode"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email "
          "https://www.googleapis.com/auth/userinfo.profile")
REFRESH_MARGIN_S = 120


class OAuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float
    scope: str = SCOPES

    def fresh(self) -> bool:
        return bool(self.access_token) and self.expires_at - time.time() > REFRESH_MARGIN_S


def client_id() -> str:
    return os.environ.get("WIZARD_GOOGLE_OAUTH_CLIENT_ID") or GEMINI_CLI_CLIENT_ID


def client_secret() -> str:
    return os.environ.get("WIZARD_GOOGLE_OAUTH_CLIENT_SECRET") or GEMINI_CLI_CLIENT_SECRET


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start_link() -> tuple[str, str, str]:
    """Returns (authorize_url, state, code_verifier). Keep the verifier server-side; only the URL goes to the browser."""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_hex(32)
    query = urlencode({"client_id": client_id(), "redirect_uri": USER_CODE_REDIRECT, "response_type": "code",
                       "scope": SCOPES, "access_type": "offline", "prompt": "consent", "code_challenge": challenge,
                       "code_challenge_method": "S256", "state": state})
    return f"{AUTHORIZE_ENDPOINT}?{query}", state, verifier


async def exchange_code(http: httpx.AsyncClient, code: str, verifier: str) -> Tokens:
    response = await http.post(TOKEN_ENDPOINT, data={
        "code": code.strip(), "client_id": client_id(), "client_secret": client_secret(),
        "redirect_uri": USER_CODE_REDIRECT, "grant_type": "authorization_code", "code_verifier": verifier})
    if response.status_code != 200:
        raise OAuthError("code_exchange_failed", "Google did not accept that code. Start the link again and paste the "
                                                 "newest code shown after sign-in.")
    body = response.json()
    if not body.get("refresh_token"):
        raise OAuthError("no_refresh_token", "Google returned no refresh token. Remove the app's access at "
                                             "myaccount.google.com/permissions and link again.")
    return Tokens(body["access_token"], body["refresh_token"], time.time() + int(body.get("expires_in", 3600)),
                  body.get("scope", SCOPES))


async def refresh(http: httpx.AsyncClient, refresh_token: str) -> Tokens:
    response = await http.post(TOKEN_ENDPOINT, data={
        "client_id": client_id(), "client_secret": client_secret(), "refresh_token": refresh_token,
        "grant_type": "refresh_token"})
    if response.status_code != 200 or "access_token" not in response.json():
        raise OAuthError("signin_expired", "Your Google sign-in could not be refreshed. Link your Gemini account again.")
    body = response.json()
    return Tokens(body["access_token"], refresh_token, time.time() + int(body.get("expires_in", 3600)),
                  body.get("scope", SCOPES))


async def userinfo(http: httpx.AsyncClient, access_token: str) -> dict[str, str]:
    response = await http.get(USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise OAuthError("userinfo_failed", "Google did not return the signed-in account.")
    body = response.json()
    return {"email": str(body.get("email", "")), "name": str(body.get("name", ""))}


def write_cli_credentials(gemini_home: Path, tokens: Tokens) -> Path:
    """Seed the user's own Gemini CLI home. With GEMINI_FORCE_FILE_STORAGE=true the CLI migrates this legacy file into
    <home>/.gemini/gemini-credentials.json (encrypted per home) and deletes it."""
    directory = gemini_home / ".gemini"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "oauth_creds.json"
    path.write_text(json.dumps({"access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
                                "scope": tokens.scope, "token_type": "Bearer",
                                "expiry_date": int(tokens.expires_at * 1000)}), encoding="utf-8")
    (directory / "gemini-credentials.json").unlink(missing_ok=True)
    return path


def clear_cli_credentials(gemini_home: Path) -> None:
    for name in ("oauth_creds.json", "gemini-credentials.json", "google_accounts.json"):
        (gemini_home / ".gemini" / name).unlink(missing_ok=True)

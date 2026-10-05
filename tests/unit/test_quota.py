"""The sidebar usage ring: Gemini CLI's retrieveUserQuota, under the person's own sign-in and project."""
from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from tests.helpers import HEADERS

from wizard_agent.code_assist import summarize_quota
from wizard_api.app import create_app
from wizard_api.config import load_settings


def test_summary_selects_the_configured_models_most_constraining_bucket():
    raw = {"buckets": [
        {"modelId": "gemini-3.8-flash", "tokenType": "REQUESTS", "remainingFraction": 0.75, "remainingAmount": "750",
         "resetTime": "2026-10-05T00:00:00Z"},
        {"modelId": "gemini-3.8-flash", "tokenType": "TOKENS", "remainingFraction": 0.4},
        {"modelId": "gemini-3.8-pro", "remainingFraction": 0.1},
        {"modelId": "broken"},
    ]}
    summary = summarize_quota(raw, "gemini-3.8-flash")
    assert summary["selected"]["token_type"] == "TOKENS" and summary["selected"]["used_fraction"] == 0.6
    requests = next(b for b in summary["buckets"] if b["token_type"] == "REQUESTS")
    assert requests["remaining"] == 750 and requests["limit"] == 1000
    assert len(summary["buckets"]) == 3, "buckets without a remainingFraction are ignored"
    preview = summarize_quota({"buckets": [{"modelId": "gemini-3.8-flash-preview", "remainingFraction": 0.9}]}, "gemini-3.8-flash")
    assert preview["selected"]["model_id"] == "gemini-3.8-flash-preview"
    assert summarize_quota({"buckets": [{"modelId": "other", "remainingFraction": 1}]}, "gemini-3.8-flash")["selected"] is None


def test_quota_endpoint_uses_the_users_own_sign_in_and_project(tmp_path):
    calls: list[tuple[str, dict]] = []

    def google(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content or b"{}") if request.headers.get("content-type", "").startswith("application/json") else {}
        calls.append((url.rsplit("/", 1)[-1], body))
        if "oauth2.googleapis.com/token" in url:
            return httpx.Response(200, json={"access_token": "ya29.x", "refresh_token": "1//r", "expires_in": 3600})
        if "userinfo" in url:
            return httpx.Response(200, json={"email": "rafael@company.example"})
        if url.endswith(":loadCodeAssist"):
            return httpx.Response(200, json={"currentTier": {"id": "standard-tier"}, "cloudaicompanionProject": "corp-gemini"})
        if url.endswith(":retrieveUserQuota"):
            return httpx.Response(200, json={"buckets": [{"modelId": "gemini-3.8-flash", "remainingFraction": 0.8,
                                                          "resetTime": "2026-10-06T00:00:00Z"}]})
        return httpx.Response(404)

    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "gemini-cli", "WIZARD_PROXY": "direct"}, home=tmp_path)
    with TestClient(create_app(settings, google_transport=httpx.MockTransport(google))) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        unlinked = client.get("/api/v1/account/gemini/quota").json()
        assert unlinked["available"] is False and unlinked["code"] == "gemini_signin_required"
        state = client.post("/api/v1/account/gemini/link", headers=HEADERS).json()["state"]
        assert client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS).status_code == 200
        quota = client.get("/api/v1/account/gemini/quota?refresh=true").json()
        assert quota["available"] and quota["selected"]["used_fraction"] == 0.2 and quota["model"] == "gemini-3.8-flash"
        assert ("v1internal:retrieveUserQuota", {"project": "corp-gemini"}) in calls
        assert not any(name.endswith(":onboardUser") for name, _ in calls), "showing quota never onboards an account"
        before = len(calls)
        client.get("/api/v1/account/gemini/quota")
        assert len(calls) == before, "cached for a minute"

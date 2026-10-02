"""Signed session cookies, run-scoped tool tokens, request-origin checks and response security headers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

SESSION_COOKIE = "wizard_session"
REQUEST_HEADER = "X-Wizard-Request"
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(secret: bytes, purpose: str, claims: dict[str, Any]) -> str:
    body = _b64(json.dumps({**claims, "p": purpose}, separators=(",", ":")).encode("utf-8"))
    mac = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def verify(secret: bytes, purpose: str, token: str | None) -> dict[str, Any] | None:
    if not token or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    expected = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("p") != purpose or float(claims.get("exp", 0)) < time.time():
        return None
    return dict(claims)


def session_token(secret: bytes, user_id: str, hours: int) -> str:
    now = time.time()
    return sign(secret, "session", {"u": user_id, "iat": int(now), "exp": int(now + hours * 3600)})


def run_token(secret: bytes, run_id: str, user_id: str, ttl_s: int) -> str:
    return sign(secret, "run", {"r": run_id, "u": user_id, "exp": int(time.time() + ttl_s)})

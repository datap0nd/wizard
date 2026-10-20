"""Sign a new Metronome client key in as the Wizard user, once, on the Metronome host PC.

Metronome has no API tokens: it knows a caller by the client key in X-Client-Key, bound to a person in its Users. Wizard
sends one key signed in as the Wizard user, so every Flow it creates belongs to that user
(docs/decisions/2026-10-20-metronome-recurring-extractions.md). Only Python's standard library is used, so Metronome's own
Python can run this file:

    python metronome_link.py                                   # http://127.0.0.1:8000, user "Wizard"
    python metronome_link.py --url http://127.0.0.1:8000 --user Wizard

It makes a random key, finds the user in Metronome's Users (create the user there first), signs the key in as that user
(POST /api/register), checks GET /api/me and prints the key once. Put the key in the company's provisioning file
(WIZARD_METRONOME_CLIENT_KEY) or in Wizard's Settings > Metronome, never in Git.

Run it on the host PC: Metronome lets only the host sign in a computer that already chose a user. Metronome also binds
this PC's address to the Wizard user for a browser here that has never chosen a user; a browser that chose one keeps it.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # Metronome is local: never through a proxy


class LinkError(Exception):
    pass


def call(url: str, path: str, key: str, body: dict[str, Any] | None = None) -> Any:
    if urlsplit(url).scheme not in ("http", "https"):
        raise LinkError(f"--url must be Metronome's http(s) address, not {url}")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url.rstrip("/") + path, data=data, method="POST" if body is not None else "GET",  # noqa: S310 - http(s) only, checked above
                                     headers={"X-Client-Key": key, "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with DIRECT.open(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise LinkError(f"Metronome answered {error.code} to {path}: {detail or error.reason}") from None
    except (urllib.error.URLError, OSError) as error:
        raise LinkError(f"Metronome is not reachable at {url}: {error}") from None


def link(url: str, user: str, key: str) -> dict[str, Any]:
    people = call(url, "/api/people", key)
    matches = [p for p in people if str(p.get("name", "")).strip().casefold() == user.casefold()]
    if not matches:
        raise LinkError(f"Metronome has no user named {user}. Create it in Metronome's Users first (give it the email "
                        "that should receive failure alerts), then run this again.")
    if len(matches) > 1:
        raise LinkError(f"Metronome has {len(matches)} users named {user}; rename all but one.")
    try:
        call(url, "/api/register", key, {"person_id": matches[0]["id"], "client_key": key})
    except LinkError as error:
        if " 409 " in str(error):
            raise LinkError(f"{error} Run this on the Metronome host PC, which may sign a computer in again.") from None
        raise
    me = call(url, "/api/me", key)
    if not me or str(me.get("name", "")).casefold() != user.casefold():
        raise LinkError(f"The key was registered but Metronome reports it as {me and me.get('name')!r}, not {user}.")
    return me


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sign a Metronome client key in as Wizard's Metronome user.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Metronome's address from this PC")
    parser.add_argument("--user", default="Wizard", help="the Metronome user every Wizard Flow belongs to")
    parser.add_argument("--key", help="sign this existing key in again instead of making a new one")
    args = parser.parse_args(argv)
    key = args.key or "wizard-" + secrets.token_urlsafe(32)
    try:
        me = link(args.url, args.user, key)
    except LinkError as error:
        print(f"Not linked: {error}", file=sys.stderr)
        return 1
    print(f"Signed in to Metronome as {me['name']} (user {me['person_id']}).")
    print("Give Wizard this key (provisioning file or Settings > Metronome), with Metronome's address on the office")
    print("network, for example http://<host PC name or address>:8000 (not 127.0.0.1):")
    print(f"WIZARD_METRONOME_CLIENT_KEY={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

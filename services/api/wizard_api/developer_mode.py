"""Developer mode (owner, 19 Nov 2026: "I want the app to be a bit more beginner friendly ... keep tasks and other
'developer' stuff behind a developer mode PIN code menu protection"): docs/decisions/2026-11-19-developer-mode.md.

A person's Settings shows Quick setup, the portals' sign-in and Version and updates. Every other section, the prompt
queue, Tasks, the portal maps, Share as case and the tray's Sync the knowledge base now and Export settings… appear once
the person at this PC enters the developer PIN. It stays on for this PC until they turn it off.

It hides; it is not a password. The repository is public (and copied to the company's GitHub), so only the PIN's salted
digest is here, never its digits. Nothing a developer feature protects depends on it: the write token, the control token
and the person-at-this-PC checks stay where they are, and the APIs answer as before. The flag is a file of its own in
this PC's data folder, so no settings file and no Export settings… ever carries it to another PC."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

SALT = b"wizard-developer:"
# sha256(SALT + PIN). The owner chose the PIN; to change it, put the new digest here.
PIN_SHA256 = "96cb46bac070183bb1264aaa814154129263812e9e85ac360264913c3a05b6b8"
FILE = "developer-mode.json"
MAX_PIN = 32


def digest(pin: str) -> str:
    return hashlib.sha256(SALT + pin.strip().encode("utf-8")).hexdigest()


def pin_matches(pin: str, expected: str | None = None) -> bool:
    if not isinstance(pin, str) or not pin.strip() or len(pin) > MAX_PIN:
        return False
    return hmac.compare_digest(digest(pin), expected or PIN_SHA256)


def path(data_dir: Path) -> Path:
    return data_dir / FILE


def is_on(data_dir: Path) -> bool:
    try:
        return json.loads(path(data_dir).read_text(encoding="utf-8")).get("on") is True
    except (OSError, ValueError, AttributeError):
        return False


def turn_on(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    target = path(data_dir)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"on": True, "since": datetime.now(UTC).isoformat(timespec="seconds")}),
                         encoding="utf-8")
    temporary.replace(target)


def turn_off(data_dir: Path) -> None:
    path(data_dir).unlink(missing_ok=True)

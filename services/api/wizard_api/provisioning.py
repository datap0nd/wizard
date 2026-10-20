"""Organisation settings shipped to a PC as one provisioning file (`wizard.provision`), kept apart from the public code.

The installer and the update channel are public, so they never carry a password or a token. The owner makes the file
(scripts/make_provision.py) and hands it out with the installer: the knowledge-base repository and its read-only token,
the read-only PostgreSQL account, the Gemini project, anything else the company sets for everyone. Wizard imports it
once: plain settings go to data/provision/settings.json, values whose name ends in _PASSWORD, _TOKEN, _SECRET or _KEY go
to data/provision/secrets.bin through the SecretBox (DPAPI on Windows), and the plaintext file is deleted.

Whoever uses the PC can still recover these values (they are on that PC, and the app must read them). What the file
avoids is publishing them: the repository, releases and CI artifacts stay free of credentials.

The settings pane edits a second store in the same format, data/settings ("this PC"), so a new company file never wipes
what the person chose. Precedence: provisioning < this PC (settings pane) < the PC's .env < the environment."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wizard_agent.secret_box import SecretBox

FORMAT = 1
FILENAME = "wizard.provision"
KEY = re.compile(r"^(WIZARD_[A-Z0-9_]{1,60}|GOOGLE_CLOUD_PROJECT)$")
SECRET_SUFFIXES = ("_PASSWORD", "_TOKEN", "_SECRET", "_KEY")
# Per-PC settings: each install decides these itself, so a company file must not move them.
LOCAL_ONLY = frozenset({
    "WIZARD_DATA_DIR", "WIZARD_HOST", "WIZARD_PORT", "WIZARD_LOCAL_USER_EMAIL", "WIZARD_LOCAL_USER_NAME", "WIZARD_AUTH_MODE",
    "WIZARD_IDENTITIES_FILE", "WIZARD_IDENTITY_HEADER", "WIZARD_TRUSTED_PROXIES", "WIZARD_PUBLIC_ORIGIN", "WIZARD_CONTENT_DIR",
    "WIZARD_WEB_DIST", "WIZARD_TRANSCRIPTS_DIR", "WIZARD_ATTACHMENT_FOLDERS", "WIZARD_HTML_REPORTS_DIR", "WIZARD_GEMINI_CLI_JS",
    "WIZARD_NODE", "WIZARD_GEMINI_FAKE_RESPONSES", "WIZARD_CONTROL_TOKEN", "WIZARD_INSTALL_ROOT",
    "WIZARD_KB_PUBLISH_REPO", "WIZARD_KB_PUBLISH_TOKEN", "WIZARD_KB_READ_TOKEN",  # the owner's publishing set-up
})
MAX_BYTES = 64 * 1024


class ProvisionError(ValueError):
    pass


def is_secret(key: str) -> bool:
    return key.endswith(SECRET_SUFFIXES)


LAYERS = {"provision": "provision", "local": "settings"}


def folder(data_dir: Path, layer: str = "provision") -> Path:
    return data_dir / LAYERS[layer]


@dataclass(frozen=True)
class Provision:
    name: str
    settings: dict[str, str]
    secrets: dict[str, str]

    def values(self) -> dict[str, str]:
        return {**self.settings, **self.secrets}


def parse(text: str) -> Provision:
    try:
        raw = json.loads(text)
    except ValueError:
        raise ProvisionError("the provisioning file is not valid JSON") from None
    if not isinstance(raw, dict) or raw.get("wizard_provision") != FORMAT:
        raise ProvisionError(f"not a Wizard provisioning file (expected \"wizard_provision\": {FORMAT})")
    values = raw.get("settings")
    if not isinstance(values, dict) or not values:
        raise ProvisionError("the provisioning file has no settings")
    settings: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not KEY.match(key):
            raise ProvisionError(f"{key!r} is not a Wizard setting (WIZARD_* or GOOGLE_CLOUD_PROJECT)")
        if key in LOCAL_ONLY:
            raise ProvisionError(f"{key} is set on each PC, not in a provisioning file")
        if not isinstance(value, str | int) or isinstance(value, bool) or not str(value).strip() or "\n" in str(value):
            raise ProvisionError(f"{key} must be a one-line text value")
        (secrets if is_secret(key) else settings)[key] = str(value).strip()
    name = raw.get("name")
    return Provision(name=name.strip()[:80] if isinstance(name, str) else "", settings=settings, secrets=secrets)


def import_file(path: Path, data_dir: Path, box: SecretBox | None = None, delete: bool = True) -> Provision:
    """Store a provisioning file for this PC, replacing any earlier one, and delete the plaintext file."""
    if path.stat().st_size > MAX_BYTES:
        raise ProvisionError("the provisioning file is too large")
    provision = parse(path.read_text(encoding="utf-8-sig"))
    _store(folder(data_dir), provision, box, {"imported_at": datetime.now(UTC).isoformat(timespec="seconds")})
    if delete:
        path.unlink(missing_ok=True)
    return provision


def _store(target: Path, provision: Provision, box: SecretBox | None, extra: dict[str, Any]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (box or SecretBox()).write(target / "secrets.bin", json.dumps(provision.secrets))
    record = {"format": FORMAT, "name": provision.name, **extra, "settings": provision.settings,
              "secret_keys": sorted(provision.secrets)}
    pending = target / "settings.json.tmp"
    pending.write_text(json.dumps(record, indent=2), encoding="utf-8")
    pending.replace(target / "settings.json")


def update_local(data_dir: Path, changes: dict[str, str | None], box: SecretBox | None = None) -> Provision:
    """Apply settings-pane changes to this PC's store: a value sets the key, None or "" removes it (the company value or
    the default applies again). Returns the new store."""
    current = load(data_dir, box, "local") or Provision("", {}, {})
    settings, secrets = dict(current.settings), dict(current.secrets)
    for key, value in changes.items():
        if not KEY.match(key) or key in LOCAL_ONLY:
            raise ProvisionError(f"{key} cannot be set here")
        text = (value or "").strip()
        if "\n" in text or "\r" in text:
            raise ProvisionError(f"{key} must be a one-line value")
        target = secrets if is_secret(key) else settings
        if text:
            target[key] = text
        else:
            target.pop(key, None)
    updated = Provision("this PC", settings, secrets)
    _store(folder(data_dir, "local"), updated, box, {"updated_at": datetime.now(UTC).isoformat(timespec="seconds")})
    return updated


def load(data_dir: Path, box: SecretBox | None = None, layer: str = "provision") -> Provision | None:
    """The imported provisioning (or, with layer="local", the settings pane's store), or None. A secret that cannot be
    decrypted (the data folder was copied from another PC or account) is left out, so it reads as missing, not wrong."""
    target = folder(data_dir, layer)
    try:
        record = json.loads((target / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    settings = {k: v for k, v in record.get("settings", {}).items() if isinstance(v, str) and KEY.match(k) and k not in LOCAL_ONLY}
    secrets: dict[str, str] = {}
    stored = (box or SecretBox()).read(target / "secrets.bin")
    if stored:
        try:
            decoded = json.loads(stored)
            secrets = {k: v for k, v in decoded.items() if isinstance(v, str) and KEY.match(k) and is_secret(k)}
        except ValueError:
            secrets = {}
    return Provision(name=str(record.get("name", "")), settings=settings, secrets=secrets)


def status(data_dir: Path, box: SecretBox | None = None) -> dict[str, Any]:
    """What was provisioned, for readiness views: names only, never a value."""
    target = folder(data_dir)
    try:
        record = json.loads((target / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"imported": False}
    loaded = load(data_dir, box)
    missing = sorted(set(record.get("secret_keys", [])) - set(loaded.secrets if loaded else {}))
    return {"imported": True, "name": record.get("name", ""), "imported_at": record.get("imported_at"),
            "settings": sorted(record.get("settings", {})), "secrets": sorted(record.get("secret_keys", [])),
            "unreadable_secrets": missing}

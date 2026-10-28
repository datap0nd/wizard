"""Access requests in a portal's information catalog (the Big Data Portal): the answers a person gives on every request
(purpose, manager, duration...), kept on this PC for them only, and what Wizard fills when it opens the request form.

Owner decision (28 October 2026, docs/decisions/2026-10-28-bdp-access-requests.md): Wizard opens the catalog's request
page in a visible window of the person's Wizard browser and fills their saved answers into the form's empty fields; the
person checks every field and submits the request themselves. Wizard never clicks a button, presses a key or submits a
form (portal_fill.js), and fills only pages of the portals' own hosts and company domains."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .portals import HostPolicy, Portal, PortalSettings

# Portals whose tables are requested in an information catalog.
REQUEST_PORTALS = ("bdp",)
FILE = "access-requests.json"
MAX_FIELDS = 40
MAX_LABEL = 120
MAX_VALUE = 2000
MAX_SEEN = 60
TABLE_LABEL = re.compile(r"table|dataset", re.I)


class AccessFormError(ValueError):
    pass


def _read(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / FILE).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(root: Path, forms: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (FILE + ".tmp")
    temporary.write_text(json.dumps(forms, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(root / FILE)


def request_page(portal: Portal) -> str:
    """Where a request starts when nothing else names a page: the portal's catalog, else its start page."""
    return next((part.url for part in portal.parts if part.id == "catalog"), portal.url)


def form(root: Path, portal: Portal) -> dict[str, Any]:
    """The person's saved form for this portal: {system, page, fields: [{label, value}], seen: [labels], default_page}."""
    saved = _read(root).get(portal.id) or {}
    return {"system": portal.id, "page": str(saved.get("page") or ""),
            "fields": [f for f in saved.get("fields", []) if isinstance(f, dict)][:MAX_FIELDS],
            "seen": [str(s) for s in saved.get("seen", [])][:MAX_SEEN], "default_page": request_page(portal)}


def clean_fields(raw: Any) -> list[dict[str, str]]:
    """[{label, value}] with labels trimmed, unique (ignoring case) and bounded; rows without a label are dropped."""
    if not isinstance(raw, list):
        raise AccessFormError("fields must be a list of {label, value}")
    fields: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AccessFormError("each field is {label, value}")
        label = " ".join(str(item.get("label") or "").split())
        value = str(item.get("value") or "").strip()
        if not label:
            continue
        if len(label) > MAX_LABEL or len(value) > MAX_VALUE:
            raise AccessFormError(f"'{label[:40]}' is too long: labels up to {MAX_LABEL} characters, answers up to {MAX_VALUE}")
        if any(f["label"].casefold() == label.casefold() for f in fields):
            raise AccessFormError(f"'{label}' is there twice")
        fields.append({"label": label, "value": value})
    if len(fields) > MAX_FIELDS:
        raise AccessFormError(f"At most {MAX_FIELDS} fields")
    return fields


def on_portal(portal: Portal, host: str) -> bool:
    """The host is one of this portal's own, or in its company domain: where the request window may open and fill."""
    return bool(host) and HostPolicy(PortalSettings((portal,))).portal_domain(host)


def check_address(portal: Portal, address: str) -> str:
    """An address the request window may open: http(s), on this portal's own hosts or its company domain."""
    address = address.strip()
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise AccessFormError("The request page must be an http(s) address")
    if not on_portal(portal, parts.hostname):
        raise AccessFormError(f"{parts.hostname} is not an address of {portal.name}")
    return address


def save(root: Path, portal: Portal, page: str, fields: Any) -> dict[str, Any]:
    cleaned = clean_fields(fields)
    page = check_address(portal, page) if page.strip() else ""
    forms = _read(root)
    forms[portal.id] = {**(forms.get(portal.id) or {}), "page": page, "fields": cleaned}
    _write(root, forms)
    return form(root, portal)


def remember_seen(root: Path, portal_id: str, labels: list[str]) -> None:
    """Keep the labels Wizard saw on the request form, so the settings can offer them as fields to answer."""
    if not labels:
        return
    forms = _read(root)
    entry = forms.get(portal_id) or {}
    seen = list(dict.fromkeys([*labels, *[str(s) for s in entry.get("seen", [])]]))[:MAX_SEEN]
    forms[portal_id] = {**entry, "seen": seen}
    _write(root, forms)


def answers(saved: list[dict[str, str]], extra: list[dict[str, str]], tables: list[str]) -> list[dict[str, str]]:
    """What the window fills: the saved answers, then this request's own (which replace a saved one of the same label),
    and the tables under 'Table' when no answer names a table field already."""
    merged = {f["label"].casefold(): f for f in saved if f.get("value")}
    for item in extra:
        merged[item["label"].casefold()] = item
    if tables and not any(TABLE_LABEL.search(label) for label in merged):
        merged["table"] = {"label": "Table", "value": ", ".join(tables)}
    return list(merged.values())[:MAX_FIELDS]


def request_id(system: str, address: str, tables: list[str], extra: list[dict[str, str]]) -> str:
    digest = hashlib.sha256(json.dumps([system, address, tables, extra], sort_keys=True).encode("utf-8")).hexdigest()
    return f"AR-{digest[:10]}"

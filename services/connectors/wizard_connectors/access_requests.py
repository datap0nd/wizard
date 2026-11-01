"""Access requests in a portal's information catalog (the Big Data Portal): the answers a person gives on every request
(the purpose, the DPA / DSA box's drop-downs, the subsidiary...), kept on this PC for them only, what Wizard fills when it
opens the request form, and the requests Gemini prepared that wait for the person to send them.

Owner decisions (docs/decisions/2026-10-28-bdp-access-requests.md, docs/decisions/2026-11-01-bdp-dataset-access.md):
Wizard opens the catalog's request page in a visible window of the person's Wizard browser and fills their saved answers
into the form's empty fields, choosing their saved option in a drop-down; the person checks every field and submits the
request themselves. Wizard never presses a key, clicks a button or link, or submits a form (portal_fill.js,
portal_pick.js), and fills only pages of the portals' own hosts and company domains."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .portals import HostPolicy, Portal, PortalSettings, click_refusal

# Portals whose tables are requested in an information catalog.
REQUEST_PORTALS = ("bdp",)
FILE = "access-requests.json"
MAX_FIELDS = 40
MAX_LABEL = 120
MAX_VALUE = 2000
MAX_SEEN = 60
MAX_QUEUE = 100
MAX_PAGES_SEEN = 20
# The steps that reach a table's page in a catalog that shows every table at one address (search, open the result):
# Gemini proves them with portal_run, and the request window follows them in the person's window. Navigation only.
STEP_ACTIONS = ("goto", "click", "fill", "select", "press", "wait")
STEP_TEXT = ("url", "selector", "role", "name", "text", "frame", "value")
MAX_STEPS = 12
STEP_TIMEOUT_MS = 15_000
# Words the control that opens a request form is allowed to carry beside a write word's refusal: it requests access.
OPENER_WORDS = re.compile(r"(?i)\b(request|requests|apply)\b")
TABLE_LABEL = re.compile(r"table|dataset", re.I)
# How a field is answered: typed text (an input or a text box), or an option chosen in a drop-down (a select, or a
# portal's own drop-down, searched by typing the answer when the list has a search box). No kind: either, by label.
KINDS = ("text", "choice")

# The fields every request in a portal's form asks, shown in Settings with an empty answer for the person to set (owner,
# 1 November 2026). Labels are the form's own; a section is the box a field sits in, which tells apart two fields of the
# same label (the free-text Purpose and the DPA / DSA box's Purpose drop-down). The form fills the requester and email.
PRESETS: dict[str, tuple[dict[str, str], ...]] = {
    "bdp": (
        {"label": "Purpose", "kind": "text", "hint": "The form's free-text purpose: what you will use the data for.",
         "example": "Will be used for analytics in the MENA region"},
        {"section": "DPA / DSA", "label": "Purpose", "kind": "choice",
         "hint": "The option as the list shows it, or its number (5 for the fifth).", "example": "5"},
        {"section": "DPA / DSA", "label": "Subsidiary Name (Full Legal Name)", "kind": "choice",
         "hint": "Your subsidiary as the list shows it, or its code: Wizard types it into the list's search and picks "
                 "the match.", "example": "(ABC) Example Electronics Co., Ltd."},
        {"section": "DPA / DSA", "label": "Subsidiary Address", "kind": "text",
         "hint": "The subsidiary's full legal address.", "example": "Building, street, city, country"},
    ),
}


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


def _words(value: Any) -> str:
    return " ".join(str(value or "").split())


def key(field: dict[str, Any]) -> tuple[str, str]:
    """A field is its section and label, ignoring case: the free-text Purpose and DPA / DSA's Purpose are two fields."""
    return _words(field.get("section")).casefold(), _words(field.get("label")).casefold()


def name(field: dict[str, Any]) -> str:
    """How a field is named to the person: "DPA / DSA › Purpose", or its label alone."""
    section, label = _words(field.get("section")), _words(field.get("label"))
    return f"{section} › {label}" if section else label


def _answer(field: dict[str, Any]) -> dict[str, str]:
    """A field as it is kept and filled: label, value, and its section and kind when it has them."""
    out = {"label": _words(field.get("label")), "value": str(field.get("value") or "").strip()}
    if _words(field.get("section")):
        out["section"] = _words(field.get("section"))
    if field.get("kind") in KINDS:
        out["kind"] = str(field["kind"])
    return out


def request_page(portal: Portal) -> str:
    """Where a request starts when nothing else names a page: the portal's catalog, else its start page."""
    return next((part.url for part in portal.parts if part.id == "catalog"), portal.url)


def form(root: Path, portal: Portal) -> dict[str, Any]:
    """The person's saved form for this portal: {system, page, fields, seen, default_page, queue}. fields are the
    portal's predefined ones first (preset, with a hint and an example; the person's answer or ''), then the person's
    own; each is {label, value, section?, kind?}."""
    saved = _read(root).get(portal.id) or {}
    own = [_answer(f) for f in saved.get("fields", []) if isinstance(f, dict) and _words(f.get("label"))][:MAX_FIELDS]
    by_key = {key(f): f for f in own}
    fields: list[dict[str, Any]] = []
    for preset in PRESETS.get(portal.id, ()):
        answer = by_key.pop(key(preset), None)
        fields.append({**_answer({**preset, "value": (answer or {}).get("value", "")}), "preset": True,
                       "hint": preset["hint"], "example": preset.get("example", "")})
    fields += [f for f in own if key(f) in by_key]
    return {"system": portal.id, "page": str(saved.get("page") or ""), "fields": fields,
            "seen": [str(s) for s in saved.get("seen", [])][:MAX_SEEN], "default_page": request_page(portal),
            "queue": queue(root, portal.id)}


def clean_fields(raw: Any) -> list[dict[str, str]]:
    """[{label, value, section?, kind?}] trimmed, unique by section and label (ignoring case) and bounded; rows without
    a label are dropped."""
    if not isinstance(raw, list):
        raise AccessFormError("fields must be a list of {label, value}")
    fields: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AccessFormError("each field is {label, value}")
        if item.get("kind") not in (None, "", *KINDS):
            raise AccessFormError(f"A field is typed text or chosen in a drop-down, not '{str(item.get('kind'))[:20]}'")
        field = _answer(item)
        if not field["label"]:
            continue
        if len(field["label"]) > MAX_LABEL or len(field.get("section", "")) > MAX_LABEL or len(field["value"]) > MAX_VALUE:
            raise AccessFormError(f"'{field['label'][:40]}' is too long: labels up to {MAX_LABEL} characters, answers "
                                  f"up to {MAX_VALUE}")
        if any(key(f) == key(field) for f in fields):
            raise AccessFormError(f"'{name(field)}' is there twice")
        fields.append(field)
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


def answers(saved: list[dict[str, Any]], extra: list[dict[str, str]], tables: list[str]) -> list[dict[str, str]]:
    """What the window fills: the saved answers, then this request's own (which replace a saved one of the same section
    and label, keeping its kind), and the tables under 'Table' when no answer names a table field already."""
    merged = {key(f): _answer(f) for f in saved if str(f.get("value") or "").strip()}
    for item in extra:
        merged[key(item)] = {**merged.get(key(item), {}), **_answer(item)}
    if tables and not any(TABLE_LABEL.search(label) for _, label in merged):
        merged[("", "table")] = {"label": "Table", "value": ", ".join(tables)}
    return list(merged.values())[:MAX_FIELDS]


def request_id(system: str, address: str, tables: list[str], extra: list[dict[str, str]],
               route: dict[str, Any] | None = None) -> str:
    payload: list[Any] = [system, address, tables, extra]
    if route and (route.get("open_steps") or route.get("form_button")):
        payload.append({"open_steps": route.get("open_steps") or [], "form_button": route.get("form_button") or ""})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"AR-{digest[:10]}"


def clean_steps(raw: Any) -> list[dict[str, Any]]:
    """The steps from a request's page to the table's own page: goto, click, fill, select, press (Enter only) and wait,
    each naming its element the way portal_run does. At most 12; nothing that runs a script or sends a request."""
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_STEPS:
        raise AccessFormError(f"open_steps is a list of at most {MAX_STEPS} steps")
    steps: list[dict[str, Any]] = []
    for number, item in enumerate(raw, 1):
        action = item.get("action") if isinstance(item, dict) else None
        if action not in STEP_ACTIONS:
            raise AccessFormError(f"Step {number}: open_steps only go to the table's page ({', '.join(STEP_ACTIONS)})")
        step: dict[str, Any] = {"action": action}
        for name in STEP_TEXT:
            value = item.get(name)
            if value not in (None, ""):
                step[name] = str(value)[:2000 if name == "url" else 500]
        if item.get("nth") not in (None, ""):
            step["nth"] = max(0, min(int(item["nth"]), 50))
        if item.get("timeout_ms") not in (None, ""):
            step["timeout_ms"] = max(500, min(int(item["timeout_ms"]), STEP_TIMEOUT_MS))
        targeted = any(step.get(k) for k in ("selector", "role", "text"))
        if action in ("click", "fill", "select") and not targeted:
            raise AccessFormError(f"Step {number} ({action}): name the element with selector, role (+ name) or text")
        if action == "goto" and not step.get("url"):
            raise AccessFormError(f"Step {number} (goto): give the url")
        if action == "press" and step.get("value", "Enter") != "Enter":
            raise AccessFormError(f"Step {number} (press): only Enter, to run a search")
        steps.append(step)
    return steps


def clean_button(text: Any) -> str:
    """The text of the control on the table's page that opens the request form (e.g. Request access). It may request
    access; it may not save, send, submit or confirm anything."""
    label = _words(text)[:80]
    if label:
        refusal = click_refusal({"text": OPENER_WORDS.sub(" ", label)})
        if refusal:
            raise AccessFormError(f"'{label}' is not a control that opens a request form: {refusal}")
    return label


def start_page(portal: Portal, address: str) -> bool:
    """The address is a start page of the portal (the catalog's, or one of its applications'), not a table's page."""
    def norm(url: str) -> str:
        parts = urlsplit(url.strip())
        return f"{(parts.hostname or '').lower()}{parts.path.rstrip('/')}?{parts.query}#{parts.fragment.strip('/')}"
    return norm(address) in {norm(u) for u in [portal.url, *[part.url for part in portal.parts]]}


# Prepared requests: what Gemini proposed, waiting for the person to open and send ----------------------------------------
def queue(root: Path, portal_id: str) -> list[dict[str, Any]]:
    """The requests Gemini prepared for this portal, oldest first: {id, address, tables, answers, added, opened}."""
    items = (_read(root).get(portal_id) or {}).get("queue", [])
    return [i for i in items if isinstance(i, dict) and i.get("id") and i.get("address")][:MAX_QUEUE]


def enqueue(root: Path, portal_id: str, request: dict[str, Any]) -> dict[str, int]:
    """Add a prepared request (once: the same request again keeps its place). One prepared again for the same tables,
    not opened yet, replaces the earlier one in its place (a better route to the table). When the list is full the
    oldest opened ones make room; a list full of unopened ones refuses. Returns its position and how many wait."""
    forms = _read(root)
    entry = forms.get(portal_id) or {}
    items = queue(root, portal_id)
    if not any(i["id"] == request["id"] for i in items):
        tables = sorted(request.get("tables") or [])
        fresh = {"id": request["id"], "address": request["address"], "tables": list(request.get("tables") or []),
                 "answers": list(request.get("answers") or []), "added": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "opened": None,
                 **({"open_steps": request["open_steps"]} if request.get("open_steps") else {}),
                 **({"form_button": request["form_button"]} if request.get("form_button") else {})}
        same = next((i for i in items if tables and not i.get("opened") and sorted(i.get("tables") or []) == tables), None)
        if same is not None:
            items[items.index(same)] = {**fresh, "added": same.get("added") or fresh["added"]}
        else:
            while len(items) >= MAX_QUEUE and any(i.get("opened") for i in items):
                items.remove(next(i for i in items if i.get("opened")))
            if len(items) >= MAX_QUEUE:
                raise AccessFormError(f"{MAX_QUEUE} prepared requests are waiting: the person opens or removes some "
                                      "in Settings → Portals first.")
            items.append(fresh)
        forms[portal_id] = {**entry, "queue": items}
        _write(root, forms)
    position = next(n for n, i in enumerate(items, 1) if i["id"] == request["id"])
    return {"position": position, "waiting": sum(1 for i in items if not i.get("opened"))}


def mark_opened(root: Path, portal_id: str, request_id_: str) -> dict[str, Any] | None:
    """The person opened a prepared request (from the list, its card or the window's Next): note when."""
    forms = _read(root)
    entry = forms.get(portal_id) or {}
    items = queue(root, portal_id)
    found = next((i for i in items if i["id"] == request_id_), None)
    if found is not None:
        found["opened"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        forms[portal_id] = {**entry, "queue": items}
        _write(root, forms)
    return found


def next_waiting(root: Path, portal_id: str, after: str | None = None) -> dict[str, Any] | None:
    """The first prepared request not opened yet (after the one named, when it is in the list)."""
    items = queue(root, portal_id)
    start = next((n + 1 for n, i in enumerate(items) if i["id"] == after), 0) if after else 0
    return next((i for i in [*items[start:], *items[:start]] if not i.get("opened") and i["id"] != after), None)


def place(root: Path, portal_id: str, request_id_: str | None) -> dict[str, int] | None:
    """Where a prepared request sits in the list, for the window's note: {position, total, waiting}, waiting being the
    others not opened yet (the ones Next request still has to show)."""
    items = queue(root, portal_id)
    position = next((n for n, i in enumerate(items, 1) if i["id"] == request_id_), None)
    if position is None:
        return None
    return {"position": position, "total": len(items),
            "waiting": sum(1 for i in items if not i.get("opened") and i["id"] != request_id_)}


def remove(root: Path, portal_id: str, ids: list[str], opened: bool = False) -> list[dict[str, Any]]:
    """Take prepared requests off the list: the ones named, and every opened one when asked."""
    forms = _read(root)
    entry = forms.get(portal_id) or {}
    items = [i for i in queue(root, portal_id) if i["id"] not in ids and not (opened and i.get("opened"))]
    forms[portal_id] = {**entry, "queue": items}
    _write(root, forms)
    return items


def search_texts(value: str) -> list[str]:
    """What Wizard types into a drop-down's search box to find the saved option, in turn: the answer, the code in its
    brackets ("(ABC) Example Co." → ABC), and its first word. A number alone (the fifth option) is never typed."""
    value = " ".join(value.split())
    if not value or re.fullmatch(r"\d{1,3}", value):
        return []
    found = [value]
    inner = re.search(r"\(([^()]{2,40})\)", value)
    if inner:
        found.append(inner.group(1).strip())
    words = re.sub(r"\([^()]*\)", " ", value).split()
    if words:
        found.append(words[0].strip(".,;:"))
    return [t for t in dict.fromkeys(found) if len(t) >= 2][:3]


def remember_page(root: Path, portal_id: str, tables: list[str], url: str) -> None:
    """Where a request form appeared for these tables, so Gemini learns the catalog's addresses (form_pages_seen)."""
    forms = _read(root)
    entry = forms.get(portal_id) or {}
    pages = [p for p in entry.get("pages", []) if isinstance(p, dict) and p.get("url") != url]
    pages.insert(0, {"tables": tables[:20], "url": url[:2000], "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    forms[portal_id] = {**entry, "pages": pages[:MAX_PAGES_SEEN]}
    _write(root, forms)


def pages_seen(root: Path, portal_id: str) -> list[dict[str, Any]]:
    return [p for p in ((_read(root).get(portal_id) or {}).get("pages") or []) if isinstance(p, dict)][:MAX_PAGES_SEEN]

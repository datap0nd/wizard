"""Wizard's calls to Metronome: who Wizard's key is signed in as, creating a recurring brief the person confirmed, the
Recurring tab's status of each Flow, and turning a Flow off when the person deletes the brief.

Only a person's action (Create in Metronome, the Recurring tab, Delete) and Settings' Test connection reach this module;
no tool does. Wizard never deletes a Flow: Delete turns it off, and Metronome keeps it and its run history.
Metronome has no API tokens: it knows a caller by the client key in X-Client-Key, bound to a person in its Users. Before
every create Wizard checks that its key is signed in as the configured Wizard user and names that person as the Flow's
owner, so a Flow never belongs to the person who asked. Metronome is on the office network and is reached directly,
never through the proxy Wizard uses for Google."""
from __future__ import annotations

from typing import Any

import httpx

from wizard_agent import outbound
from wizard_connectors import metronome
from wizard_connectors.metronome import MetronomeSettings

LINK_HINT = ("On the Metronome host PC, run scripts/metronome_link.py to sign a key in as the Wizard user, and put that key "
             "in WIZARD_METRONOME_CLIENT_KEY.")


class MetronomeError(Exception):
    """`uncertain`: Metronome may have created the Flow although it did not confirm it, so it must not be sent again."""

    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.message = message
        self.uncertain = uncertain


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # FastAPI's validation errors
        detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail[:4])
    return str(detail or response.reason_phrase or "no reason given")[:500]


class MetronomeClient:
    def __init__(self, settings: MetronomeSettings, transport: httpx.BaseTransport | None = None, timeout: float = 30):
        self.settings, self.transport, self.timeout = settings, transport, timeout

    def _client(self) -> httpx.Client:
        headers = {"X-Client-Key": self.settings.client_key, "Accept": "application/json", "User-Agent": "Wizard"}
        if self.transport is not None:
            return httpx.Client(base_url=self.settings.url, headers=headers, transport=self.transport, timeout=self.timeout)
        return httpx.Client(base_url=self.settings.url, headers=headers, timeout=self.timeout, trust_env=False,
                            verify=outbound.ssl_context(), follow_redirects=False)

    def _get(self, client: httpx.Client, path: str) -> Any:
        try:
            response = client.get(path)
        except httpx.HTTPError as error:
            raise MetronomeError(f"Metronome is not reachable at {self.settings.url}: {error}") from None
        if response.status_code >= 400:
            raise MetronomeError(f"Metronome answered {response.status_code} to {path}: {_detail(response)}")
        return response.json()

    def whoami(self, client: httpx.Client) -> dict[str, Any]:
        """The Metronome person Wizard's key is signed in as; MetronomeError unless it is the configured Wizard user."""
        me = self._get(client, "/api/me")
        if not isinstance(me, dict) or not me.get("person_id"):
            raise MetronomeError(f"Wizard's key is not signed in to Metronome. {LINK_HINT}")
        if str(me.get("name", "")).strip().casefold() != self.settings.user.casefold():
            raise MetronomeError(f"Wizard's key is signed in to Metronome as {me.get('name')}, not {self.settings.user}. "
                                 f"Flows must belong to {self.settings.user}: {LINK_HINT}")
        return me

    def check(self) -> dict[str, Any]:
        """Settings' Test connection."""
        try:
            with self._client() as client:
                me = self.whoami(client)
        except MetronomeError as error:
            return {"ok": False, "message": error.message}
        return {"ok": True, "message": f"Connected to Metronome at {self.settings.url} as {me['name']} (user "
                                       f"{me['person_id']}). Recurring extractions Wizard creates belong to "
                                       f"{me['name']}."}

    def create(self, schedule: dict[str, Any]) -> dict[str, Any]:
        """Upload the extraction script and create the active Flow, owned by the Wizard user. Returns the Flow."""
        with self._client() as client:
            me = self.whoami(client)
            script = metronome.brief_script(schedule).encode("utf-8")
            try:
                uploaded = client.post("/api/flows/transform-script", params={"target": "python"},
                                       files={"file": (metronome.script_filename(schedule), script, "text/x-python")})
            except httpx.HTTPError as error:
                raise MetronomeError(f"Metronome is not reachable at {self.settings.url}: {error}") from None
            if uploaded.status_code >= 400:
                raise MetronomeError(f"Metronome refused the extraction script ({uploaded.status_code}): "
                                     f"{_detail(uploaded)}")
            script_path = uploaded.json().get("script_path")
            if not script_path:
                raise MetronomeError("Metronome did not say where it saved the extraction script.")
            definition = metronome.flow_definition(schedule, str(script_path), int(me["person_id"]))
            try:
                response = client.post("/api/flows", json=definition)
            except httpx.HTTPError as error:
                raise MetronomeError(f"Metronome did not answer ({error}). The Flow “{definition['name']}” may have been "
                                     "created: look for it in Metronome's Flows before asking again.",
                                     uncertain=True) from None
        if response.status_code >= 500:
            raise MetronomeError(f"Metronome failed ({response.status_code}: {_detail(response)}). The Flow "
                                 f"“{definition['name']}” may have been created: look for it in Metronome's Flows before "
                                 "asking again.", uncertain=True)
        if response.status_code >= 400:
            raise MetronomeError(f"Metronome refused the Flow ({response.status_code}): {_detail(response)}")
        flow = response.json()
        return {"id": flow.get("id"), "name": flow.get("name") or definition["name"],
                "owner": flow.get("owner_name") or me["name"], "enabled": flow.get("enabled"),
                "next_run_at": utc(flow.get("next_run_at")), "url": f"{self.settings.url}/"}

    def status(self, flow_ids: list[int], runs: int = 5) -> dict[int, dict[str, Any]]:
        """The Recurring tab's view of each Flow: on or off, the next and last run, and its latest runs with their
        email. A Flow Metronome no longer has reads {"missing": True}."""
        found: dict[int, dict[str, Any]] = {}
        with self._client() as client:
            for flow_id in flow_ids:
                try:
                    response = client.get(f"/api/flows/{int(flow_id)}")
                except httpx.HTTPError as error:
                    raise MetronomeError(f"Metronome is not reachable at {self.settings.url}: {error}") from None
                if response.status_code == 404:
                    found[flow_id] = {"missing": True}
                    continue
                if response.status_code >= 400:
                    raise MetronomeError(f"Metronome answered {response.status_code} for Flow {flow_id}: "
                                         f"{_detail(response)}")
                flow = response.json()
                listed = self._get(client, f"/api/flows/runs?flow_id={int(flow_id)}&limit={int(runs)}")
                found[flow_id] = {
                    "missing": False, "name": flow.get("name"), "enabled": bool(flow.get("enabled")),
                    "owner": flow.get("owner_name"), "next_run_at": utc(flow.get("next_run_at")),
                    "last_run_at": utc(flow.get("last_run_at")), "last_status": flow.get("last_status"),
                    "last_error": _short(flow.get("last_error")),
                    "runs": [{"id": run.get("id"), "status": run.get("status"), "trigger": run.get("trigger_type"),
                              "at": utc(run.get("finished_at") or run.get("started_at") or run.get("created_at")),
                              "error": _short(run.get("error")),
                              "email": (run.get("email") or {}).get("status") if isinstance(run.get("email"), dict)
                              else None}
                             for run in listed if isinstance(run, dict)] if isinstance(listed, list) else [],
                }
        return found

    def deactivate(self, flow_id: int) -> dict[str, Any]:
        """Turn the Flow off in Metronome, as the Wizard user that owns it; Metronome keeps the Flow and its history.
        A Flow Metronome no longer has is already gone: {"missing": True}."""
        with self._client() as client:
            self.whoami(client)
            try:
                response = client.patch(f"/api/flows/{int(flow_id)}/enabled", json={"enabled": False})
            except httpx.HTTPError as error:
                raise MetronomeError(f"Metronome is not reachable at {self.settings.url}: {error}") from None
        if response.status_code == 404:
            return {"missing": True, "enabled": False}
        if response.status_code >= 400:
            raise MetronomeError(f"Metronome refused to turn the Flow off ({response.status_code}): {_detail(response)}")
        return {"missing": False, "enabled": bool(response.json().get("enabled"))}


def utc(value: Any) -> str | None:
    """Metronome stores and returns naive UTC; the page needs the zone."""
    if not isinstance(value, str) or not value:
        return None
    return value if value.endswith("Z") or "+" in value[10:] else value + "Z"


def _short(value: Any) -> str | None:
    return str(value)[:300] if value else None

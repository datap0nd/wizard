"""Wizard's calls to Metronome: who Wizard's key is signed in as, and creating a recurring extraction the person confirmed.

Only a person's click (POST /api/v1/schedules/{id}/create) and Settings' Test connection reach this module; no tool does.
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
            script = metronome.extraction_script(schedule).encode("utf-8")
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
        next_run = flow.get("next_run_at")
        if isinstance(next_run, str) and next_run and not next_run.endswith("Z") and "+" not in next_run[10:]:
            next_run += "Z"  # Metronome stores and returns naive UTC
        return {"id": flow.get("id"), "name": flow.get("name") or definition["name"],
                "owner": flow.get("owner_name") or me["name"], "enabled": flow.get("enabled"),
                "next_run_at": next_run, "url": f"{self.settings.url}/"}

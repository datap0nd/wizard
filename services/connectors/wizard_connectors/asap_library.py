"""ASAP (MicroStrategy / Strategy Library REST) client and row normaliser - groundwork for Step 09, NOT validated.

Status: written against the published Strategy REST shapes (session auth, folder browse, v2 report instances with
prompts, paged grid results). It has only been exercised with recorded-shape fakes in tests. Until IT confirms the
tenant-supported login route and one owner-approved report passes same-user, same-filter parity, ASAP stays
NAVIGATION_ONLY in Wizard and no ASAP number is labelled LIVE_VERIFIED.

Deliberately absent: copied browser cookies, TLS verification bypass, arbitrary /mstr event URLs, password handling in
Wizard, and any write endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

AUTH_HEADER = "X-MSTR-AuthToken"
PROJECT_HEADER = "X-MSTR-ProjectID"


class AsapError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Grid:
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int


class LibraryClient:
    def __init__(self, base_url: str, project_id: str, *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 60.0, verify: bool | str = True):
        if not base_url.startswith("https://") and transport is None:
            raise AsapError("insecure_url", "ASAP Library must be reached over HTTPS.")
        self.project_id = project_id
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/api", timeout=timeout, verify=verify,
                                 transport=transport, trust_env=True)
        self.token: str | None = None

    # Session ---------------------------------------------------------------------------------------------------------
    def login_delegated(self, identity_token: str) -> None:
        """Exchange an identity token issued by the approved SSO/trusted-auth route for a Library session."""
        response = self.http.post("/auth/delegate", json={"loginMode": -1, "identityToken": identity_token})
        self._raise(response, "login")
        self.token = response.headers.get(AUTH_HEADER)
        if not self.token:
            raise AsapError("login_failed", "ASAP did not return a session token.")

    def logout(self) -> None:
        if self.token:
            self.http.post("/auth/logout", headers=self._headers())
            self.token = None

    # Navigation ------------------------------------------------------------------------------------------------------
    def folder(self, folder_id: str) -> list[dict[str, Any]]:
        response = self.http.get(f"/folders/{folder_id}", headers=self._headers(project=True))
        self._raise(response, "folder")
        return [{"id": item.get("id"), "name": item.get("name"), "type": item.get("type"), "subtype": item.get("subtype")}
                for item in response.json()]

    def report_definition(self, report_id: str) -> dict[str, Any]:
        response = self.http.get(f"/v2/reports/{report_id}", headers=self._headers(project=True))
        self._raise(response, "definition")
        return response.json()

    # Rows ------------------------------------------------------------------------------------------------------------
    def open_instance(self, report_id: str, limit: int) -> dict[str, Any]:
        response = self.http.post(f"/v2/reports/{report_id}/instances", params={"limit": limit},
                                  headers=self._headers(project=True))
        self._raise(response, "instance")
        return response.json()

    def prompts(self, report_id: str, instance_id: str) -> list[dict[str, Any]]:
        response = self.http.get(f"/reports/{report_id}/instances/{instance_id}/prompts", headers=self._headers(project=True))
        self._raise(response, "prompts")
        return list(response.json())

    def answer_prompts(self, report_id: str, instance_id: str, answers: list[dict[str, Any]]) -> None:
        response = self.http.put(f"/reports/{report_id}/instances/{instance_id}/prompts/answers",
                                 json={"prompts": answers}, headers=self._headers(project=True))
        self._raise(response, "prompt_answers")

    def page(self, report_id: str, instance_id: str, offset: int, limit: int) -> dict[str, Any]:
        response = self.http.get(f"/v2/reports/{report_id}/instances/{instance_id}", params={"offset": offset, "limit": limit},
                                 headers=self._headers(project=True))
        self._raise(response, "rows")
        return response.json()

    def read_rows(self, report_id: str, answers: list[dict[str, Any]], *, max_rows: int = 500, page_size: int = 200) -> Grid:
        first = self.open_instance(report_id, page_size)
        instance_id = first.get("instanceId") or first.get("mid")
        if not instance_id:
            raise AsapError("no_instance", "ASAP did not return a report instance.")
        if first.get("status") == 2 or answers:  # 2 = prompted
            self.answer_prompts(report_id, instance_id, answers)
            first = self.page(report_id, instance_id, 0, page_size)
        grid = normalise_grid(first)
        total = grid.total_rows
        while len(grid.rows) < min(total, max_rows):
            more = normalise_grid(self.page(report_id, instance_id, len(grid.rows), page_size))
            if not more.rows:
                break
            grid.rows.extend(more.rows)
        grid.rows = grid.rows[:max_rows]
        return grid

    # Helpers ---------------------------------------------------------------------------------------------------------
    def _headers(self, project: bool = False) -> dict[str, str]:
        if not self.token:
            raise AsapError("not_signed_in", "No ASAP session.")
        headers = {AUTH_HEADER: self.token}
        if project:
            headers[PROJECT_HEADER] = self.project_id
        return headers

    @staticmethod
    def _raise(response: httpx.Response, step: str) -> None:
        if response.status_code in (401, 403):
            raise AsapError("not_permitted", "ASAP refused the request for this user.", response.status_code)
        if response.status_code == 404:
            raise AsapError("not_found", "The ASAP object was not found or is not visible to this user.", 404)
        if response.status_code >= 400:
            raise AsapError(f"{step}_failed", f"ASAP {step} request failed ({response.status_code}).", response.status_code)


def normalise_grid(payload: dict[str, Any]) -> Grid:
    """Flatten a v2 report result (attribute row headers + metric columns) into named columns and value rows."""
    definition = payload.get("definition", {}).get("grid", {})
    data = payload.get("data", {})
    row_attributes = definition.get("rows", [])
    metric_header = next((c for c in definition.get("columns", []) if c.get("type") in (None, "templateMetrics")), None)
    metrics = [m.get("name") for m in (metric_header or {}).get("elements", [])]
    columns = [a.get("name") for a in row_attributes] + metrics
    headers = data.get("headers", {}).get("rows", [])
    raw = data.get("metricValues", {}).get("raw", [])
    rows = []
    for index, header in enumerate(headers):
        labels = []
        for position, element_index in enumerate(header):
            elements = row_attributes[position].get("elements", [])
            element = elements[element_index] if element_index < len(elements) else {}
            labels.append((element.get("formValues") or [element.get("name")])[0])
        values = raw[index] if index < len(raw) else [None] * len(metrics)
        rows.append([*labels, *values])
    total = data.get("paging", {}).get("total", len(rows))
    return Grid(columns=columns, rows=rows, total_rows=total)

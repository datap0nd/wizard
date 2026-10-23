"""Typed source contracts: systems, folders, reports, columns and prompts.

The contract is what a source owner approves (Step 04): it limits which fields an adapter can expose. Connector status,
row access and data mode are separate fields, so browsing a report is never confused with reading verified rows."""
from __future__ import annotations

import copy
import json
import logging
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ColumnType = Literal["string", "text", "integer", "number", "percent", "currency", "month", "quarter"]
Aggregation = Literal["sum", "sum_same_currency", "last", "none"]
DataMode = Literal["SYNTHETIC", "DATED_APPROVED_SNAPSHOT", "LIVE_VERIFIED"]
ConnectorStatus = Literal["SYNTHETIC_FIXTURE", "NAVIGATION_ONLY", "ROWS_VERIFIED", "BLOCKED"]
RowAccess = Literal["ROWS", "NAVIGATION_ONLY"]
READABLE = ("ROWS_VERIFIED", "SYNTHETIC_FIXTURE")  # statuses only a parity-tested adapter (or the fixtures) may carry

log = logging.getLogger("wizard.catalog")


def navigation_only(data: Any) -> Any:
    """A report catalog from real content with every claim of readable rows taken back: its connector and reports become
    navigation only and no report points at a data file. Real content describes reports; it cannot make one readable."""
    if not isinstance(data, dict):
        return data
    data = copy.deepcopy(data)
    connector = (data.get("system") or {}).get("connector")
    if isinstance(connector, dict) and connector.get("status") in READABLE:
        connector["status"] = "NAVIGATION_ONLY"
    for report in data.get("reports") or []:
        if isinstance(report, dict):
            if report.get("row_access") == "ROWS":
                report["row_access"] = "NAVIGATION_ONLY"
            if "file" in report:
                report["file"] = None
    return data


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Dimension(Strict):
    key: str
    label: str
    type: ColumnType
    role: Literal["market", "period", "model"] | None = None
    values_hint: list[str] = Field(default_factory=list)


class Measure(Strict):
    key: str
    label: str
    type: ColumnType
    unit: str | None = None
    aggregation: Aggregation


class Attribute(Strict):
    key: str
    label: str
    type: ColumnType


class Prompt(Strict):
    key: str
    label: str
    multi: bool = True


class Connector(Strict):
    status: ConnectorStatus
    data_mode: DataMode
    transport: str
    live_interface: str


class SystemInfo(Strict):
    id: str
    name: str
    description: str
    families: list[str]
    owner: str
    connector: Connector
    open_url_template: str | None


class Folder(Strict):
    id: str
    name: str
    parent: str | None


class Report(Strict):
    id: str
    name: str
    folder: str
    type: Literal["report", "dossier"]
    row_access: RowAccess
    file: str | None
    description: str
    grain: list[str]
    as_of: str | None
    refresh: str
    dimensions: list[Dimension]
    measures: list[Measure]
    attributes: list[Attribute]
    prompts: list[Prompt]
    caveats: list[str]
    sensitivity: Literal["internal", "restricted"]

    def column(self, key: str) -> Dimension | Measure | Attribute | None:
        columns: list[Dimension | Measure | Attribute] = [*self.dimensions, *self.measures, *self.attributes]
        for column in columns:
            if column.key == key:
                return column
        return None

    @property
    def dimension_keys(self) -> list[str]:
        return [d.key for d in self.dimensions]

    @property
    def measure_keys(self) -> list[str]:
        return [m.key for m in self.measures]


class SourceContract(Strict):
    contract_version: int
    system: SystemInfo
    folders: list[Folder]
    reports: list[Report]


class Catalog:
    """All approved source contracts. Search and lookups never apply rights; callers filter by entitlement first."""

    def __init__(self, contracts: list[SourceContract]):
        self.contracts = {c.system.id: c for c in contracts}

    @classmethod
    def load(cls, directory: Path, real: bool = False, skip: frozenset[str] = frozenset()) -> Catalog:
        """Every report catalog in `directory`. Real content (a knowledge base or content folder) can only describe
        reports: whatever it claims, its systems and reports load as navigation only, and a file that cannot be read is
        skipped with a warning instead of stopping Wizard."""
        contracts = []
        for path in sorted(directory.glob("*.json")):
            if path.name in skip:
                log.warning("report catalog %s left out: it has errors (see the content warnings)", path.name)
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                contracts.append(SourceContract.model_validate(navigation_only(data) if real else data))
            except (ValueError, OSError) as error:
                if not real:
                    raise
                log.warning("report catalog %s skipped: %s", path.name, str(error).splitlines()[0][:300])
        return cls(contracts)

    @property
    def systems(self) -> list[SystemInfo]:
        return [c.system for c in self.contracts.values()]

    @cached_property
    def _reports(self) -> dict[str, tuple[str, Report]]:
        return {r.id: (system_id, r) for system_id, c in self.contracts.items() for r in c.reports}

    def report(self, report_id: str) -> tuple[str, Report] | None:
        return self._reports.get(report_id)

    def reports(self, system_id: str | None = None) -> list[tuple[str, Report]]:
        return [(s, r) for s, r in self._reports.values() if system_id in (None, s)]

    def folder_path(self, system_id: str, folder_id: str) -> list[str]:
        folders = {f.id: f for f in self.contracts[system_id].folders}
        path: list[str] = []
        current = folders.get(folder_id)
        while current is not None:
            path.insert(0, current.name)
            current = folders.get(current.parent) if current.parent else None
        return path

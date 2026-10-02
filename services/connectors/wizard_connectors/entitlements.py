"""Who may see which system, report and market. Checked on search, schema, run, drill-down and report reopen.

In Release A rights come from fixtures/identities.json. In a connected release the same interface is backed by source-side
entitlement checks (per-user delegation or a constrained service identity with checked per-user rights, Step 02)."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SystemRights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reports: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    email: str
    name: str
    role: str
    entitlements: dict[str, SystemRights] = Field(default_factory=dict)

    def can_use_system(self, system_id: str) -> bool:
        rights = self.entitlements.get(system_id)
        return bool(rights and rights.reports)

    def can_see_report(self, system_id: str, report_id: str) -> bool:
        rights = self.entitlements.get(system_id)
        return bool(rights) and any(fnmatch.fnmatchcase(report_id, pattern) for pattern in rights.reports)  # type: ignore[union-attr]

    def allowed_markets(self, system_id: str) -> set[str] | None:
        """None means every market; an empty set means none."""
        rights = self.entitlements.get(system_id)
        if not rights:
            return set()
        return None if "*" in rights.markets else set(rights.markets)


class IdentityDirectory:
    def __init__(self, identities: list[Identity]):
        self.by_id = {i.id: i for i in identities}
        self.by_email = {i.email.lower(): i for i in identities}

    @classmethod
    def load(cls, path: Path) -> IdentityDirectory:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Identity.model_validate(u) for u in data["users"]])

    def get(self, user_id: str) -> Identity | None:
        return self.by_id.get(user_id)

    def by_login(self, email: str) -> Identity | None:
        return self.by_email.get(email.strip().lower())

    def all(self) -> list[Identity]:
        return list(self.by_id.values())

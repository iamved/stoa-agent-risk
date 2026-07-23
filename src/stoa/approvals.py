"""In-repo approval workflow (`.stoa/approvals.toml`, Part III §2.6).

Approvals are code-reviewed artifacts, never ephemeral UI state. Each binds to
``(agent_id, kind, value, evidence_fingerprint)`` — if the call site changes
materially the fingerprint no longer matches and the approval is reported
**stale**, so approvals can't be farmed once and reused for different code.
Nothing is hidden: active, stale, and expired approvals all surface.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

VALID_KINDS = ("capability", "integration", "provider", "new-agent")


@dataclass
class Approval:
    agent_id: str
    agent_name: str
    kind: str
    value: str
    reason: str
    approved_by: str
    evidence_fingerprint: str | None = None
    expires: str | None = None

    def is_expired(self, today: date | None = None) -> bool:
        if not self.expires:
            return False
        try:
            return date.fromisoformat(self.expires) < (today or date.today())
        except ValueError:
            return False


class Approvals:
    """Loaded ``.stoa/approvals.toml``; matches drift entries against records."""

    def __init__(self, records: list[Approval], path: Path):
        self._records = records
        self._path = path
        self._stale: list[dict] = []

    @property
    def path(self) -> Path:
        return self._path

    def path_str(self) -> str:
        return str(self._path)

    @classmethod
    def load(cls, path: Path) -> "Approvals":
        records: list[Approval] = []
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("approval", []):
                records.append(Approval(
                    agent_id=entry.get("agent_id", ""),
                    agent_name=entry.get("agent_name", ""),
                    kind=entry.get("kind", ""),
                    value=entry.get("value", ""),
                    reason=entry.get("reason", ""),
                    approved_by=entry.get("approved_by", ""),
                    evidence_fingerprint=entry.get("evidence_fingerprint"),
                    expires=entry.get("expires"),
                ))
        return cls(records, path)

    def is_approved(self, agent_id: str, kind: str, value: str, evidence_fp: str) -> bool:
        for r in self._records:
            if r.agent_id == agent_id and r.kind == kind and r.value == value:
                if r.is_expired():
                    self._record_stale(r, "expired")
                    return False
                if r.evidence_fingerprint and r.evidence_fingerprint != evidence_fp:
                    self._record_stale(r, "evidence changed")
                    return False
                return True
        return False

    def _record_stale(self, r: Approval, why: str) -> None:
        rec = {"agent_id": r.agent_id, "kind": r.kind, "value": r.value, "reason": why}
        if rec not in self._stale:
            self._stale.append(rec)

    def stale_records(self) -> list[dict]:
        return sorted(self._stale, key=lambda r: (r["agent_id"], r["kind"], r["value"]))

    def records(self) -> list[Approval]:
        return list(self._records)

    def add(self, approval: Approval) -> None:
        self._records.append(approval)

    def write(self) -> None:
        """Serialize deterministically back to the TOML file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# .stoa/approvals.toml — records intentional agent capability changes.",
            "# Each entry is written by `stoa approve` and reviewed like code.",
            "",
        ]
        for r in sorted(self._records, key=lambda a: (a.agent_id, a.kind, a.value)):
            lines.append("[[approval]]")
            lines.append(f'agent_id = "{r.agent_id}"')
            lines.append(f'agent_name = "{r.agent_name}"')
            lines.append(f'kind = "{r.kind}"')
            lines.append(f'value = "{r.value}"')
            lines.append(f'reason = "{_esc(r.reason)}"')
            lines.append(f'approved_by = "{r.approved_by}"')
            if r.evidence_fingerprint:
                lines.append(f'evidence_fingerprint = "{r.evidence_fingerprint}"')
            if r.expires:
                lines.append(f'expires = "{r.expires}"')
            lines.append("")
        self._path.write_text("\n".join(lines), encoding="utf-8")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')

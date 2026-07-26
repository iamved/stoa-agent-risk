"""Declared-metadata layer (``stoa-declared.toml``).

Human-supplied business facts the scanner cannot derive from code — owner,
purpose, intended autonomy, economic limits — captured as structured,
git-reviewed metadata and cross-checked against scan results (see
``contradiction_rules.py``, Phase 4). Mirrors ``approvals.py``'s shape: a
loader class over a TOML file, one dataclass per record kind.

Validation is two-tier. Structurally broken TOML, or a field that's the wrong
*type* (not a table where a table is required, etc.), raises ``ConfigError``
immediately — the file can't be interpreted at all. Semantic issues — an
invalid enum value, a malformed amount, an unknown top-level or per-agent
key — are collected as warning strings instead of raised, so a still-useful
partial declaration loads. The CLI escalates warnings to errors under
``--strict`` (the same flag ``stoa scan --strict`` already uses to mean "stop
tolerating looseness" — not a second, adjacent flag).

Agent identity: declarations key by the scanned agent **id** (the stable
12-hex hash on every ``AgentCandidate``), never a human slug — the same
exact-match precedent as ``Approval.agent_id``. Whether a declared id still
exists in the current scan is a separate, scan-dependent check
(``unknown_agent_ids``), not part of ``load()`` itself, since the loader has
no access to scan results.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from .config import ConfigError

AUTONOMY_INTENTS = (
    "recommend_only", "human_approved", "bounded_autonomous", "unrestricted_autonomous",
)
USERS_VALUES = ("internal", "customers", "public")
PRODUCTION_STATUSES = ("dev", "staging", "production", "deprecated")
DEPENDENCY_LEVELS = ("low", "medium", "high", "critical")
DATA_CLASSES = ("personal", "financial", "health", "confidential", "ip", "authentication")
# AIUC-1 Society category: org-level attestation only, never scored by Stoa —
# a static per-repo scan has no visibility into deployment-scale societal harm.
SOCIETAL_RISK_FLAGS = ("critical_infrastructure", "biosecurity_adjacent", "mass_influence")

_KNOWN_AGENT_KEYS = {
    "name", "owner", "purpose", "users", "geography", "production_status",
    "autonomy_intent", "data_classes", "economic_authority",
}
_KNOWN_BUSINESS_KEYS = {
    "industries", "regulated_activities", "max_customer_dependency", "societal_risk_flags",
}
_KNOWN_TOP_KEYS = {"version", "business", "agents", "governance", "evidence"}


@dataclass
class EconomicAuthority:
    max_per_action: dict | None = None
    daily_aggregate: dict | None = None
    worst_case_customer_loss: dict | None = None


@dataclass
class AgentDeclaration:
    agent_id: str
    name: str = ""
    owner: str = ""
    purpose: str = ""
    users: str | None = None
    geography: list[str] = field(default_factory=list)
    production_status: str | None = None
    autonomy_intent: str | None = None
    data_classes: list[str] = field(default_factory=list)
    economic_authority: EconomicAuthority | None = None


@dataclass
class Governance:
    release_approval: str = ""
    incident_response: str = ""
    risk_acceptance: dict | None = None
    harmful_output_policy: str = ""


@dataclass
class EvidenceRef:
    category: str  # testing | monitoring | contracts | historical
    kind: str
    ref: str
    date: str | None = None


class Declarations:
    """Loaded ``stoa-declared.toml``."""

    def __init__(
        self,
        path: Path,
        agents: dict[str, AgentDeclaration],
        business: dict,
        governance: Governance | None,
        evidence: list[EvidenceRef],
    ):
        self.path = path
        self.agents = agents
        self.business = business
        self.governance = governance
        self.evidence = evidence

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @classmethod
    def empty(cls, path: Path) -> "Declarations":
        return cls(path, {}, {}, None, [])

    @classmethod
    def load(cls, path: Path) -> tuple["Declarations", list[str]]:
        """Parse *path*. Returns ``(declarations, warnings)``.

        Malformed TOML raises ``ConfigError``. A missing file is not an
        error — it returns an empty ``Declarations`` (the feature is
        opt-in-by-presence).
        """
        if not path.is_file():
            return cls.empty(path), []

        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

        warnings: list[str] = []
        for key in data:
            if key not in _KNOWN_TOP_KEYS:
                warnings.append(f"{path}: unknown top-level key [{key}] — ignored")

        business = data.get("business", {})
        if not isinstance(business, dict):
            raise ConfigError(f"{path}: [business] must be a table")
        for key in business:
            if key not in _KNOWN_BUSINESS_KEYS:
                warnings.append(f"{path}: unknown key business.{key} — ignored")
        business = dict(business)
        if "max_customer_dependency" in business:
            level = business["max_customer_dependency"]
            if level not in DEPENDENCY_LEVELS:
                warnings.append(
                    f"{path}: business.max_customer_dependency={level!r} is not one of "
                    f"{DEPENDENCY_LEVELS} — ignored"
                )
                del business["max_customer_dependency"]
        if "societal_risk_flags" in business:
            flags = business["societal_risk_flags"] or []
            bad = [f for f in flags if f not in SOCIETAL_RISK_FLAGS]
            if bad:
                warnings.append(
                    f"{path}: business.societal_risk_flags has unknown values {bad} "
                    f"(expected a subset of {SOCIETAL_RISK_FLAGS}) — unknown values ignored"
                )
            business["societal_risk_flags"] = [f for f in flags if f in SOCIETAL_RISK_FLAGS]

        agents: dict[str, AgentDeclaration] = {}
        raw_agents = data.get("agents", {})
        if not isinstance(raw_agents, dict):
            raise ConfigError(f"{path}: [agents] must be a table of tables")
        for agent_id, raw in raw_agents.items():
            if not isinstance(raw, dict):
                raise ConfigError(f"{path}: [agents.{agent_id!r}] must be a table")
            decl, agent_warnings = _parse_agent_declaration(path, agent_id, raw)
            warnings.extend(agent_warnings)
            agents[agent_id] = decl

        governance = None
        raw_gov = data.get("governance")
        if raw_gov is not None:
            if not isinstance(raw_gov, dict):
                raise ConfigError(f"{path}: [governance] must be a table")
            governance = Governance(
                release_approval=raw_gov.get("release_approval", ""),
                incident_response=raw_gov.get("incident_response", ""),
                risk_acceptance=raw_gov.get("risk_acceptance"),
                harmful_output_policy=raw_gov.get("harmful_output_policy", ""),
            )

        evidence: list[EvidenceRef] = []
        raw_evidence = data.get("evidence", {})
        if not isinstance(raw_evidence, dict):
            raise ConfigError(f"{path}: [evidence] must be a table")
        for category, entries in raw_evidence.items():
            if not isinstance(entries, list):
                raise ConfigError(f"{path}: evidence.{category} must be a list")
            for entry in entries:
                if not isinstance(entry, dict) or "kind" not in entry or "ref" not in entry:
                    warnings.append(
                        f"{path}: evidence.{category} entry missing required "
                        "kind/ref — ignored"
                    )
                    continue
                evidence.append(EvidenceRef(
                    category=category, kind=entry["kind"], ref=entry["ref"],
                    date=entry.get("date"),
                ))

        return cls(path, agents, business, governance, evidence), warnings

    def unknown_agent_ids(self, known_ids: set[str]) -> list[str]:
        """Declared ids that no longer match any scanned agent (DECL007)."""
        return sorted(set(self.agents) - known_ids)


def generate_stub(agents: list[dict]) -> str:
    """A commented-out ``stoa-declared.toml`` stub, pre-populated with real
    scanned agent ids (from a registry document's ``agents`` list) so nobody
    has to find the hash by hand. Every field is commented out — declaring a
    fact is an explicit, git-reviewed action, never a filled-in default."""
    lines = [
        "# stoa-declared.toml — declared facts, cross-checked by the scanner.",
        "# Uncomment and fill in what you know; leave the rest commented out.",
        "version = 1",
        "",
        "# [business]",
        "# industries = []",
        "# regulated_activities = []",
        f"# max_customer_dependency = \"low\"  # {'|'.join(DEPENDENCY_LEVELS)}",
        f"# societal_risk_flags = []  # {'|'.join(SOCIETAL_RISK_FLAGS)} — attestation only, never scored",
        "",
    ]
    for agent in sorted(agents, key=lambda a: (a.get("path", ""), a.get("symbol", ""))):
        agent_id = agent["id"]
        name = agent.get("name", agent_id)
        lines += [
            f'[agents."{agent_id}"]',
            f'name = "{name}"  # {agent.get("path", "")} — from the last scan, for reference',
            '# owner = ""',
            '# purpose = ""',
            f"# users = \"internal\"  # {'|'.join(USERS_VALUES)}",
            "# geography = []",
            f"# production_status = \"production\"  # {'|'.join(PRODUCTION_STATUSES)}",
            f"# autonomy_intent = \"human_approved\"  # {'|'.join(AUTONOMY_INTENTS)}",
            f"# data_classes = []  # {'|'.join(DATA_CLASSES)}",
            "#",
            f'# [agents."{agent_id}".economic_authority]',
            '# max_per_action = {amount = 0, currency = "USD"}',
            '# daily_aggregate = {amount = 0, currency = "USD"}',
            '# worst_case_customer_loss = {amount = 0, currency = "USD"}',
            "",
        ]
    lines += [
        "# [governance]",
        '# release_approval = ""',
        '# incident_response = ""',
        '# harmful_output_policy = ""  # AIUC-1 Safety: declared risk taxonomy / harmful-output policy',
        "#",
        "# [governance.risk_acceptance]",
        '# owner = ""',
        '# date = "2026-01-01"',
        "",
        "# [[evidence.testing]]          # AIUC-1 Security: third-party adversarial testing",
        '# kind = "prompt_injection"',
        '# ref = ""',
        '# date = "2026-01-01"',
        "",
        "# [[evidence.safety_testing]]   # AIUC-1 Safety: third-party harmful-output / hallucination testing",
        '# kind = "harmful_output"',
        '# ref = ""',
        '# date = "2026-01-01"',
        "",
        "# [[evidence.vendor]]           # AIUC-1 Accountability: vendor due diligence",
        '# kind = "vendor_review"',
        '# ref = ""',
        '# date = "2026-01-01"',
        "",
    ]
    return "\n".join(lines)


def agent_declaration_to_dict(decl: AgentDeclaration) -> dict:
    record: dict = {
        "name": decl.name,
        "owner": decl.owner,
        "purpose": decl.purpose,
        "users": decl.users,
        "geography": decl.geography,
        "production_status": decl.production_status,
        "autonomy_intent": decl.autonomy_intent,
        "data_classes": decl.data_classes,
    }
    if decl.economic_authority is not None:
        record["economic_authority"] = {
            k: v for k, v in {
                "max_per_action": decl.economic_authority.max_per_action,
                "daily_aggregate": decl.economic_authority.daily_aggregate,
                "worst_case_customer_loss": decl.economic_authority.worst_case_customer_loss,
            }.items() if v is not None
        }
    return record


def governance_to_dict(gov: Governance) -> dict:
    record = {"release_approval": gov.release_approval, "incident_response": gov.incident_response}
    if gov.risk_acceptance is not None:
        record["risk_acceptance"] = gov.risk_acceptance
    if gov.harmful_output_policy:
        record["harmful_output_policy"] = gov.harmful_output_policy
    return record


def evidence_to_dict(items: list[EvidenceRef]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        entry = {"kind": item.kind, "ref": item.ref}
        if item.date is not None:
            entry["date"] = item.date
        grouped.setdefault(item.category, []).append(entry)
    return grouped


def _parse_agent_declaration(
    path: Path, agent_id: str, raw: dict
) -> tuple[AgentDeclaration, list[str]]:
    warnings: list[str] = []
    for key in raw:
        if key not in _KNOWN_AGENT_KEYS:
            warnings.append(f"{path}: unknown key agents.{agent_id!r}.{key} — ignored")

    users = raw.get("users")
    if users is not None and users not in USERS_VALUES:
        warnings.append(
            f"{path}: agents.{agent_id!r}.users={users!r} is not one of {USERS_VALUES} — ignored"
        )
        users = None

    production_status = raw.get("production_status")
    if production_status is not None and production_status not in PRODUCTION_STATUSES:
        warnings.append(
            f"{path}: agents.{agent_id!r}.production_status={production_status!r} "
            f"is not one of {PRODUCTION_STATUSES} — ignored"
        )
        production_status = None

    autonomy_intent = raw.get("autonomy_intent")
    if autonomy_intent is not None and autonomy_intent not in AUTONOMY_INTENTS:
        warnings.append(
            f"{path}: agents.{agent_id!r}.autonomy_intent={autonomy_intent!r} "
            f"is not one of {AUTONOMY_INTENTS} — ignored"
        )
        autonomy_intent = None

    data_classes = raw.get("data_classes", []) or []
    bad_classes = [c for c in data_classes if c not in DATA_CLASSES]
    if bad_classes:
        warnings.append(
            f"{path}: agents.{agent_id!r}.data_classes has unknown values {bad_classes} "
            f"(expected a subset of {DATA_CLASSES}) — unknown values ignored"
        )
        data_classes = [c for c in data_classes if c in DATA_CLASSES]

    economic_authority = None
    raw_econ = raw.get("economic_authority")
    if raw_econ is not None:
        if not isinstance(raw_econ, dict):
            warnings.append(
                f"{path}: agents.{agent_id!r}.economic_authority must be a table — ignored"
            )
        else:
            amounts = {}
            for field_name in ("max_per_action", "daily_aggregate", "worst_case_customer_loss"):
                if field_name not in raw_econ:
                    continue
                amt = raw_econ[field_name]
                if (
                    not isinstance(amt, dict)
                    or "amount" not in amt
                    or "currency" not in amt
                    or not isinstance(amt["amount"], (int, float))
                ):
                    warnings.append(
                        f"{path}: agents.{agent_id!r}.economic_authority.{field_name} "
                        "must be {amount = <number>, currency = \"...\"} — ignored"
                    )
                    continue
                amounts[field_name] = amt
            economic_authority = EconomicAuthority(**amounts) if amounts else None

    decl = AgentDeclaration(
        agent_id=agent_id,
        name=raw.get("name", ""),
        owner=raw.get("owner", ""),
        purpose=raw.get("purpose", ""),
        users=users,
        geography=list(raw.get("geography", []) or []),
        production_status=production_status,
        autonomy_intent=autonomy_intent,
        data_classes=data_classes,
        economic_authority=economic_authority,
    )
    return decl, warnings

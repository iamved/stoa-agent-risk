"""Pydantic v2 models for the canonical submission schema.

Core design rule: every posture answer carries an evidence quadruple —
{value, evidence, confidence, scan_hash} — where absence of evidence is
ALWAYS `unknown`, never a "no". `attested` marks human-declared answers
with no code verification. This quadruple is the product's explainability
feature; it is never dropped anywhere downstream.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Confidence(str, Enum):
    confirmed = "confirmed"
    not_confirmed = "not_confirmed"
    unknown = "unknown"
    contradicted = "contradicted"
    attested = "attested"


class EvidencedValue(BaseModel):
    """The evidence quadruple attached to every answer field."""

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.unknown
    scan_hash: Optional[str] = None


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    generated_at: str
    extractor_version: str
    registry_scan_hash: str
    sample_data: bool = False


# --------------------------------------------------------------------------
# business_context
# --------------------------------------------------------------------------


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    website: Optional[str] = None
    employees: Optional[int] = None
    industry: Optional[str] = None
    naics: Optional[str] = None
    annual_revenue_usd: Optional[float] = None
    gross_profit_usd: Optional[float] = None
    description: Optional[str] = None


class LossEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    description: str
    status: str


class LiabilityCapType(str, Enum):
    fee_pct = "fee_pct"
    contract_pct = "contract_pct"
    fixed = "fixed"
    none = "none"


class LiabilityCap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: LiabilityCapType
    value: Optional[float] = None


class ContractProvision(str, Enum):
    limitation_of_liability = "limitation_of_liability"
    indemnity = "indemnity"
    arbitration = "arbitration"
    warranty_disclaimer = "warranty_disclaimer"
    consequential_damages_exclusion = "consequential_damages_exclusion"
    ai_output_disclaimer = "ai_output_disclaimer"


class Contracts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avg_value_usd: Optional[float] = None
    largest_value_usd: Optional[float] = None
    pct_standard_terms: Optional[float] = None
    liability_cap: Optional[LiabilityCap] = None
    provisions: list[ContractProvision] = Field(default_factory=list)
    legal_counsel_reviews: Optional[bool] = None


class Projections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: Optional[int] = None
    outputs: Optional[int] = None
    revenue_usd: Optional[float] = None


class GovernanceOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str


class BusinessContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: Company
    loss_history: list[LossEvent] = Field(default_factory=list)
    contracts: Optional[Contracts] = None
    other_policies: list[str] = Field(default_factory=list)
    projections: Optional[dict[str, Projections]] = None  # keyed e.g. "next_2y"
    governance_owners: list[GovernanceOwner] = Field(default_factory=list)


# --------------------------------------------------------------------------
# systems[]
# --------------------------------------------------------------------------


class Posture(BaseModel):
    """Every field is an evidence quadruple. Field semantics:

    - data_types values: company_proprietary | licensed_third_party | unlicensed | synthetic
    - sensitive_data values: pii | health | payment | biometric | none
    - output_types values: text | video | audio | image | other
    - audience: internal | third_party | both
    - frameworks values: nist_ai_rmf | iso_42001
    """

    model_config = ConfigDict(extra="forbid")

    model: EvidencedValue
    business_activities: EvidencedValue
    fine_tuned: EvidencedValue
    data_types: EvidencedValue
    sensitive_data: EvidencedValue
    output_types: EvidencedValue
    audience: EvidencedValue
    io_logging: EvidencedValue
    hitl: EvidencedValue
    agentic_actions: EvidencedValue
    frameworks: EvidencedValue
    guardrails_intact: EvidencedValue


class AttestationStatus(str, Enum):
    verified = "verified"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


class Attestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str
    declared: bool
    observed: Optional[bool] = None
    status: AttestationStatus


class Severity(str, Enum):
    output_error = "output_error"
    ip_infringement = "ip_infringement"
    data_disclosure = "data_disclosure"
    bodily_injury = "bodily_injury"
    property_damage = "property_damage"
    regulatory = "regulatory"
    none = "none"


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts: str
    scenario_id: str
    scenario_class: str
    expected: str
    actual: str
    pass_: bool = Field(alias="pass")
    severity: Severity
    loss_proxy_usd: float = 0.0


class Robustness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_tests: int
    passed: int
    pass_rate: float


class Aggregates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_runs: int
    error_rate: float
    ci_95: list[float]
    severity_counts: dict[str, int] = Field(default_factory=dict)
    total_loss_proxy_usd: float = 0.0
    robustness: Optional[Robustness] = None


class CoveredModelDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    covered_model: str
    function_scope: str
    error_definition: str
    ground_truth_source: str
    unexpected_error_threshold: str
    proposed_error_limit_usd: float


class EvidenceClass(str, Enum):
    simulated = "simulated"
    observed = "observed"


class Performance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[Run] = Field(default_factory=list)
    aggregates: Optional[Aggregates] = None
    covered_model_draft: Optional[CoveredModelDraft] = None
    evidence_class: EvidenceClass = EvidenceClass.simulated


class System(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    description: str
    posture: Posture
    attestations: list[Attestation] = Field(default_factory=list)
    performance: Optional[Performance] = None


# --------------------------------------------------------------------------
# coverage_request / gaps
# --------------------------------------------------------------------------


class CoverageHead(str, Enum):
    output_error = "output_error"
    ip_or_personal_injury = "ip_or_personal_injury"
    data_disclosure = "data_disclosure"
    bodily_injury = "bodily_injury"
    property_damage = "property_damage"
    regulatory = "regulatory"


class CoverageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heads: list[CoverageHead] = Field(default_factory=list)
    limit_usd: Optional[float] = None
    rationale: Optional[str] = None


class GapOwner(str, Enum):
    human = "human"
    scan = "scan"
    simulator = "simulator"


class Gap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str
    field_id: str
    description: str
    owner: GapOwner


# --------------------------------------------------------------------------
# root
# --------------------------------------------------------------------------


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: Meta
    business_context: BusinessContext
    systems: list[System] = Field(default_factory=list)
    coverage_request: Optional[CoverageRequest] = None
    gaps: list[Gap] = Field(default_factory=list)


def load_submission(path: str) -> Submission:
    """Parse and validate a submission JSON file into models."""
    import json

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Submission.model_validate(data)

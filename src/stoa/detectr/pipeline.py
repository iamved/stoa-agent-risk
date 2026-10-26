"""One call from a ledger to findings: claims, routing, fusion, findings."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .claims import Claim, ClaimExtractor, LLMClaimExtractor, RuleClaimExtractor
from .evidence import Evidence
from .fusion import FusedVerdict, fuse, to_findings
from .ledger import Ledger, LedgerEntry
from .router import Router, RouterConfig, RunResult

REPORT_SCHEMA = "stoa-detectr-report/0.1"


@dataclass
class Report:
    ledger: Ledger
    claims: list[Claim]
    run: RunResult
    fused: list[FusedVerdict]
    findings: list[dict]
    evidence: dict[str, list[Evidence]] = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        counts = {label: sum(1 for f in self.fused if f.label == label) for label in ("grounded", "unsupported", "contradicted", "unverifiable")}
        return {
            "schema": REPORT_SCHEMA,
            "trajectory_id": self.ledger.trajectory_id, "agent_id": self.ledger.agent_id, "model_id": self.ledger.model_id,
            "built_from": self.ledger.built_from, "consequence": self.run.consequence,
            "entries": len(self.ledger.entries), "redacted": self.ledger.redacted,
            "claims": [c.to_dict() for c in self.claims],
            "claim_timestamps": {c.id: next((e.timestamp for e in self.ledger.entries if e.id == c.entry_id), None) for c in self.claims},
            "verdicts": [f.to_dict() for f in self.fused],
            "findings": self.findings,
            "counts": counts,
            "checkers": {"ran": sorted({v.checker for v in self.run.external}), "skipped": self.run.skipped, "demoted": self.run.demoted,
                         "deferred": [{"checker": c, "claim_id": k} for c, k in self.run.deferred_plan], "timings_ms": {k: round(v, 2) for k, v in self.run.timings_ms.items()}},
            "warnings": list(self.ledger.warnings) + list(self.run.warnings),
        }


def check_ledger(ledger: Ledger, *, config: RouterConfig | None = None, router: Router | None = None, entries: list[LedgerEntry] | None = None,
                 schema: dict | None = None, registry: dict | None = None, agent: dict | None = None, deferred: bool = True,
                 extractor: ClaimExtractor | None = None, llm_complete=None) -> Report:
    config = config or (router.config if router else RouterConfig())
    router = router or Router(config)
    if extractor is None:
        if config.extractor == "llm" and llm_complete is not None:
            extractor = LLMClaimExtractor(llm_complete)
        else:
            extractor = RuleClaimExtractor(status_synonyms=config.tolerances.status_synonyms)
    claims = extractor.extract(ledger)
    run = router.run(ledger, claims, entries=entries, schema=schema, registry=registry, deferred=deferred)
    if ledger.redacted and not any("capture_content" in w for w in ledger.warnings + run.warnings):
        run.warnings.append("content not captured: configure(capture_content=True) to record prompts, responses and payloads; every claim is unverifiable")
    fused = fuse(claims, run.layer0, run.external, weights=config.weights, threshold=config.threshold_for(ledger.agent_id))
    findings = to_findings(fused, claims, ledger, evidence=run.evidence, agent=agent)
    return Report(ledger, claims, run, fused, findings, run.evidence)

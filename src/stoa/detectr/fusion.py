"""Fusion: one verdict per claim, findings in the existing shape.

A Layer 0 contradiction wins outright. Otherwise checker scores combine with
per-checker weights into a probability, read against the agent's threshold.
Labels: grounded, unsupported, contradicted, unverifiable. Unverifiable
means no evidence could be resolved and is counted apart, never in the
hallucination rate. Taint follows ``consumed_by``: downstream claims that
reuse a bad value are marked, and the count is the blast radius.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ..models import finding_fingerprint
from ..redaction import redact_line
from ..rules import RULES
from .claims import Claim
from .evidence import Evidence
from .layer0 import RULE_IDS, Verdict
from .ledger import Ledger

LABELS = ("grounded", "unsupported", "contradicted", "unverifiable")
# When several Layer 0 rules fire on one claim, the finding carries the most
# consequential one.
_RULE_PRIORITY = {RULE_IDS["argument"]: 0, RULE_IDS["phantom"]: 1, RULE_IDS["fidelity"]: 2, RULE_IDS["stale"]: 3, RULE_IDS["promise"]: 4}
_TEXT_RULE_FOR_TYPE = {"commitment": RULE_IDS["promise"], "action": RULE_IDS["phantom"]}


@dataclass
class FusedVerdict:
    claim_id: str
    label: str
    probability: float
    rule_id: str | None = None
    subcategory: str | None = None
    evidence: list[str] = dc_field(default_factory=list)
    detail: str = ""
    checkers: list[str] = dc_field(default_factory=list)
    tainted: bool = False
    tainted_by: list[str] = dc_field(default_factory=list)
    blast_radius: int = 0
    layer0: list[Verdict] = dc_field(default_factory=list)
    external: list[Verdict] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "label": self.label, "probability": round(self.probability, 4), "rule_id": self.rule_id,
            "subcategory": self.subcategory, "evidence": list(self.evidence), "detail": self.detail, "checkers": list(self.checkers),
            "tainted": self.tainted, "tainted_by": list(self.tainted_by), "blast_radius": self.blast_radius,
            "layer0": [v.to_dict() for v in self.layer0], "external": [v.to_dict() for v in self.external],
        }


def _non_grounded_probability(verdict: Verdict) -> float:
    """The checker's belief that the claim is NOT grounded."""
    if verdict.label == "grounded":
        return 1.0 - min(max(verdict.confidence, 0.0), 1.0)
    if verdict.label == "unverifiable":
        return 0.5
    return min(max(verdict.confidence, 0.0), 1.0)


def combine(external: list[Verdict], weights: dict[str, float]) -> float | None:
    usable = [v for v in external if v.label != "unverifiable"]
    if not usable:
        return None
    total = sum(weights.get(v.checker, 1.0) for v in usable)
    if total <= 0:
        return None
    return sum(weights.get(v.checker, 1.0) * _non_grounded_probability(v) for v in usable) / total


def fuse(claims: list[Claim], layer0: list[Verdict], external: list[Verdict], *, weights: dict[str, float] | None = None,
         threshold: float = 0.5) -> list[FusedVerdict]:
    weights = weights or {}
    by_claim_l0: dict[str, list[Verdict]] = {}
    by_claim_ext: dict[str, list[Verdict]] = {}
    for v in layer0:
        by_claim_l0.setdefault(v.claim_id, []).append(v)
    for v in external:
        by_claim_ext.setdefault(v.claim_id, []).append(v)
    fused: dict[str, FusedVerdict] = {}
    for claim in claims:
        l0 = by_claim_l0.get(claim.id, [])
        ext = by_claim_ext.get(claim.id, [])
        checkers = sorted({v.checker for v in l0 + ext})
        contradicted = sorted((v for v in l0 if v.label == "contradicted"), key=lambda v: (_RULE_PRIORITY.get(v.rule_id or "", 9), v.claim_id))
        unsupported = sorted((v for v in l0 if v.label == "unsupported"), key=lambda v: (_RULE_PRIORITY.get(v.rule_id or "", 9), v.claim_id))
        grounded = [v for v in l0 if v.label == "grounded"]
        combined = combine(ext, weights)
        if contradicted:
            top = contradicted[0]
            result = FusedVerdict(claim.id, "contradicted", 1.0, top.rule_id, top.subcategory, _union(contradicted), top.detail, checkers, layer0=l0, external=ext)
        elif unsupported:
            top = unsupported[0]
            probability = combined if combined is not None else 0.85
            if combined is not None:
                probability = 0.5 * 0.85 + 0.5 * combined
            result = FusedVerdict(claim.id, "unsupported", probability, top.rule_id, top.subcategory, _union(unsupported), top.detail, checkers, layer0=l0, external=ext)
        elif combined is not None and combined >= threshold:
            worst = max((v for v in ext if v.label != "unverifiable"), key=lambda v: _non_grounded_probability(v))
            label = "contradicted" if worst.label == "contradicted" else "unsupported"
            rule_id = _TEXT_RULE_FOR_TYPE.get(claim.type, RULE_IDS["fidelity"])
            result = FusedVerdict(claim.id, label, combined, rule_id, worst.subcategory or "text", _union([worst]), worst.detail, checkers, layer0=l0, external=ext)
        elif grounded or (combined is not None and combined < threshold):
            probability = combined if combined is not None else 0.0
            source = grounded[0] if grounded else max(ext, key=lambda v: v.confidence)
            result = FusedVerdict(claim.id, "grounded", probability, None, None, _union(grounded or ext), source.detail, checkers, layer0=l0, external=ext)
        else:
            detail = next((v.detail for v in l0 + ext if v.label == "unverifiable"), "no checkable value and no evidence")
            result = FusedVerdict(claim.id, "unverifiable", 0.0, None, "unverifiable", [], detail, checkers, layer0=l0, external=ext)
        fused[claim.id] = result
    _propagate(claims, fused)
    return [fused[c.id] for c in claims]


def _union(verdicts: list[Verdict]) -> list[str]:
    seen: list[str] = []
    for v in verdicts:
        for e in v.evidence:
            if e not in seen:
                seen.append(e)
    return seen


def _propagate(claims: list[Claim], fused: dict[str, FusedVerdict]) -> None:
    by_id = {c.id: c for c in claims}
    for claim in claims:
        verdict = fused[claim.id]
        if verdict.label not in ("unsupported", "contradicted"):
            continue
        downstream: list[str] = []
        stack = list(claim.consumed_by)
        while stack:
            nxt = stack.pop()
            if nxt in downstream or nxt == claim.id or nxt not in by_id:
                continue
            downstream.append(nxt)
            stack.extend(by_id[nxt].consumed_by)
        verdict.blast_radius = len(downstream)
        for cid in downstream:
            fused[cid].tainted = True
            if claim.id not in fused[cid].tainted_by:
                fused[cid].tainted_by.append(claim.id)


def to_findings(fused: list[FusedVerdict], claims: list[Claim], ledger: Ledger, *, evidence: dict[str, list[Evidence]] | None = None,
                agent: dict | None = None, severity_overrides: dict[str, str] | None = None) -> list[dict]:
    """One finding per non-grounded fused verdict, in the shape the RT
    family uses, plus a ``detectr`` block. Excerpts go through the
    scanner's redactor; ledger entry hashes are kept for verification."""
    by_claim = {c.id: c for c in claims}
    entries = {e.id: e for e in ledger.entries}
    path = (agent or {}).get("path") or f"trajectory:{ledger.trajectory_id}"
    line = ((agent or {}).get("evidence") or [{}])[0].get("line", 1) if agent else 1
    out: list[dict] = []
    for verdict in fused:
        if verdict.label not in ("unsupported", "contradicted") or not verdict.rule_id:
            continue
        claim = by_claim[verdict.claim_id]
        spec = RULES[verdict.rule_id]
        context_key = f"{ledger.trajectory_id}:{claim.id}:{redact_line(claim.text)[:120]}"
        anchor = entries.get(claim.entry_id)
        trace_ref = None
        if anchor is not None and (anchor.meta.get("trace_file") or anchor.span_id):
            trace_ref = {"file": anchor.meta.get("trace_file"), "line": anchor.meta.get("trace_line"), "span_id": anchor.span_id}
        excerpts = []
        for item in (evidence or {}).get(claim.id, []):
            excerpts.append({"entry_id": item.entry_id, "kind": item.kind, "hash": item.hash, "excerpt": redact_line(item.excerpt)})
        for entry_id in verdict.evidence:
            if entry_id not in {x["entry_id"] for x in excerpts} and entry_id in entries:
                e = entries[entry_id]
                excerpts.append({"entry_id": e.id, "kind": e.kind, "hash": e.hash, "excerpt": redact_line(e.text_view[:400])})
        finding = {
            "fingerprint": finding_fingerprint(verdict.rule_id, path, context_key),
            "rule_id": verdict.rule_id,
            "title": spec.title,
            "category": spec.category,
            "severity": (severity_overrides or {}).get(verdict.rule_id, spec.default_severity),
            "confidence": "high" if verdict.probability >= 0.85 else "medium" if verdict.probability >= 0.5 else "low",
            "path": path,
            "line": line,
            "column": 1,
            "snippet": redact_line(claim.text)[:200],
            "remediation": spec.remediation,
            "suppressed": False,
            "suppression_reason": None,
            "is_new": False,
            "message": redact_line(verdict.detail),
            "detectr": {
                "label": verdict.label, "subcategory": verdict.subcategory, "probability": round(verdict.probability, 4),
                "claim": {"id": claim.id, "type": claim.type, "text": redact_line(claim.text), "char_span": list(claim.char_span) if claim.char_span else None,
                          "span_id": claim.span_id, "entry_id": claim.entry_id, "tool_name": claim.tool_name, "source": claim.source},
                "evidence": excerpts, "checkers": verdict.checkers, "blast_radius": verdict.blast_radius, "tainted": verdict.tainted,
                "trajectory_id": ledger.trajectory_id, "agent_id": ledger.agent_id,
                # Every non-grounded verdict on the claim, so a reply that gets both
                # the amount and the status wrong shows both.
                "issues": [{"rule_id": v.rule_id, "label": v.label, "subcategory": v.subcategory, "field": v.field, "value": v.value,
                            "raw": v.raw, "expected": v.expected, "checker": v.checker, "detail": redact_line(v.detail)}
                           for v in verdict.layer0 + verdict.external if v.label in ("unsupported", "contradicted")],
            },
        }
        if trace_ref:
            finding["trace_ref"] = trace_ref
        out.append(finding)
    return out

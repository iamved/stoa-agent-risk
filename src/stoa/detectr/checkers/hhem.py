"""Vectara HHEM-2.1-Open adapter: one consistency score for a premise and a
hypothesis, as a second opinion on text claims. English only.

Install with ``pip install stoa-agent-risk[hallucination-hhem]``. The model's
license is read from its card at install time and recorded in the manifest
by ``record_license``; it ships as "see model card" until then.
"""

from __future__ import annotations

from ..claims import Claim
from ..evidence import Evidence, evidence_context
from ..layer0 import Verdict
from . import CheckerManifest, CheckerUnavailable, grounded, unverifiable

MODEL = "vectara/hallucination_evaluation_model"


class HHEMChecker:
    MANIFEST = CheckerManifest(
        id="hhem", claim_types={"factual", "result", "commitment", "reasoning"}, requires_evidence=True,
        requires_model_internals=False, max_context_tokens=512, est_latency_ms=200, est_cost_per_call=0.0,
        sync_capable=False, license="see model card", extra="hallucination-hhem",
        notes="FLAN-T5 based consistency classifier, under 600MB, English only; short inputs work best.",
    )
    manifest = MANIFEST

    def __init__(self, *, threshold: float = 0.5, model=None, model_name: str = MODEL) -> None:
        self.threshold = float(threshold)
        self.model_name = model_name
        self._model = model

    @classmethod
    def record_license(cls, text: str) -> None:
        cls.MANIFEST.license = text

    def _load(self):
        if self._model is None:
            try:
                from transformers import AutoModelForSequenceClassification
            except ImportError as exc:
                raise CheckerUnavailable("HHEM needs transformers and torch: pip install 'stoa-agent-risk[hallucination-hhem]'") from exc
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name, trust_remote_code=True)
        return self._model

    def check(self, claim: Claim, evidence: list[Evidence]) -> Verdict:
        context = evidence_context(evidence)
        if not context:
            return unverifiable(claim, "hhem", "no evidence could be resolved for this claim")
        model = self._load()
        premise = "\n".join(context)
        scores = model.predict([(premise, claim.text)])
        score = float(scores[0]) if not hasattr(scores, "tolist") else float(scores.tolist()[0])
        if score >= self.threshold:
            return grounded(claim, "hhem", score, f"consistent with the evidence (score {score:.2f})", evidence)
        return Verdict(claim.id, "unsupported", None, "inconsistent", [e.entry_id for e in evidence],
                       f"not consistent with the evidence (score {score:.2f})", confidence=1.0 - score, checker="hhem")

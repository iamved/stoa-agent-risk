"""LettuceDetect adapter: token-level unsupported spans of a claim against
its evidence. MIT licensed encoder models that run on CPU.

Install with ``pip install stoa-agent-risk[hallucination]``. The default
model is the v2 mmBERT encoder with the taxonomy head, which types each span
(category and subcategory). The generative ``lettucedect-v2-qwen-2b`` can be
selected for typed spans with reasons at a higher cost.
"""

from __future__ import annotations

from ..claims import Claim
from ..evidence import Evidence, evidence_context
from ..layer0 import Verdict
from . import CheckerManifest, CheckerUnavailable, grounded, unverifiable

DEFAULT_MODEL = "KRLabsOrg/lettucedect-v2-mmbert-base"
DEFAULT_TAXONOMY_HEAD = "KRLabsOrg/lettucedect-v2-taxonomy-head"
GENERATIVE_MODEL = "KRLabsOrg/lettucedect-v2-qwen-2b"
# EuroBERT variants need transformers below 5 and are not selected by default.
EXCLUDED_MODEL_HINTS = ("eurobert",)

_CATEGORY_LABEL = {"contradiction": "contradicted", "contradicted": "contradicted", "unsupported": "unsupported",
                   "fabrication": "unsupported", "baseless": "unsupported", "extrinsic": "unsupported", "intrinsic": "contradicted"}


class LettuceDetectChecker:
    MANIFEST = CheckerManifest(
        id="lettucedetect", claim_types={"factual", "result", "commitment", "reasoning", "action"}, requires_evidence=True,
        requires_model_internals=False, max_context_tokens=8192, est_latency_ms=120, est_cost_per_call=0.0,
        sync_capable=True, license="MIT", extra="hallucination",
        notes="Encoder cascade: binary span detector plus a typing head. Spans below min_confidence are dropped.",
    )
    manifest = MANIFEST

    def __init__(self, *, model_path: str = DEFAULT_MODEL, taxonomy_head: str | None = DEFAULT_TAXONOMY_HEAD, min_confidence: float = 0.5,
                 method: str = "transformer", detector=None, lang: str | None = None) -> None:
        if any(hint in (model_path or "").lower() for hint in EXCLUDED_MODEL_HINTS):
            raise CheckerUnavailable(f"{model_path} needs transformers<5 and is not supported by this adapter; pick a ModernBERT or mmBERT model")
        self.model_path = model_path
        self.taxonomy_head = taxonomy_head
        self.min_confidence = float(min_confidence)
        self.method = method
        self.lang = lang
        self._detector = detector

    def _load(self):
        if self._detector is None:
            try:
                from lettucedetect.models.inference import HallucinationDetector
            except ImportError as exc:
                raise CheckerUnavailable("LettuceDetect is not installed: pip install 'stoa-agent-risk[hallucination]'") from exc
            kwargs = {"method": self.method, "model_path": self.model_path}
            if self.taxonomy_head and self.method == "transformer":
                kwargs["taxonomy_head"] = self.taxonomy_head
            if self.lang:
                kwargs["lang"] = self.lang
            self._detector = HallucinationDetector(**kwargs)
        return self._detector

    def check(self, claim: Claim, evidence: list[Evidence], *, question: str = "") -> Verdict:
        context = evidence_context(evidence)
        if not context:
            return unverifiable(claim, "lettucedetect", "no evidence could be resolved for this claim")
        detector = self._load()
        spans = detector.predict(context=context, question=question or "", answer=claim.text, output_format="spans") or []
        kept = [s for s in spans if float(s.get("confidence", s.get("hallucination_score", 0.0))) >= self.min_confidence]
        if not kept:
            return grounded(claim, "lettucedetect", 1.0 - max((float(s.get("confidence", 0.0)) for s in spans), default=0.0), "no unsupported span found", evidence)
        top = max(kept, key=lambda s: float(s.get("confidence", 0.0)))
        category = str(top.get("category") or "unsupported").lower()
        label = _CATEGORY_LABEL.get(category, "unsupported")
        subcategory = str(top.get("subcategory") or category or "span").lower()
        texts = [str(s.get("text", "")) for s in kept if s.get("text")]
        detail = f"unsupported span(s): {texts}" if texts else "unsupported span found"
        return Verdict(claim.id, label, None, subcategory, [e.entry_id for e in evidence], detail, confidence=float(top.get("confidence", 0.0)),
                       checker="lettucedetect", value=texts[0] if texts else None)

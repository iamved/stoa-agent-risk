"""DeepEval judge adapter: a model-graded faithfulness score with a reason,
run in batch with the customer's own key. Never on the synchronous path.

Install with ``pip install stoa-agent-risk[hallucination-judge]``. The judge
refuses to grade an agent from the same model family as itself.
"""

from __future__ import annotations

import re

from ..claims import Claim
from ..evidence import Evidence, evidence_context
from ..layer0 import Verdict
from . import CheckerManifest, CheckerUnavailable, grounded, unverifiable

_FAMILIES = ("gpt", "o1", "o3", "o4", "claude", "gemini", "llama", "mistral", "mixtral", "qwen", "deepseek", "command", "grok", "nova", "titan", "phi")


def model_family(name: str | None) -> str | None:
    if not name:
        return None
    lowered = name.lower()
    for family in _FAMILIES:
        if re.search(rf"(^|[^a-z]){family}", lowered):
            return family
    return lowered.split("/")[-1].split("-")[0] or None


class SameFamilyRefusal(RuntimeError):
    """The judge would be grading its own model family."""


class DeepEvalJudge:
    MANIFEST = CheckerManifest(
        id="deepeval", claim_types={"factual", "result", "commitment", "reasoning", "action"}, requires_evidence=True,
        requires_model_internals=False, max_context_tokens=None, est_latency_ms=4000, est_cost_per_call=0.002,
        sync_capable=False, license="Apache-2.0", extra="hallucination-judge",
        notes="Faithfulness metric; score 0 to 1 with a reason. Batch only, customer key.",
    )
    manifest = MANIFEST

    def __init__(self, *, judge_model: str, agent_model: str | None = None, threshold: float = 0.7, metric=None) -> None:
        if agent_model and model_family(judge_model) and model_family(judge_model) == model_family(agent_model):
            raise SameFamilyRefusal(f"judge {judge_model!r} and agent model {agent_model!r} share the {model_family(judge_model)} family")
        self.judge_model = judge_model
        self.agent_model = agent_model
        self.threshold = float(threshold)
        self._metric = metric

    def _load(self):
        if self._metric is None:
            try:
                from deepeval.metrics import FaithfulnessMetric
            except ImportError as exc:
                raise CheckerUnavailable("DeepEval is not installed: pip install 'stoa-agent-risk[hallucination-judge]'") from exc
            self._metric = FaithfulnessMetric(threshold=self.threshold, model=self.judge_model, include_reason=True)
        return self._metric

    def check(self, claim: Claim, evidence: list[Evidence], *, question: str = "") -> Verdict:
        context = evidence_context(evidence)
        if not context:
            return unverifiable(claim, "deepeval", "no evidence could be resolved for this claim")
        metric = self._load()
        try:
            from deepeval.test_case import LLMTestCase
            case = LLMTestCase(input=question or "agent turn", actual_output=claim.text, retrieval_context=context)
        except ImportError:
            case = {"input": question, "actual_output": claim.text, "retrieval_context": context}
        metric.measure(case)
        score = float(getattr(metric, "score", 0.0) or 0.0)
        reason = str(getattr(metric, "reason", "") or "")
        if score >= self.threshold:
            return grounded(claim, "deepeval", score, reason or f"faithful (score {score:.2f})", evidence)
        return Verdict(claim.id, "unsupported", None, "judged", [e.entry_id for e in evidence], reason or f"not faithful (score {score:.2f})",
                       confidence=1.0 - score, checker="deepeval")

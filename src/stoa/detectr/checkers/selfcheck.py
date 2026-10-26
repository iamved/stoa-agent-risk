"""Resampling consistency (SelfCheckGPT style): sample the model again and
test whether the original answer agrees with the samples. Registered so the
interface is fixed; not implemented in this build."""

from __future__ import annotations

from ..claims import Claim
from ..evidence import Evidence
from ..layer0 import Verdict
from . import CheckerManifest


class SelfCheckStub:
    MANIFEST = CheckerManifest(
        id="selfcheck", claim_types={"factual", "result", "commitment", "reasoning"}, requires_evidence=False,
        requires_model_internals=True, max_context_tokens=None, est_latency_ms=6000, est_cost_per_call=0.01,
        sync_capable=False, license="n/a", extra=None, notes="Needs the agent's model and sampling access. Stub.", implemented=False,
    )
    manifest = MANIFEST

    def __init__(self, **_config) -> None:
        pass

    def check(self, claim: Claim, evidence: list[Evidence]) -> Verdict:
        raise NotImplementedError("selfcheck is a stub in this build; see docs/design/detectr.md")

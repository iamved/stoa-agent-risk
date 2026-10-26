"""External checkers: text claims judged against evidence by models.

The core has no model dependency. Each adapter imports its library when it
is first used and says plainly which extra to install when it is missing.
Checkers register under the ``stoa.detectr.checkers`` entry point group, so
a customer can ship their own by naming it in their package metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from importlib import import_module
from importlib.metadata import entry_points
from typing import Protocol

from ..claims import Claim
from ..evidence import Evidence
from ..layer0 import Verdict

BUILTIN = {
    "lettucedetect": "stoa.detectr.checkers.lettucedetect:LettuceDetectChecker",
    "hhem": "stoa.detectr.checkers.hhem:HHEMChecker",
    "deepeval": "stoa.detectr.checkers.deepeval:DeepEvalJudge",
    "selfcheck": "stoa.detectr.checkers.selfcheck:SelfCheckStub",
}


@dataclass
class CheckerManifest:
    id: str
    claim_types: set[str]
    requires_evidence: bool
    requires_model_internals: bool
    max_context_tokens: int | None
    est_latency_ms: int
    est_cost_per_call: float
    sync_capable: bool
    license: str
    extra: str | None = None
    notes: str = ""
    implemented: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id, "claim_types": sorted(self.claim_types), "requires_evidence": self.requires_evidence,
            "requires_model_internals": self.requires_model_internals, "max_context_tokens": self.max_context_tokens,
            "est_latency_ms": self.est_latency_ms, "est_cost_per_call": self.est_cost_per_call, "sync_capable": self.sync_capable,
            "license": self.license, "extra": self.extra, "notes": self.notes, "implemented": self.implemented,
        }


class Checker(Protocol):
    manifest: CheckerManifest

    def check(self, claim: Claim, evidence: list[Evidence]) -> Verdict: ...


class CheckerUnavailable(RuntimeError):
    """The checker's library or model is not installed."""


@dataclass
class CheckerSpec:
    name: str
    target: str
    source: str  # builtin | entry_point
    manifest: CheckerManifest | None = None
    error: str | None = None
    config: dict = dc_field(default_factory=dict)


def _resolve(target: str):
    module_name, _, attr = target.partition(":")
    module = import_module(module_name)
    return getattr(module, attr)


def available_checkers() -> dict[str, CheckerSpec]:
    """Built-in adapters plus any registered through entry points. Nothing
    is imported beyond the adapter module; model libraries load on use."""
    specs: dict[str, CheckerSpec] = {name: CheckerSpec(name, target, "builtin") for name, target in BUILTIN.items()}
    try:
        for ep in entry_points(group="stoa.detectr.checkers"):
            specs[ep.name] = CheckerSpec(ep.name, ep.value, "entry_point")
    except Exception:  # noqa: BLE001 - metadata problems never break the core
        pass
    for spec in specs.values():
        try:
            cls = _resolve(spec.target)
            spec.manifest = getattr(cls, "MANIFEST", None)
        except Exception as exc:  # noqa: BLE001
            spec.error = f"{type(exc).__name__}: {exc}"
    return specs


def load_checker(name: str, **config) -> Checker:
    """Instantiate a checker by name. Raises ``CheckerUnavailable`` with the
    extra to install when its library is missing."""
    specs = available_checkers()
    if name not in specs:
        raise KeyError(f"unknown checker {name!r}; known: {sorted(specs)}")
    spec = specs[name]
    if spec.error:
        raise CheckerUnavailable(f"checker {name!r} cannot be imported: {spec.error}")
    cls = _resolve(spec.target)
    return cls(**config)


def grounded(claim: Claim, checker: str, confidence: float, detail: str, evidence: list[Evidence]) -> Verdict:
    return Verdict(claim.id, "grounded", None, None, [e.entry_id for e in evidence], detail, confidence=confidence, checker=checker)


def unverifiable(claim: Claim, checker: str, detail: str) -> Verdict:
    return Verdict(claim.id, "unverifiable", None, "no_evidence", [], detail, confidence=0.0, checker=checker)

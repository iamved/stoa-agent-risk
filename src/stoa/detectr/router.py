"""Routing: which checkers run on which claims, in which lane.

Layer 0 always runs on every claim. External checkers run per
``stoa.detectr.toml``, keyed on the consequence class of the trajectory
(payment, delete, external_send, write, read, unknown): which checkers, a
sample rate, sync or deferred, and a latency budget for the sync lane. A
sync checker that blows its budget is demoted to the deferred lane for the
rest of the run, with one warning.
"""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from .checkers import Checker, CheckerUnavailable, load_checker
from .claims import Claim
from .evidence import Evidence, resolve_evidence
from .layer0 import Tolerances, Verdict, run_layer0
from .ledger import Ledger, LedgerEntry

CONFIG_NAME = "stoa.detectr.toml"
CONSEQUENCE_CLASSES = ("payment", "delete", "external_send", "write", "read", "unknown")
_SEVERITY_ORDER = {"payment": 5, "delete": 4, "external_send": 3, "write": 2, "read": 1, "unknown": 0}


@dataclass
class LaneConfig:
    checkers: list[str] = dc_field(default_factory=list)
    sample_rate: float = 1.0
    sync: bool = False
    latency_budget_ms: int = 100
    evidence_tokens: int = 512


@dataclass
class RouterConfig:
    default: LaneConfig = dc_field(default_factory=LaneConfig)
    by_consequence: dict[str, LaneConfig] = dc_field(default_factory=dict)
    extractor: str = "rules"
    checker_config: dict[str, dict] = dc_field(default_factory=dict)
    weights: dict[str, float] = dc_field(default_factory=dict)
    threshold: float = 0.5
    thresholds_by_agent: dict[str, float] = dc_field(default_factory=dict)
    tolerances: Tolerances = dc_field(default_factory=Tolerances)
    path: str | None = None
    problems: list[str] = dc_field(default_factory=list)

    def lane(self, consequence: str) -> LaneConfig:
        return self.by_consequence.get(consequence, self.default)

    def threshold_for(self, agent_id: str | None) -> float:
        return self.thresholds_by_agent.get(agent_id or "", self.threshold)

    @classmethod
    def from_dict(cls, data: dict, *, path: str | None = None) -> "RouterConfig":
        root = data.get("detectr", data) if isinstance(data, dict) else {}
        config = cls(path=path)
        if not isinstance(root, dict):
            config.problems.append("top level must be a table")
            return config

        def lane(raw: dict, base: LaneConfig | None = None) -> LaneConfig:
            out = LaneConfig(**(base.__dict__ if base else {}))
            if "checkers" in raw:
                out.checkers = [str(c) for c in raw["checkers"]] if isinstance(raw["checkers"], list) else [str(raw["checkers"])]
            if "sample_rate" in raw:
                out.sample_rate = min(1.0, max(0.0, float(raw["sample_rate"])))
            if "sync" in raw:
                out.sync = bool(raw["sync"])
            if "latency_budget_ms" in raw:
                out.latency_budget_ms = int(raw["latency_budget_ms"])
            if "evidence_tokens" in raw:
                out.evidence_tokens = int(raw["evidence_tokens"])
            return out

        lanes = root.get("lanes") or {}
        if "default" in lanes and isinstance(lanes["default"], dict):
            config.default = lane(lanes["default"])
        if "latency_budget_ms" in root:
            config.default.latency_budget_ms = int(root["latency_budget_ms"])
        for name, raw in lanes.items():
            if name == "default" or not isinstance(raw, dict):
                continue
            if name not in CONSEQUENCE_CLASSES:
                config.problems.append(f"lanes.{name}: unknown consequence class; expected one of {CONSEQUENCE_CLASSES}")
                continue
            config.by_consequence[name] = lane(raw, config.default)
        config.extractor = str(root.get("extractor", "rules"))
        if config.extractor not in ("rules", "llm"):
            config.problems.append(f"extractor must be rules or llm, got {config.extractor!r}")
            config.extractor = "rules"
        checkers = root.get("checkers") or {}
        if isinstance(checkers, dict):
            config.checker_config = {str(k): dict(v) for k, v in checkers.items() if isinstance(v, dict)}
        weights = root.get("weights") or {}
        if isinstance(weights, dict):
            config.weights = {str(k): float(v) for k, v in weights.items()}
        if "threshold" in root:
            config.threshold = float(root["threshold"])
        thresholds = root.get("thresholds") or {}
        if isinstance(thresholds, dict):
            config.thresholds_by_agent = {str(k): float(v) for k, v in thresholds.items()}
        tol = root.get("tolerances") or {}
        if isinstance(tol, dict):
            from decimal import Decimal
            config.tolerances = Tolerances(
                money_abs=Decimal(str(tol.get("money_abs", "0.01"))), date_days=int(tol.get("date_days", 1)),
                status_synonyms=dict(tol["status_synonyms"]) if isinstance(tol.get("status_synonyms"), dict) else None,
            )
        return config

    @classmethod
    def load(cls, path: str | Path) -> "RouterConfig":
        target = Path(path)
        try:
            data = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            config = cls(path=str(target))
            config.problems.append(f"cannot read {target}: {exc}")
            return config
        return cls.from_dict(data, path=str(target))


def find_config(start: str | Path | None = None) -> Path | None:
    here = Path(start or ".").resolve()
    for folder in (here, *here.parents):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def consequence_class(ledger: Ledger, claim: Claim | None = None, *, registry: dict | None = None) -> str:
    """The highest side effect in play: of the claim's own tool call, else
    of every tool call in the trajectory. Side effects come from the trace
    (``side_effect`` recorded by the guard) or the registry's tool list."""
    classes: list[str] = []
    calls = [e for e in ledger.entries if e.kind == "tool_call"]
    if claim is not None and claim.source == "tool_call":
        calls = [e for e in calls if e.id == claim.entry_id] or calls
    registry_tools: dict[str, str] = {}
    for agent in (registry or {}).get("agents") or []:
        if ledger.agent_id and agent.get("id") not in (ledger.agent_id, agent.get("name")) and agent.get("name") != ledger.agent_id:
            continue
        for tool in agent.get("tools") or []:
            if isinstance(tool, dict) and tool.get("name"):
                effect = tool.get("side_effect") or tool.get("effect")
                if effect in CONSEQUENCE_CLASSES:
                    registry_tools[str(tool["name"])] = str(effect)
    for call in calls:
        effect = call.meta.get("side_effect") or registry_tools.get(call.tool_name or "")
        classes.append(effect if effect in CONSEQUENCE_CLASSES else "unknown")
    if not classes:
        return "unknown"
    return max(classes, key=lambda c: _SEVERITY_ORDER[c])


def sampled(claim_id: str, trajectory_id: str, rate: float) -> bool:
    """Deterministic sampling: the same claim is always in or always out."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha256(f"{trajectory_id}:{claim_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF < rate


@dataclass
class RunResult:
    layer0: list[Verdict]
    external: list[Verdict]
    evidence: dict[str, list[Evidence]]
    consequence: str
    demoted: list[str]
    skipped: list[str]
    warnings: list[str]
    timings_ms: dict[str, float]
    deferred_plan: list[tuple[str, str]]  # (checker id, claim id) left for the deferred lane


class Router:
    def __init__(self, config: RouterConfig | None = None, *, checkers: dict[str, Checker] | None = None,
                 clock: Callable[[], float] = time.perf_counter, loader: Callable[..., Checker] = load_checker) -> None:
        self.config = config or RouterConfig()
        self._checkers: dict[str, Checker] = dict(checkers or {})
        self._clock = clock
        self._loader = loader
        self.demoted: set[str] = set()
        self.unavailable: dict[str, str] = {}

    def checker(self, name: str) -> Checker | None:
        if name in self._checkers:
            return self._checkers[name]
        if name in self.unavailable:
            return None
        try:
            self._checkers[name] = self._loader(name, **self.config.checker_config.get(name, {}))
        except (CheckerUnavailable, KeyError, RuntimeError) as exc:
            self.unavailable[name] = str(exc)
            return None
        return self._checkers[name]

    def run(self, ledger: Ledger, claims: list[Claim], *, entries: list[LedgerEntry] | None = None, schema: dict | None = None,
            registry: dict | None = None, deferred: bool = True, question: str | None = None) -> RunResult:
        """Layer 0 on every claim, then external checkers per lane. With
        ``deferred=False`` only sync-capable checkers in sync lanes run and
        the rest is returned as a plan."""
        consequence = consequence_class(ledger, registry=registry)
        lane = self.config.lane(consequence)
        layer0 = run_layer0(ledger, claims, entries=entries, tol=self.config.tolerances, schema=schema)
        external: list[Verdict] = []
        evidence_by_claim: dict[str, list[Evidence]] = {}
        warnings: list[str] = []
        skipped: list[str] = []
        timings: dict[str, float] = {"layer0": 0.0}
        plan: list[tuple[str, str]] = []
        if question is None:
            first = next((e for e in ledger.entries if e.kind == "user_input" and e.content_captured), None)
            question = first.text_view if first else ""
        for name in lane.checkers:
            checker = self.checker(name)
            if checker is None:
                reason = self.unavailable.get(name, "unknown checker")
                if f"{name}: {reason}" not in warnings:
                    warnings.append(f"{name}: {reason}")
                skipped.append(name)
                continue
            manifest = checker.manifest
            if not getattr(manifest, "implemented", True):
                warnings.append(f"{name}: not implemented in this build")
                skipped.append(name)
                continue
            run_sync = lane.sync and manifest.sync_capable and name not in self.demoted
            for claim in claims:
                if claim.type not in manifest.claim_types or claim.source == "tool_call":
                    continue
                if not sampled(claim.id, ledger.trajectory_id, lane.sample_rate):
                    continue
                if not run_sync and not deferred:
                    plan.append((name, claim.id))
                    continue
                evidence = evidence_by_claim.get(claim.id)
                if evidence is None:
                    budget = min(lane.evidence_tokens, manifest.max_context_tokens or lane.evidence_tokens)
                    evidence = resolve_evidence(claim, ledger, entries=entries, token_budget=budget)
                    evidence_by_claim[claim.id] = evidence
                if manifest.requires_evidence and not evidence:
                    external.append(Verdict(claim.id, "unverifiable", None, "no_evidence", [], "no evidence could be resolved", confidence=0.0, checker=name))
                    continue
                started = self._clock()
                try:
                    try:
                        verdict = checker.check(claim, evidence, question=question)  # type: ignore[call-arg]
                    except TypeError:
                        verdict = checker.check(claim, evidence)
                except Exception as exc:  # noqa: BLE001 - a checker failure is unverifiable, never a crash
                    verdict = Verdict(claim.id, "unverifiable", None, "checker_error", [], f"{name} failed: {type(exc).__name__}: {exc}", confidence=0.0, checker=name)
                elapsed = (self._clock() - started) * 1000.0
                timings[name] = timings.get(name, 0.0) + elapsed
                verdict.checker = name
                external.append(verdict)
                if run_sync and elapsed > lane.latency_budget_ms and name not in self.demoted:
                    self.demoted.add(name)
                    warnings.append(f"{name}: {elapsed:.0f} ms exceeded the {lane.latency_budget_ms} ms sync budget; demoted to the deferred lane")
                    run_sync = False
                    if not deferred:
                        # The remaining claims for this checker move to the plan.
                        continue
        return RunResult(layer0, external, evidence_by_claim, consequence, sorted(self.demoted), skipped, warnings, timings, plan)

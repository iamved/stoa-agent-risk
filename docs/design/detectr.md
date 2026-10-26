# Hallucination DetectR: plan and design

Status: built 2026-10-25 (core). User guide: `docs/detectr.md`. Core only. No policy, graph or dashboard
work in this build; DetectR writes findings and metrics those features read
later.

## What it is

A hallucination is a property of a claim, relative to a source of truth, at a
point in a trajectory. DetectR rebuilds what the agent saw (the ledger),
splits what the agent said and did into claims, checks each claim against the
ledger with deterministic rules, optionally asks text-grounding models about
text claims, fuses the results, and emits findings in the existing finding
shape plus metrics as JSON.

## Where each piece lands

| Deliverable | Module | Builds on |
|---|---|---|
| Ledger and the three builders | `stoa/detectr/ledger.py` | `runtime.reader.TraceReader`, `runtime.spans`, OTel GenAI span JSON, LangGraph checkpoint JSON |
| Claims | `stoa/detectr/claims.py` | `redaction.redact_line` for excerpts |
| Layer 0 rules | `stoa/detectr/layer0.py` | `rules.RULES`, `models.finding_fingerprint`, the RT finding shape in `runtime.rt_rules` |
| Evidence resolution | `stoa/detectr/evidence.py` | ledger value index |
| Checkers | `stoa/detectr/checkers/` | entry points `stoa.detectr.checkers`; extras `hallucination`, `hallucination-hhem`, `hallucination-judge` |
| Routing, fusion, calibration | `stoa/detectr/router.py`, `fusion.py`, `calibration.py` | `stoa.detectr.toml`, registry side effects for consequence class |
| Metrics | `stoa/detectr/metrics.py` | `stoa-detectr-metrics/0.1` JSON |
| CLI | `stoa detectr check / ledger / metrics / bench` in `cli.py` | same pattern as `stoa policy` |
| SDK content capture | `runtime/__init__.py` | additive attrs under `capture_content=True`, trace schema stays 1.1 |
| Fixtures | `tests/detectr/fixtures/` | deterministic generator, committed JSON, currency test |

## Where the brief and the code disagree, and what this build does

1. Rule ids. RT006, RT007 and RT008 already exist (undeclared tool, money
   action without approval, unknown model or integration). DetectR takes
   RT009 to RT013: phantom action, result fidelity, hallucinated promise,
   argument grounding, stale grounding. Category `hallucination`, never
   gateable in this build.
2. Content. The SDK records no prompt, response or payload text unless
   `configure(capture_content=True)`. A ledger built from a redacted trace
   has hashes and lengths only; every claim is then `unverifiable` and the
   report says why. This build adds content recording to the SDK, opt in
   only: `model_call().record(prompt=, response=, system=)`, guarded tool
   arguments and results, `session.user_input()` and `session.retrieved()`.
   Strings still pass through the customer's redaction hook.
3. Risk report. There is no `stoa-risk-report/1.2` and no
   `hallucination_exposure` block. Metrics ship as their own JSON document.
   Putting them into the dashboard envelope is a later build.
4. Config format. Stoa uses TOML everywhere (policy, declarations, config),
   so the router reads `stoa.detectr.toml`, not YAML.

## Rules

| Id | Fires when | Label |
|---|---|---|
| RT009 Phantom action | The agent says it did something and no matching tool call with a successful result precedes the claim | contradicted |
| RT010 Result fidelity | A value the agent states conflicts with the field the tool returned | contradicted, with numerical, identifier, temporal or status |
| RT011 Hallucinated promise | A commitment has no supporting tool result, instruction or approval | unsupported |
| RT012 Argument grounding | A tool argument traces to nothing the agent saw, or conflicts with what it saw | unsupported or contradicted |
| RT013 Stale grounding | A claim or argument traces only to an entry a later entry superseded | contradicted, stale |

Every verdict carries the ledger entry ids it used, so a finding can be
audited back to the trace.

## Order of work

Ledger builders, then claims with their test set, then Layer 0 with the
fixture set, then evidence resolution, then the LettuceDetect adapter, then
router and fusion, then metrics, then bench. One commit per step.

## Not in this build

Policy conditions, graph overlay, dashboard screens, world-knowledge
checking, resampling consistency (stub only), fine-tuning, an adjudication
UI, and writing anything into the registry or envelope.

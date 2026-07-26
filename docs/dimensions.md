# Dimension exposure

Every agent candidate is assessed across a taxonomy of risk **dimensions** and
rendered as a Dimension Exposure Matrix at the top of the HTML report. The
default taxonomy (`stoa-aiuc-8`, v2.0) has eight dimensions, grouped under the
six standard categories of [AIUC-1](https://www.aiuc-1.com/) — the AI agent
trust standard (Data & Privacy, Security, Safety, Reliability, Accountability,
Society). **Five dimensions are assessable statically, three are proxy signals
flagged for runtime follow-up** — all with line-level evidence.

Grouping under AIUC-1's categories is a display header, not a certification
claim — AIUC-1 certification requires their accredited-auditor process. It's
also not the complete AIUC-1 picture: the technical dimensions below only
cover what static analysis can score. The parts of AIUC-1 that require
governance documentation or third-party testing evidence (most of Safety,
Accountability, and Society) live in `stoa-declared.toml` and surface in
[`stoa export --assurance`](assurance-export.md) instead, under the same six
group letters plus a seventh, Stoa-only group for insurance-specific exposure.

## The eight default dimensions

| Group | Dimension | Assessability | What static analysis sees |
|---|---|---|---|
| A — Data & Privacy | Boundary leakage | strong | sensitive data leaving via model calls or egress |
| B — Security | Mandate overreach | strong | reach beyond declared scope |
| B — Security | Injection & tamper surface | partial | prompt-injection / supply-chain surface (robustness is runtime) |
| B — Security | Control coverage gap | partial | auth / validation / rate-limit / observability |
| C — Safety | Unreviewed high-impact action | strong | high-impact actions without an observed approval |
| D — Reliability | Output fidelity | partial | unsafe model-output handling (correctness is runtime) |
| D — Reliability | Conduct variability | **proxy** | only config signals (e.g. unpinned sampling) |
| D — Reliability | Dependency drift | **proxy** | only upstream-pin signals |

Notice groups **E (Accountability)** and **F (Society)** have no scanned
dimension — that's deliberate, not a gap to be padded. A static code scan has
no way to assess vendor due diligence or societal-scale misuse risk; those
live entirely in the declared/ingested layers of the assurance packet.

**Assessability tiers** cap what Stoa may claim. A `proxy` dimension can never
render `elevated` — it is capped at `moderate`, enforced by a property test.
Stoa must never imply it measured behavior it only saw a config signal for.

## Scoring (deterministic)

Per agent, per dimension:

```
score = min(100,
    Σ finding_weight(severity, confidence)   # e.g. critical×high-conf = 40
  + Σ capability_weight                       # each mapped capability contributes
  − Σ control_credit)                          # observed controls subtract (floor 0)
```

Buckets: `0 → none-observed · 1–24 → low · 25–54 → moderate · ≥55 → elevated`,
then the proxy cap applies. Weights live in `data/dimensions.toml` — changing
them bumps the taxonomy version, so score changes are always attributable to a
code change or a declared taxonomy change, never a silent recalibration.

**Observed controls** (approval, authentication, validation, rate-limit,
observability, deterministic sampling, pinned model) *subtract* exposure — the
one place Stoa reports good news, always phrased as "observed".

**Suppressed findings contribute zero** but remain listed in the drill-down.

## Exposure values

`elevated | moderate | low | none-observed | not-assessable`. Never "safe",
"covered", or "compliant".

## Custom taxonomies

```toml
# stoa.toml
[dimensions]
taxonomy = ".stoa/dimensions.toml"   # replaces the default
```

A custom file declares its own `[[dimensions]]` and `[rule_dimensions]` /
`[capability_dimensions]` maps. Any rule left unmapped falls into a reserved
`unclassified` dimension that always renders — a custom taxonomy cannot silently
drop findings from the dimensional view. The taxonomy `id`+`version` is embedded
in every registry, so `stoa diff` across mismatched taxonomies exits 2 rather
than producing a misleading comparison.

Flags: `--no-dimensions` (skip assessment + matrix), `--taxonomy PATH`.

## Machine interface

The registry's per-agent `dimension_assessment` block and the top-level
`dimension_summary` are the machine interface: *"read stoa-registry.json and
address all elevated boundary-leakage contributors"* is a valid agent
instruction with zero extra tooling. SARIF results carry a `stoa-dim:<dimension>`
tag so GitHub Code Scanning can filter by dimension. Every dimension entry also
carries `group` (one of `A`–`D`, or empty for a custom taxonomy that doesn't
use groups).

## What Stoa says / never says

| Stoa says | Stoa never says |
|---|---|
| "Exposure observed" / "none observed" | "Covered" / "protected" / "compliant" |
| "Proxy signals only — runtime evaluation required" | "Behaviorally stable" / "drift-free" |
| "Controls observed: interrupt gate" | "Risk mitigated" |
| "Assessed across 8 dimensions: 5 direct, 3 proxy" | "Full coverage across 8 risk dimensions" |

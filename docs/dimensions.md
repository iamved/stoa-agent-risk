# Dimension exposure

v0.2 assesses every agent candidate across a taxonomy of risk **dimensions** and
renders a Dimension Exposure Matrix at the top of the HTML report. The default
taxonomy has eight dimensions; **five are assessable statically, three are proxy
signals flagged for runtime follow-up** — all with line-level evidence.

## The eight default dimensions

| Dimension | Assessability | What static analysis sees |
|---|---|---|
| Scope violation | strong | reach beyond intended scope |
| Data exfiltration | strong | sensitive data leaving via model calls or egress |
| Unauthorized action | strong | high-impact actions without an observed approval |
| Output integrity | partial | unsafe model-output handling (correctness is runtime) |
| Adversarial manipulation | partial | prompt-injection / supply-chain surface (robustness is runtime) |
| Behavioral instability | **proxy** | only config signals (e.g. unpinned sampling) |
| Model drift | **proxy** | only upstream-pin signals |
| Operational control | partial | auth / validation / rate-limit / observability |

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
address all elevated data-exfiltration contributors"* is a valid agent
instruction with zero extra tooling. SARIF results carry a `stoa-dim:<dimension>`
tag so GitHub Code Scanning can filter by dimension.

## What Stoa says / never says

| Stoa says | Stoa never says |
|---|---|
| "Exposure observed" / "none observed" | "Covered" / "protected" / "compliant" |
| "Proxy signals only — runtime evaluation required" | "Behaviorally stable" / "drift-free" |
| "Controls observed: interrupt gate" | "Risk mitigated" |
| "Assessed across 8 dimensions: 5 direct, 3 proxy" | "Full coverage across 8 risk dimensions" |

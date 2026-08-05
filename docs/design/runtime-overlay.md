# Design: Runtime Trace Overlay (the `observed` evidence layer)

Status: **implemented** (design approved as drafted; two deviations noted
in the final report — unknown `[runtime]` config keys are *ignored* to
match existing `load_config` behavior rather than warned, and `stoa diff`'s
dimension-delta additionally excludes runtime-tier entries, a leak the
Meridian e2e caught).
Baseline regression contract: **349 passed, 0 skipped, 0 xfailed** (recorded
before any change; the suite stayed green after every phase).

Stoa today has two evidence layers: **scanned** (static analysis) and
**declared** (`stoa-declared.toml`), plus **ingested** pointers. The codebase
reserves slots for a third — **observed** — in five places, verified in code:

| Reserved slot | Where | Verified |
|---|---|---|
| `"observed"` edge provenance | `graph_model.py:35` — `PROVENANCES = ("declared", "observed")`, "never emitted by this module" | ✅ |
| `"delegates"` edge kind | `graph_model.py:34` + module docstring ("for if and when that data exists") | ✅ |
| Assurance Area 18 (Claims evidence) | `assurance.py:353` — all rows `not_provided`, note names the "future runtime-trace overlay ('observed' provenance)" | ✅ |
| Assurance Area 12 (Monitoring) | `assurance.py:320` — ingested pointers + CTRL004 only | ✅ |
| `liveness_state` reserved registry field | SCHEMA.md "Reserved field names": *"Runtime-derived Active / Idle / Deprecated status"* | ✅ |

Two more implicit slots found during recon:

- `dimensions.py:224` already handles an assessability value
  `"runtime-required"` → forces `not-assessable`. No shipped dimension uses
  it; it demonstrates the intended extension mechanism: **assessability is
  per-entry data, so a new tier slots in without touching the cap logic.**
- `VALID_RULE_ID = ^[A-Z]{2,5}\d{3}$` (`rules.py:286`) — `RT001` is a valid
  rule id with zero regex changes.

Corrections to the task brief, from code: the registry schema is currently
**1.3** (not 1.2; 0.4.0 bumped it), the assurance packet is
`assurance-packet/1.1`, and there are **two** proxy dimensions
(`conduct-variability`, `dependency-drift`) — the "runtime half" of
injection-tamper-surface and output-fidelity is docs prose about their
`partial` tier, not a third proxy dimension. This design upgrades exactly the
two proxy dimensions.

---

## 1. Architecture

```
customer agent process                       CI / analyst machine
┌──────────────────────────┐                ┌─────────────────────────────────┐
│ agent code               │                │ stoa runtime analyze TRACES/    │
│  + @stoa_trace /         │   JSONL        │   → stoa-runtime.json           │
│    with stoa_span(...)   │  append-only   │   (+ --registry: RT findings,   │
│                          │ ────────────►  │    correlation, no-evidence)    │
│ stoa.runtime SDK         │ stoa-traces/   │                                 │
│  (buffered, redacted,    │   *.jsonl      │ stoa runtime baseline / drift   │
│   no-op on failure)      │  customer FS   │ stoa runtime merge → enriched   │
└──────────────────────────┘   only, ever   │   registry (runtime_evidence,   │
                                            │   observed graph, Areas 12/18)  │
                                            └─────────────────────────────────┘
```

Nothing in the left box ever talks to a network endpoint unless the customer
explicitly configures their own OTLP collector (deferred — see §10). Nothing
in the right box reads anything but local files. Shadow mode throughout: the
SDK observes, never intercepts or blocks.

## 2. Module layout

```
src/stoa/runtime/
  __init__.py     # public SDK surface: configure(), stoa_trace, stoa_span
  spans.py        # span records, kinds, stoa-trace/1.0 constants, validation
  exporter.py     # JSONLExporter: buffer thread, size rotation, warn-once no-op
  reader.py       # streaming trace reader — generator, fail-open per line
  analysis.py     # analyze/baseline/drift as pure functions over span streams
  rt_rules.py     # RT001–RT005 detectors (mirrors contradiction_rules.py shape)
  merge.py        # registry enrichment: runtime_evidence, liveness_state,
                  # RT findings, dimension runtime-tier overlay
```

`stoa scan` imports **nothing** from `stoa.runtime`. The CLI lazy-imports it
inside the `runtime` subcommand handler, so a broken/absent optional extra
can never affect `scan`/`diff`/`graph`/`export`. The SDK itself is
**stdlib-only** (threading, queue, json, hashlib, contextvars, uuid) — the
`[runtime]` pip extra is reserved for the deferred OTLP exporter, not needed
for JSONL.

## 3. Trace schema — `stoa-trace/1.0`

JSONL, one record per line. Line 1 of every file is a header record;
readers tolerate a missing header (warn + assume current version, fail-open).

```jsonl
{"kind": "header", "schema": "stoa-trace/1.0", "sdk_version": "0.5.0", "redaction": "redacted"}
{"kind": "llm_call", "trace_id": "…", "span_id": "…", "parent_span_id": "…",
 "agent_id": "a09ff38687e9", "start_ts": "2026-08-01T12:00:00.123Z", "end_ts": "…",
 "status": "ok", "provider": "openai", "model": "gpt-4o",
 "attrs": {"prompt_sha256": "…", "prompt_chars": 812, "response_chars": 214}}
{"kind": "action", "…": "…", "capability": "payment_access", "integration": "stripe",
 "amount": {"amount": 1200, "currency": "USD"}, "approval_span_id": "…"}
{"kind": "delegation", "…": "…", "from_agent_id": "…", "to_agent_id": "…"}
```

- `kind` ∈ `agent_run | llm_call | tool_call | action | approval | retrieval
  | delegation`.
- `capability` / `integration` / `provider` reuse the scanner's existing ids
  from `rules.CAPABILITY_PATTERNS` / `INTEGRATION_PATTERNS` /
  `PROVIDER_PATTERNS` verbatim — `spans.py` imports those key sets for
  validation; unknown values are recorded but flagged
  `"vocabulary": "custom"` so analysis can report them without inventing a
  parallel taxonomy.
- `agent_id` is the scanned 12-hex id when supplied; otherwise the SDK
  records `agent_hint: {"module", "qualname"}` and analysis lists the span
  under `unmatched_agents` with suggested registry matches.
- `approval` spans carry `{"approved_by", "method"}`; `action` spans may
  reference `approval_span_id`.
- **Redaction is the default and is recorded per file**: `attrs` carries
  shapes/hashes/lengths only. `capture_content=True` (per-span opt-in) adds
  a `content` attr and flips the span's `redaction` field to `"content"`,
  optionally routed through a caller-supplied redaction hook first. Analysis
  artifacts always state which evidence quality they had.
- Reserved (documented, never emitted in 1.0): `enforcement`, `session_id`,
  `cost`.
- Timestamps are ISO-8601 UTC. Fine inside trace files (constraint 4); all
  derived artifacts keep them out of the body.

## 4. SDK behavior (`stoa.runtime`)

- `configure(trace_dir=…, agent_id=…, capture_content=False, redaction_hook=None,
  max_file_bytes=16MB)` — also configurable via `[runtime]` in `stoa.toml`
  and env `STOA_TRACE_DIR`. No config → SDK is dormant (decorators become
  pass-throughs).
- `@stoa_trace(agent_id="a09ff38687e9", kind="agent_run")` wraps a callable;
  `with stoa_span(kind="tool_call", capability="payment_access", …)` for
  finer scopes. Parent/child links via `contextvars` (async-safe).
- **Hot path:** span dict → `queue.put_nowait` → background thread batches
  and appends JSONL. Queue full → drop span, increment a dropped counter
  (flushed into the next header), warn once. Write error (read-only FS,
  etc.) → warn once via `warnings.warn`, become a permanent no-op.
  Instrumentation must never raise into customer code — every public entry
  point is wrapped.
- Rotation: `stoa-traces/trace-<pid>-<seq>.jsonl`, new file past
  `max_file_bytes`.
- Performance budget (smoke-tested): ≤ 50 µs median per span on the hot path
  (dict build + queue put); analysis streams ≥100k spans without slurping.

## 5. Analysis CLI — `stoa runtime …`

New top-level subcommand group; existing commands untouched. Exit codes
mirror `stoa diff`: 0 ok, 1 gated (only with an explicit `--fail-on-*`),
2 bad args/version mismatch, 3 internal.

- **`stoa runtime analyze TRACES_DIR [--registry stoa-registry.json] [--out stoa-runtime.json]`**
  → `runtime-analysis/1.0`. Header: generated-at, stoa version, files read,
  parse-warning count (wall-clock here only). Body (deterministic given
  identical traces): observation window (min/max span ts — derived from
  input, not the clock), per-agent summary (span counts by kind,
  capabilities/integrations/providers/models observed, approval firing rate
  on high-impact actions, observed amounts vs declared `economic_authority`,
  error rate, redaction quality), `unmatched_agents` (with suggested
  registry matches by module/symbol similarity — this is the `stoa runtime
  map` guidance, also printed by a thin `map` subcommand), and
  `no_runtime_evidence` (registry agents with zero spans — explicit, never
  dropped). With `--registry`, also emits RT findings (§7).
- **`stoa runtime baseline TRACES_DIR --out .stoa/baseline.json`**
  → `runtime-baseline/1.0`, committed and reviewed like
  `.stoa/approvals.toml`. Per-agent distributions: span-kind counts,
  capability/integration counts, approval rate, totals, window.
- **`stoa runtime drift TRACES_DIR --baseline .stoa/baseline.json [--registry …] [--fail-on-drift high|medium|info]`**
  Drift classes (thresholds in `[runtime.drift]`, defaults shown):
  - **high** — high-impact capability observed, absent from baseline AND
    absent from the static registry; approval rate on a high-impact path
    drops by ≥ `approval_drop` (0.10) vs baseline; observed amount exceeds
    declared `max_per_action`, or window aggregate exceeds `daily_aggregate`.
  - **medium** — new non-high-impact capability/integration observed; or a
    per-category frequency-ratio shift: category rate now vs baseline rate
    exceeds `ratio_threshold` (3.0) in either direction with at least
    `min_count` (20) observations now. Deliberately simple and explainable —
    two numbers a reviewer can recompute by hand.
  - **info** — baseline capability no longer observed.
  Report-only by default (shadow mode); gating only via `--fail-on-drift`.
- **`stoa runtime merge TRACES_DIR --registry stoa-registry.json [--out enriched.json]`**
  Registry enrichment (§6). Never modifies in place unless `--in-place`.

Fail-open everywhere: unreadable file / bad JSON line / unknown schema
version → counted warning, line skipped, exit 0 (unless gating requested and
the gate itself trips). Zero parseable spans → explicit "no runtime
evidence" output, exit 0, never a crash.

## 6. Registry, graph, report integration

**Registry → schema 1.4** (additive; a scan with no runtime merge serializes
byte-identically to 1.3 apart from `schema_version`):

- Per-agent `runtime_evidence` (only via `merge`): `{window: {start, end},
  span_count, observed_capabilities, observed_integrations,
  observed_providers, observed_models, approval_rate_high_impact,
  error_rate, max_observed_amount, evidence_quality: "redacted"|"content",
  trace_files: [names]}`.
- Per-agent `liveness_state` — **fills the reserved field**: `"active"`
  (spans in window) / `"idle"` (registry agent, zero spans). Only emitted by
  merge; plain scans never emit it, preserving today's output.
- On RT findings only: `trace_ref: {file, line, span_id}` — the trace-side
  evidence pointer, sibling to DECL's `declared_ref`.

**Graph.** `build_graph()` stays pure and untouched. New
`overlay_runtime(graph, analysis) -> Graph` in `stoa.runtime.merge`:

- Reading the reserved design (`PROVENANCES` is a single-valued enum on the
  edge = the edge's *origin*): edges that exist **only** because of traces
  (all `delegates` edges; capability/integration edges never seen statically)
  get `provenance="observed"`. A statically-declared edge corroborated by
  traces keeps `provenance="declared"` and gains an additive
  `observed: true` flag (serialized only when true). This preserves the enum
  and still distinguishes corroboration — documented in the module docstring
  replacing the "never emitted" note.
- HTML report: observed edges render solid, declared-only dashed, via the
  byte-fixed glue script (its CSP hash is computed at import time from
  content, so the hash-pinning model is untouched; runtime data continues to
  enter through the non-executing JSON tag).

**`stoa diff`:** excludes `runtime_evidence`, `liveness_state`, and
RT-family findings from comparison unconditionally (documented, tested) —
runtime data varies run to run and must not create phantom drift in code
diffs. No new flag in v1.

## 7. RT rule family (`rt_rules.py`, registered in `RULES`)

Registered exactly like existing rules (RuleSpec entries → config
validation, suppression ids, docs table all work). Category `runtime`.
**Gates? no — all five, v1 shadow mode**; the only runtime gate is
`runtime drift --fail-on-drift`, which is opt-in and separate.

| Rule | Sev | Fires when | Evidence pair |
|---|---|---|---|
| RT001 | critical | declared `recommend_only`/`human_approved`, but ≥1 high-impact action span with no linked approval span | `trace_ref` + `declared_ref` |
| RT002 | high | observed amount > declared `max_per_action`, or window sum > `daily_aggregate` | `trace_ref` + `declared_ref` |
| RT003 | high | observed capability absent from both static registry and declarations | `trace_ref` + registry field ref |
| RT004 | medium | declared production + monitoring evidence declared, but zero spans for the agent in window | declarations refs + window statement |
| RT005 | info | static `human_approved` + approval spans observed on 100% of high-impact actions | `trace_ref` + autonomy signal — the one good-news rule, phrased "observed" |

Suppression: `# stoa: ignore[RT00x]` works where a finding is code-anchored;
trace-anchored findings suppress via config
(`[runtime] suppress = ["RT002:a09ff38687e9"]`) — suppressed findings stay
counted and listed, never dropped (house rule). One docs page per rule.

## 8. Dimension runtime tier

New assessability value `runtime`, used **only** by the merge overlay and
only for `conduct-variability` and `dependency-drift`, only for agents with
runtime evidence covering the window:

- The merged entry's `assessability` becomes `"runtime"`, gains
  `evidence_window: {start, end, span_count}` (non-empty, enforced by a new
  property test), and its statement reads e.g. *"Assessed from traces:
  2026-07-18 → 2026-08-01, 12,431 spans."*
- Re-bucketing from observed signals (simple, documented, thresholds
  configurable under `[runtime.dimensions]`): dependency-drift — elevated if
  >1 distinct model id observed for one (agent, provider) pair in-window;
  low if a single dated-pinned id; moderate otherwise. Conduct-variability —
  elevated if error rate on high-impact spans ≥ 0.10 or the approval rate
  contradicts a declared human gate; moderate if error rate ≥ 0.02; else low.
- **The existing proxy cap and its property test are untouched**: entries
  still labeled `proxy` (no runtime evidence) remain capped by the exact
  same code path; the invariant holds by construction because runtime-tier
  entries are no longer labeled `proxy`. A parallel property test pins the
  new invariant (runtime tier ⇒ non-empty evidence window).
- No runtime evidence ⇒ the overlay never runs ⇒ byte-for-byte today's
  output.

## 9. Assurance packet → `assurance-packet/1.2`

- New status/glyph `observed` (📡) joins scanned/declared/ingested/
  not_provided.
- **Area 18** — populated from a merged registry: RT findings, drift events,
  and the approval-gate summary as `observed` rows with trace refs. No
  runtime data → `not_provided` rows exactly as today.
- **Area 12** — adds an `observed` row per covered agent (window, span
  count) beside the existing ingested pointers and CTRL004 row.
- Without runtime data the packet is byte-identical to today **apart from
  the schema string** — the same precedent SCHEMA.md already sets for
  registry minor bumps ("byte-identically … apart from `schema_version`").
- `TODO(assurance-sign)` untouched. Future note: a signed packet would cover
  runtime evidence by hashing the trace files' sha256s into the signed
  header, making the observed rows tamper-evident without shipping traces.

## 10. Deferred, explicitly

- **OTLP exporter + collector querying** — deferred to a follow-up. The
  `stoa.*` attribute semantic conventions are documented *now* (in
  `docs/runtime.md`) so the contract is fixed; the `[runtime]` pip extra is
  declared but empty-of-behavior until then; `exporter = "otlp"` in config
  produces a clear "not yet implemented, JSONL only" ConfigError. File-based
  first, per spec.
- **Framework auto-instrumentation** (`stoa.runtime.integrations.*`) —
  deferred; decorator + context manager cover v1. Documented.
- **Enforcement** — out of scope entirely (constraint 7); `enforcement` is a
  reserved span field only.

## 11. Config

```toml
[runtime]                    # absence = feature fully dormant
trace_dir = "stoa-traces"
redaction = "redacted"       # "redacted" | "content"
exporter = "jsonl"           # "otlp" reserved, errors clearly in v1
suppress = []                # e.g. ["RT002:a09ff38687e9"]

[runtime.drift]
ratio_threshold = 3.0
min_count = 20
approval_drop = 0.10

[runtime.dimensions]
error_rate_elevated = 0.10
error_rate_moderate = 0.02
```

`stoa init runtime` scaffolds this section plus a minimal instrumentation
example file. Unknown keys warn (forward-compatible), invalid values raise
`ConfigError` (exit 2) — matching `load_config`'s existing strictness.

## 12. What does NOT change

- `stoa scan` output: byte-for-byte identical (schema string included —
  scan never emits 1.4 fields, and the version constant only changes with
  the registry additions, documented in SCHEMA.md).
  *(Decision for review: bump `SCHEMA_VERSION` to 1.4 globally — meaning
  every new scan says 1.4 with no other difference, the documented
  precedent — or emit 1.4 only from `merge`. Proposal: global bump, matching
  how 1.1→1.3 were done.)*
- `stoa diff`, `graph`, `export --assurance` on registries without runtime
  data: identical output (packet schema string aside).
- Every existing rule, severity, gate, autonomy inference, proxy cap,
  determinism, redaction, CSP hash-pinning, dependency set of the core
  install, and the zero-telemetry posture.
- All 349 existing tests: expected to pass unmodified. Any exception (e.g. a
  CLI help-text snapshot) will be individually justified in the final
  report.

## 13. Test plan

Per-phase, all green before advancing: trace schema round-trip; SDK no-op
degradation (read-only dir) and never-raises wrapper; redaction default
(assert no content by default, content only with opt-in); JSONL rotation;
reader fail-open on corrupt lines; `analyze` determinism (identical traces →
identical body bytes); baseline/drift golden fixtures covering every drift
class and thresholds; each RT rule positive + negative; merge additivity
(no-runtime registry byte-identical through scan/diff/export); diff ignores
runtime fields; graph observed/delegates edges + report CSP intact;
Areas 12/18 populated and absent; proxy-cap property test untouched + new
runtime-tier property test; CLI exit codes 0/1/2/3; Meridian synthetic trace
fixture (small, deterministic, hand-auditable); performance smoke (span
overhead budget, 100k-span streaming).

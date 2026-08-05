# Runtime trace overlay

Stoa's static layer answers *what the code can do*. Declarations answer
*what humans say it should do*. The runtime overlay adds the third layer the
schema has reserved slots for since 1.0: **what agents were actually
observed doing** — and cross-checks all three against each other.

v1 is **shadow mode**: the SDK observes, it never blocks, gates, or alters
live agent behavior. Enforcement is a future milestone; the only reserved
scaffolding for it is a documented span field.

## The workflow, end to end

Six steps, from nothing to a runtime-evidenced assurance packet. Each step
is independently useful — stop at any point and everything before it still
works.

**1. Scaffold.** `stoa init runtime` appends a `[runtime]` section to
`stoa.toml` and writes `stoa_runtime_example.py`. Nothing activates until
an agent process calls `configure()`.

**2. Instrument.** Add `configure(trace_dir=…, agent_id=…)` plus
`@stoa_trace` / `stoa_span` around agent runs, model calls, tool calls, and
side-effecting actions. Get the `agent_id` from `stoa-registry.json` (or
skip it and let step 3's `map` suggest one). Deploy as normal — the SDK is
µs-cheap, redact-by-default, and becomes a no-op rather than ever crashing
the agent.

**3. Analyze.** After the agents have run for a while:

```bash
stoa runtime analyze stoa-traces --registry stoa-registry.json
stoa runtime map stoa-traces --registry stoa-registry.json   # if ids were omitted
```

Read `stoa-runtime.json`: who actually did what, approval rates on
high-impact actions, observed amounts, and — explicitly — which spans
matched no agent and which agents produced no spans.

**4. Baseline, once behavior looks right.**

```bash
stoa runtime baseline stoa-traces --out .stoa/baseline.json
git add .stoa/baseline.json    # reviewed like code, like approvals
```

**5. Watch for drift, on a schedule.** A cron/CI job over each new trace
window:

```bash
stoa runtime drift fresh-traces --baseline .stoa/baseline.json \
    --registry stoa-registry.json --fail-on-drift high
```

Report-only without `--fail-on-drift`; with it, exit 1 on e.g. a
high-impact capability nothing on paper had, an approval-rate drop, or an
amount over declared economic authority. When drift is intentional,
regenerate and re-review the baseline — the same motion as `stoa approve`.

**6. Merge for the evidence artifacts.** When you want the runtime layer in
the registry, report, graph, and assurance packet:

```bash
stoa scan . --with-runtime stoa-traces      # scan + enrich in one pass
# or enrich an existing registry:
stoa runtime merge stoa-traces --registry stoa-registry.json --out enriched.json
stoa export --assurance enriched.json --format md
```

This is where RT001–RT005 fire, `liveness_state` fills, observed/delegates
edges draw, the proxy dimensions upgrade to the `runtime` tier, and packet
Areas 12/18 populate.

A typical steady state: steps 3+5 run continuously (cheap, local, gate
only if opted in); step 6 runs when producing evidence for a review, a
customer questionnaire, or an underwriter.

**Zero telemetry, restated for this layer:** traces are JSONL files on the
customer's own filesystem. The SDK contains no network code. Analysis reads
local files. Not one byte of trace or analysis data ever leaves the
customer's infrastructure.

## Instrument (`stoa.runtime`)

```python
from stoa import runtime as stoa_rt

stoa_rt.configure(trace_dir="stoa-traces", agent_id="a09ff38687e9")

@stoa_rt.stoa_trace(kind="agent_run")
def handle(ticket): ...

with stoa_rt.stoa_span("action", capability="payment_access",
                       integration="stripe", amount=120.0, currency="USD",
                       approval_span_id=approval_id):
    stripe.Refund.create(...)
```

- The default JSONL path is **stdlib-only** — no new dependencies; the
  `[runtime]` pip extra is reserved for the deferred OTLP exporter.
- `capability` / `integration` / `provider` reuse the scanner's exact ids —
  never a parallel vocabulary. Custom values are recorded but flagged.
- Unconfigured, every decorator is a pass-through. An unwritable trace
  directory warns **once** and the SDK becomes a no-op: instrumentation
  must never crash or slow the customer's agent (hot path is a queue
  append; a background thread does the I/O; a full queue drops spans and
  counts the drops into the next file header).
- `stoa init runtime` scaffolds the config and a working example.

### Privacy: redact-by-default

Prompt/response bodies and tool payloads are **never recorded** unless you
opt in. By default every string attr becomes a SHA-256 hash plus a length —
shapes, not content. Opting in (`capture_content=True`) flips the span's
`redaction` flag to `"content"` (so downstream analysis states what
evidence quality it had) and routes text through your `redaction_hook`
first if you set one.

### Deferred, explicitly

The OTLP exporter and collector querying are deferred (file-based first);
`exporter = "otlp"` errors clearly today. The attribute contract is fixed
now so nothing changes shape later: spans map to OTel with `stoa.agent_id`,
`stoa.kind`, `stoa.capability`, `stoa.integration`, `stoa.provider`,
`stoa.model`, `stoa.amount`, `stoa.currency`, `stoa.approval_span_id`,
`stoa.redaction` attributes — pointed only at the customer's own collector,
never a default remote URL. Framework auto-instrumentation
(`stoa.runtime.integrations.*`) is likewise deferred.

## Analyze, baseline, drift

```bash
stoa runtime analyze stoa-traces --registry stoa-registry.json   # → stoa-runtime.json
stoa runtime map     stoa-traces --registry stoa-registry.json   # id suggestions
stoa runtime baseline stoa-traces --out .stoa/baseline.json      # commit it
stoa runtime drift   stoa-traces --baseline .stoa/baseline.json [--fail-on-drift high]
stoa runtime merge   stoa-traces --registry stoa-registry.json --out enriched.json
stoa scan . --with-runtime stoa-traces                           # scan + merge in one pass
```

Every artifact keeps the house determinism rule: identical trace input →
byte-identical body; wall-clock lives only in header blocks. The
observation window is derived from span timestamps, not the clock. Spans
that can't be tied to a registry agent land in `unmatched_agents` with
suggested matches — never silently dropped; registry agents with zero spans
are explicitly `no-runtime-evidence`. Missing or corrupt trace data warns
loudly and degrades gracefully (exit 0 unless you opted into gating).

Drift classes mirror `stoa diff`'s philosophy — report-only unless
`--fail-on-drift` is passed:

| Class | Fires on |
|---|---|
| high | high-impact capability absent from baseline *and* static registry; approval-rate drop ≥ `approval_drop`; observed amount over declared `economic_authority` |
| medium | new non-high-impact capability/integration; frequency-ratio shift (`ratio_threshold`× either way, with ≥ `min_count` observations — two numbers a reviewer can recompute by hand) |
| info | baseline capability no longer observed |

Thresholds live in `stoa.toml [runtime.drift]`. The baseline is committed
and reviewed like `.stoa/approvals.toml`.

## The RT contradiction family

DECL rules cross-check declared vs **scanned**; RT rules cross-check
declared/scanned vs **observed**. Emitted only by merge, never by `stoa
scan`. All are report-only in v1 (`Gates? no` — shadow mode); every finding
carries both sides of the evidence (`trace_ref` + `declared_ref`/registry
field):

| Rule | Severity | Fires when | Gates? |
|---|---|---|---|
| [RT001](rules/RT001.md) | critical | declared `recommend_only`/`human_approved`, unapproved high-impact actions observed | no |
| [RT002](rules/RT002.md) | high | observed amount over declared `max_per_action` / window total over `daily_aggregate` | no |
| [RT003](rules/RT003.md) | high | observed capability absent from both registry and declarations | no |
| [RT004](rules/RT004.md) | medium | production + monitoring declared, zero spans observed | no |
| [RT005](rules/RT005.md) | info | approval observed on 100% of high-impact actions (good news, phrased "observed") | no |

Suppression: `# stoa: ignore[RT###]` where code-anchored; trace-anchored
findings via `[runtime] suppress = ["RT002:<agent_id>"]` — suppressed
findings stay counted and listed, never hidden.

## What the rest of the toolchain gains

- **Registry** (schema 1.4, [SCHEMA.md](../SCHEMA.md)): per-agent
  `runtime_evidence`, the long-reserved `liveness_state`, RT findings with
  `trace_ref`.
- **Graph / report**: trace-corroborated static edges gain `observed: true`
  (thick in the HTML report, "(observed)" in Mermaid); runtime-only reach
  and **`delegates`** edges — the first inter-agent edges Stoa draws — carry
  `provenance: "observed"` (dashed/dotted). The report states the evidence
  window. The zero-network, hash-pinned CSP model is untouched: runtime
  data enters through the same non-executing JSON tag.
- **Dimensions**: the two proxy dimensions (Conduct variability, Dependency
  drift) upgrade to a new `runtime` assessability tier *per agent, per
  window* when spans cover them — no longer capped at `moderate`, in either
  direction, with the observed basis serialized (`runtime_basis`) and the
  window stated ("Assessed from traces: …, 12,431 spans"). Entries without
  runtime evidence stay `proxy` and stay capped — the original property
  test holds untouched; a new one enforces that `runtime`-tier entries
  always carry a non-empty evidence window.
- **Assurance packet** (`assurance-packet/1.2`): Area 12 (Monitoring) gains
  `observed` rows (window, span counts, coverage — and explicit
  `not_provided` gaps for uncovered agents); Area 18 (Claims evidence)
  populates its reserved `observed` provenance with RT findings, approval-
  gate logs, and the analysis window. No runtime data → `not_provided`,
  exactly as before.
- **`stoa diff`** ignores all of it, unconditionally: code diffs must never
  show phantom drift from run-to-run runtime variance.

## Worked example

Meridian ships a hand-auditable 12-span fixture
([examples/meridian-ops/traces/](https://github.com/iamved/stoa-agent-risk/tree/main/examples/meridian-ops/traces)):

```bash
cd examples/meridian-ops
stoa scan . --no-git --with-runtime traces
stoa export --assurance stoa-registry.json --format md
```

Against Meridian's real `stoa-declared.toml` this produces two RT001s (the
payments agent *and* the support bot both execute unapproved high-impact
actions despite declared oversight), an RT002 (a 2,500 USD refund against a
declared 2,000 USD per-action cap, trace span cited), an RT003 (the triage
agent observed writing to the filesystem — a capability nothing on paper
gave it), a `delegates` edge from the support bot to the payments agent,
and a populated Area 18.

## What Stoa says / never says (runtime rows)

The existing table in [dimensions.md](dimensions.md) extends — it never
shrinks:

| Stoa says | Stoa never says |
|---|---|
| "Approval gate observed firing on 100% of high-impact actions in window X" | "The agent is safe in production" |
| "Assessed from 14 days of traces, 12,431 spans" | "Behaviorally guaranteed" / "will keep behaving this way" |
| "Observed capability absent from everything on paper" | "This is the agent's complete behavior" |
| "No spans observed for this agent in the window" | "This agent is not running" |
| "Evidence quality: redacted (shapes and hashes only)" | claims about content it never recorded |

Runtime evidence is still evidence about a *window*, not a proof about the
future — the overlay widens what "observed" can honestly cover; it never
converts observation into guarantee.

## Performance budget

Hot path (span build + queue append): ~50 µs typical, asserted < 1 ms
median in tests. Analysis streams: 100k spans are processed with peak
memory growth bounded far below the raw file size (asserted < 60 MB) —
never slurped.

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
  `[runtime]` pip extra adds ed25519 signing (below) and, later, the OTLP
  exporter.
- `capability` / `integration` / `provider` reuse the scanner's exact ids —
  never a parallel vocabulary. Custom values are recorded but flagged.
- Unconfigured, every decorator is a pass-through. An unwritable trace
  directory warns **once** and the SDK becomes a no-op: instrumentation
  must never crash or slow the customer's agent (hot path is a queue
  append; a background thread does the I/O; a full queue drops spans and
  counts the drops into the next file header).
- `stoa init runtime` scaffolds the config and a working example.

### Guard, session, model call (trace 1.1)

Three thin aliases over `stoa_span`, for code that would otherwise repeat
the same arguments:

```python
from stoa import runtime as stoa_rt

stoa_rt.configure("stoa-traces", agent_id="account-actions",
                  signing_key="hmac:...", registry_path="stoa-registry.json")

@stoa_rt.guard(side_effect="payment", limit_field="amount", approval_field="approval")
def issue_refund(order_id: str, amount: float, approval: str | None = None): ...

with stoa_rt.session(user_ref="cust-8841") as s:
    with stoa_rt.model_call("openai", "gpt-4o") as m:
        reply = client.chat.completions.create(...)
        m.record(tokens_in=reply.usage.prompt_tokens, tokens_out=reply.usage.completion_tokens, cost_usd=0.002)
    ok = s.approval(actor="ops-oncall@meridian.example", channel="slack", granted=True, latency_ms=1200)
    issue_refund("o-1", 120.0, approval=ok)
```

- `@guard` records an `action` span named after the function, with
  `attrs.side_effect` (`read | write | payment | delete | external_send`),
  the argument named by `limit_field` as the span's `amount`, and the
  argument named by `approval_field` as its `approval_span_id`. Sync and
  async functions; signature and docstring preserved; never raises.
- `session()` opens an `agent_run` span and stamps every span inside it
  with one `session_id`. `s.approval(...)` records an `approval` span and
  returns its id; the actor is keyed under the signing key, never stored in
  clear. `s.flag(name)` attaches a caller-chosen flag to the session span.
- `model_call()` records an `llm_call` span; `record(...)` adds token
  counts (OpenTelemetry GenAI attribute names) and `cost`.

### Flags

Each span carries `attrs.flags`, computed by the SDK from the agent's recent
window (last 1,000 spans or seven days) and the last scan's
`stoa-registry.json` (found by searching upward, or given as
`registry_path`): `no_registry`, `undeclared_tool`, `over_declared_limit`,
`approval_bypassed`, `new_counterparty`, `burst`, `repeat_failure`,
`model_changed`, `integration_changed`. `analyze` counts them per agent;
`drift` compares them. The full definitions are in `stoa/runtime/flags.py`.

### Chain and signature

Every record in a trace file links to the one before it (`prev_hash`,
`hash`) and is signed under the configured key (`sig`,
`signer_fingerprint`). The key comes from `configure(signing_key=...)` or
`$STOA_SIGNING_KEY`, in one of three grades the header names:

| Grade | Key spec | Who can verify |
|---|---|---|
| `none` | no key | anyone can check the chain; anyone who can edit the file can also recompute it |
| `hmac-sha256` | `hmac:<secret>` | whoever holds the secret |
| `ed25519` | `ed25519:<64 hex seed>` (needs `pip install stoa-agent-risk[runtime]`) | anyone: the public key travels in the header |

`stoa runtime verify stoa-traces [--key hmac:...]` walks every file and
reports the first break (a changed record, a deleted or reordered line, a
signature that fails). A pre-1.1 file is reported as unchained, not broken.
Chaining and signing run on the exporter's background thread, never on the
hot path.

### Privacy: redact-by-default

Prompt/response bodies and tool payloads are **never recorded** unless you
opt in. By default every string attr becomes a SHA-256 hash plus a length —
shapes, not content. Opting in (`capture_content=True`) flips the span's
`redaction` flag to `"content"` (so downstream analysis states what
evidence quality it had) and routes text through your `redaction_hook`
first if you set one.

### Policy (`stoa.policy.toml`)

A policy is evaluated on every guarded call (and every MCP `tools/call`
through the proxy). It is found by searching upward from the working
directory, or given as `configure(policy=...)` / `$STOA_POLICY`. The file
is TOML, like the rest of Stoa's configuration:

```toml
version = 1
[defaults]
mode = "observe"            # observe | enforce: the starting point for every rule

[[rules]]
id = "refund-cap"
when = 'tool == "issue_refund"'
expr = "amount <= 500"
on_fail = "require_approval"

[[rules]]
id = "payment-needs-approval"
when = 'side_effect == "payment"'
expr = "approval.granted == true"
on_fail = "deny"
enforce = true

[[rules]]
id = "allowlist"
when = "true"
expr = "tool in agent.declared_tools"
on_fail = "observe"
```

Expressions see `tool`, `args` (the redacted view: numbers and bools as
they are, strings as hashes), `side_effect`, `amount`, `approval`
(`granted`, `span_id`), `agent` (`id`, `name`, `declared_tools`,
`max_per_action`) and `session`. They are evaluated by a small AST walker,
never `eval`: names, attributes, items, comparisons including `in`, `and`,
`or`, `not`, arithmetic. An unknown name makes the rule report `error`
rather than raise.

What a decision does: every rule records its decision in
`attrs.policy_rules` / `attrs.policy_decisions` and the span's
`enforcement` says `allowed`, `observed` or `denied`. Only a `deny` whose
rule sets `enforce = true` (or every deny when the SDK is configured with
`fail_open=False`) raises `StoaDenied` into the caller before the tool
runs. `require_approval` calls the hook registered with
`stoa_rt.on_approval(fn)`; a true result records an approval span the call
then cites, false records a denial; with no hook the decision is recorded
and the call proceeds. A missing or malformed policy file means no rules
and one warning.

### Framework adapters (`stoa.runtime.integrations`)

Each adapter imports its framework lazily and degrades to a no-op with one
warning when it is absent. None records prompt or response content.

- **LangChain / LangGraph**: `StoaCallbackHandler(side_effects={...},
  limit_fields={...})` passed in `config={"callbacks": [...]}`. Tool runs
  become `action` spans (named after the tool, with the side effect you
  declared for it and the numeric field you named as the amount), model
  calls become `llm_call` spans with token usage and requested tool names.
  A LangGraph `interrupt()` is recorded as a pending approval; the resume
  on the same thread as a granted one the next tool span cites.
- **OpenAI**: `instrument(client)` wraps `chat.completions.create` and
  `responses.create` on sync and async clients.
- **Anthropic**: `instrument(client)` wraps `messages.create`.
- **MCP**: `stoa runtime mcp-proxy --upstream "python server.py"
  --side-effect issue_refund=payment --limit-field issue_refund=amount`
  runs a stdio MCP server behind a proxy that records the tools it
  advertises, records every `tools/call` as an `action` span, and applies
  the policy: an enforced deny is answered with a JSON-RPC error and never
  reaches the server. Stdio only; nothing imports the `mcp` package.

`stoa runtime tail stoa-traces [-f]` prints one line per span as they are
written. `examples/langgraph_refund_bot/` is a complete worked example:
`make demo` scans the bot, runs five traced sessions (one above the
approval threshold, one duplicate refund, one call to a tool the scan never
listed), verifies the chain, reconciles the tools and prints the RT
findings.

### OTLP mirror

`configure(exporter="otlp", otlp_endpoint="https://collector.example.test")`
(or `[runtime] exporter = "otlp"` plus `otlp_endpoint`, or
`$OTEL_EXPORTER_OTLP_ENDPOINT`) keeps the JSONL file as the record and
mirrors every span to your own collector as an OpenTelemetry span with the
`stoa.*` and `gen_ai.*` attributes (`stoa/runtime/otel.py`). It needs
`pip install stoa-agent-risk[runtime]`; without the package the mirror
warns once and the file sink carries on. There is no default remote URL.

### Alerts (local)

`stoa runtime alerts stoa-traces --registry stoa-registry.json
[--baseline .stoa/baseline.json] [--deliver]` evaluates alert rules over
the analysis, the drift and the chain report, deduplicates per agent and
rule within `dedupe_minutes` (state in `.stoa/alerts-state.json`), prints
the result, and with `--deliver` sends critical and high alerts one by one
and the rest as one digest, to a signed webhook (`X-Stoa-Signature:
sha256=<hmac>` over the body), a Slack incoming webhook, or the terminal.
Rules and channels live under `[alerts]` in `stoa.policy.toml`; without
that block the defaults fire for undeclared tools, approval bypassed, over
the declared limit, new counterparty, burst, policy denied, model or
integration changed, approval rate drop, chain broken and agent silent.
`stoa runtime alerts --test approval-bypassed` sends one synthetic alert so
the wiring can be confirmed. Nothing here runs a server; alerts are
evaluated where the trace files are, as often as you run the command.

### Collector querying stays deferred

Reading spans back from a collector (instead of the JSONL files) is not
implemented; the file is the record.

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

## Reconcile

`stoa runtime reconcile stoa-traces --registry stoa-registry.json [--since 30]`
prints, per agent, the three columns a reviewer asks for: tools declared and
used, tools used but undeclared (the RT006 evidence), and tools declared but
dormant for `--since` days measured back from the end of the window.
`--out` writes `runtime-reconcile/1.0`.

## The RT contradiction family

Trace 1.1 adds three rules to the five below: **RT006** a tool observed at
runtime that the scanned inventory does not list for the agent; **RT007** a
money action whose `approval_span_id` does not resolve to an approval span
in the window; **RT008** a model or integration that neither the static
scan nor the committed baseline (`--baseline`) knew. Same shape as RT001 to
RT005: `trace_ref`, report-only, suppressible via `[runtime].suppress`.

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

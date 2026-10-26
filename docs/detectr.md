# Hallucination DetectR

DetectR checks what an agent said and did against what it saw. It is
ledger-first: everything the agent could have known in one run is rebuilt
in order, then every statement and every tool call is checked against that
record. Text-grounding models are optional and come after the deterministic
checks, never instead of them.

## The ledger comes first

A hallucination is a property of a claim, relative to a source of truth, at
a point in a trajectory. The ledger is that source of truth: user input,
instructions, retrieved documents, tool calls, tool results, approvals, the
agent's own output, and hand-offs between agents, in the order they
happened, with the raw payload kept as recorded. The agent's paraphrase of a
tool result is an `agent_output` entry and never stands in for the result.
Every entry carries a SHA-256 of its payload, so evidence survives redaction.

Three sources build the same shape:

- Stoa SDK traces (`stoa-trace/1.1`). Content is recorded only under
  `configure(capture_content=True)`; a redacted trace yields a ledger of
  hashes and lengths, every claim is then unverifiable, and the report says
  why.
- OpenTelemetry GenAI spans, current (`gen_ai.input.messages`,
  `gen_ai.output.messages`, `gen_ai.tool.call.arguments` and `.result`) and
  legacy (`gen_ai.prompt`, `gen_ai.completion`) forms.
- LangGraph checkpoints or `StateSnapshot` dumps, in `model_dump` or `lc`
  constructor form.

```bash
stoa detectr ledger stoa-traces/              # dump what the agent saw and did
stoa detectr ledger checkpoint.json --agent-id refund
```

## Claims and checks

Tool calls become action claims. Agent output is split into sentences and
clauses, each typed as action, result, commitment, reasoning or factual,
with negation, hedges and conditionals marked. "I was not able to process
the refund" is the opposite of a phantom action and is read that way.

Layer 0 runs on every claim, with no model and no network:

| Rule | Fires when | Label |
|---|---|---|
| RT009 | The agent says it did something and no tool call with a successful result precedes the claim | contradicted |
| RT010 | An amount, id, date or status the agent states conflicts with the field the tool returned | contradicted, with numerical, identifier, temporal or status |
| RT011 | A promise carries a timeline or amount nothing the agent saw supports | unsupported |
| RT012 | A money, id, email or date argument of a tool call traces to nothing the agent saw, or conflicts with it | unsupported or contradicted |
| RT013 | A value traces only to a tool result a later result for the same field replaced | contradicted, stale |

Every verdict names the ledger entries it used. Tolerances (a cent of
rounding, a day of timezone drift, status synonyms) live in
`stoa.detectr.toml`.

```bash
stoa detectr check stoa-traces/ --out reports/run-1.json
stoa detectr check checkpoint.json --agent-id refund --json
```

The report lists each finding with the claim text, the offending value in
brackets, the evidence excerpts and how many downstream claims reused the
bad value. Findings use the same shape as the RT family, plus a `detectr`
block. Unverifiable claims are listed apart and never enter the rate.

## Checkers

External checkers judge text claims against evidence. The evidence is
resolved per claim and trimmed to the checker's budget: the tool result the
claim is about, entries sharing one of its values, the sentences of the
instructions and documents that share its words, approvals. A checker sees
the refund API response, not the whole trace.

| Checker | Extra | Runs | Notes |
|---|---|---|---|
| `lettucedetect` | `hallucination` | sync capable | MIT; mmBERT encoder with a typing head, spans with category and subcategory |
| `hhem` | `hallucination-hhem` | deferred | Vectara HHEM-2.1-Open, one consistency score, English only |
| `deepeval` | `hallucination-judge` | batch | Faithfulness judge with the customer's key; refuses to grade its own model family |
| `selfcheck` | none | stub | Resampling consistency; interface only |

Routing is per consequence class of the trajectory, from the `side_effect`
the guard recorded or the registry's tool list:

```toml
[detectr]
latency_budget_ms = 100
threshold = 0.5

[detectr.lanes.default]
checkers = ["lettucedetect"]
sample_rate = 0.2

[detectr.lanes.payment]
checkers = ["lettucedetect", "hhem"]
sample_rate = 1.0
sync = true

[detectr.checkers.lettucedetect]
min_confidence = 0.6

[detectr.weights]
lettucedetect = 0.6
hhem = 0.4

[detectr.thresholds]
"meridian-refund" = 0.7
```

A sync checker that blows the budget is demoted to the deferred lane for the
rest of the run, with one warning. `--sync` runs only what is allowed inline
and lists the rest as deferred.

## Fusion

A Layer 0 contradiction wins outright. Otherwise checker scores combine with
the weights into a probability, read against the agent's threshold. Taint
follows the claim graph: downstream claims that reuse a bad value are
marked, and the count is the blast radius.

## Metrics, labels and the bench

```bash
stoa detectr metrics reports/ --window month
stoa detectr bench --datasets agentic,ragtruth --checkers lettucedetect --ragtruth ragtruth.jsonl
```

Metrics are per agent, per window and per claim type: hallucination rate,
contradiction rate, phantom action rate, argument grounding failure rate,
unverifiable rate (apart), mean blast radius, mean time to detection. Every
number is derived from the reports passed in.

Labels (`.stoa/detectr-labels.jsonl`, sources human, outcome, redteam) feed
a fitter for per-agent thresholds and per-checker weights. The table and
the fitter ship now; the adjudication screen comes later.

The bench runs enabled checkers on RAGTruth and HaluBench subsets you
download yourself, and on the agentic fixture set, reporting precision,
recall, span F1, latency and cost per checker, plus suggested fusion
weights. It never runs in CI and never downloads.

## On the dashboard

`stoa dashboard --runtime stoa-traces` (and `stoa scan --with-runtime`) runs
Layer 0 over every session that carried captured content and puts the result
on the DetectR screen: per agent, how many claims
were grounded, unsupported, contradicted or unverifiable, then each finding
with the offending value marked in the agent's own words and the tool result
it was checked against. Sessions recorded in redacted mode are counted but
not checked. These findings stay on the DetectR screen; they are not added to
the agent's findings or the scan totals.

## Adding a checker

Implement a class with a `MANIFEST` (a `CheckerManifest`) and a
`check(claim, evidence) -> Verdict` method, then register it:

```toml
[project.entry-points."stoa.detectr.checkers"]
mychecker = "my_package.detectr:MyChecker"
```

Import your model library inside `check` or a lazy loader and raise
`CheckerUnavailable` with the install hint when it is missing. Mark
`sync_capable` honestly: anything that calls a network or a large model is
not. Return `unverifiable` when no evidence was given, never a guess.

## What DetectR does not do

No policy evaluation or enforcement, no graph rendering, no world-knowledge
factuality, no resampling consistency (stub only), no fine-tuning, no
adjudication UI. Findings land in the existing shape and metrics in JSON so
those features can read them later.

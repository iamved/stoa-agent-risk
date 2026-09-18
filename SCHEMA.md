# Stoa JSON Schema

This document describes the structure of `stoa-registry.json`, the JSON
document produced by `stoa scan`.

**Current schema version: `1.7`**

## Versioning policy

- The schema is **additive-first**. New optional fields bump the **minor**
  version (`1.0` → `1.1`).
- Breaking changes (removing or renaming a field, changing a field's type or
  meaning) bump the **major** version (`1.x` → `2.0`).
- **Consumers must ignore unknown fields.** New fields may appear in any
  minor release.
- No generated timestamps appear in the document, so output is deterministic
  for a given tree and configuration.
- **Backward compatibility:** a `1.0` reader can consume a `1.1` document, and
  a scan that produces no AI (`AI0xx`) findings serializes byte-identically to
  `1.0` apart from `schema_version` — every `1.1` field below is emitted only
  when it carries data.

## Schema 1.1 additions (v0.2)

**On a finding** (present only on AST/flow-based `AI0xx` findings):

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `"<rule_id>-<fingerprint[:12]>"`, the stable finding id |
| `canonical_name` | string | e.g. `STOA-LLM02-OUTPUT-EXEC` (also the SARIF ruleId) |
| `owasp` | object | `{"llm_top10_v1_1": "LLM02", "llm_top10_2025": "LLM05"}` |
| `variant` | string | rule sub-variant (e.g. AI005 `trust-remote-code`) |
| `flow` | array | taint steps: `{role: source\|propagation\|sink, line, snippet}` (snippets redacted) |
| `gate_eligible` | bool | true only for AI002 exec-class at high confidence |
| `dimensions` | array | dimension ids this finding contributes to |
| `supersedes` | array | rule ids this finding dedups (e.g. AI002/sql supersedes SEC003) |
| `evidence_tags` | array | e.g. `system_role_interpolation`, `local_endpoint_observed` |

**On an agent candidate:** `dimension_assessment` — per-dimension exposure
block: `{taxonomy: {id, version}, dimensions: [{id, group, assessability,
exposure, score, contributing_findings, contributing_capabilities,
controls_observed, statement}]}`. `exposure` ∈ `elevated | moderate | low |
none-observed | not-assessable` (never "safe"/"covered"); proxy-tier
dimensions are capped at `moderate`. `group` (schema 1.3+) is a display
grouping letter (e.g. `A`–`D` on the default taxonomy) — empty string on a
custom taxonomy that doesn't define groups. **On a finding:** `dimensions` —
the dimension ids it contributes to. **Top-level:** `dimension_summary` — org
rollup (per-dimension max exposure and agent counts); `degraded_files` —
files whose AST parse degraded.

## Schema 1.2 additions (Assurance layer)

Three independent additions. **Declared metadata** and **the contradiction
detector** are opt-in by presence: a scan with no `stoa-declared.toml`
serializes byte-identically to `1.1` apart from `schema_version`.
**Autonomy inference** is unconditional, like `highest_severity` — every
agent candidate gets an `autonomy_level`, regardless of declarations.
**Permission tags** (`permission_tags` on every agent candidate) are also
unconditional, like `capabilities`.

**On an agent candidate — declared metadata** (present only when
`stoa-declared.toml` declares this agent id): `declared` — the raw declared
record: `{name, owner, purpose, users, geography, production_status,
autonomy_intent, data_classes, economic_authority}`. `economic_authority`,
when set, is `{max_per_action?, daily_aggregate?, worst_case_customer_loss?}`,
each `{amount: number, currency: string}`.

**On an agent candidate — autonomy inference** (always present):
`autonomy_level` — `{level, signals, reason}`. `level` ∈ `recommend_only |
human_approved | bounded_autonomous | unrestricted_autonomous |
indeterminate` — a static classification of how unattended the agent's
side-effecting reach appears to be, derived from existing detectors (AI002
side-effecting sinks, AI003 approval-absence, a same-file bounding signal).
`signals` — the evidence list, `[{signal (a rule id or a named pattern like
`"approval_construct"`/`"bounding"`), path, line}]`. `reason` — populated
only when `level == "indeterminate"`: the classifier never guesses when
signals don't cleanly resolve.

**On an agent candidate — permission tags** (always present, possibly
empty): `permission_tags` — a higher-stakes layer on top of `capabilities`:
`move_funds`, `approve_transactions`, `sign_contracts`, `delete`,
`communicate` (an alias over `email_send`/`messaging`).

**On a finding — the contradiction detector** (`DECL001`-`DECL007` only):
`declared_ref` — `{path, key}`, the declaration-side evidence (the
`stoa-declared.toml` key path this finding contradicts), alongside the
finding's own `path`/`line` (the code-side evidence). Cross-checks declared
facts against what the scan actually observed — e.g. `DECL001` fires when
`autonomy_intent` is `recommend_only`/`human_approved` but the inferred
`autonomy_level` is `bounded_autonomous`/`unrestricted_autonomous`. See
[docs/declarations.md](docs/declarations.md) for the full rule table.

**Top-level:** `business` — `{industries?, regulated_activities?,
max_customer_dependency?, societal_risk_flags?}`. `governance` —
`{release_approval, incident_response, risk_acceptance?,
harmful_output_policy?}`. `evidence` — pointers only, grouped by category
(`testing`, `safety_testing`, `monitoring`, `contracts`, `vendor`,
`historical`, or any other caller-supplied category name), each entry
`{kind, ref, date?}`. All three present only when `stoa-declared.toml` exists.

## Schema 1.3 additions (trust-standard alignment)

Renames the default dimension taxonomy's ids and adds a display `group`
field — see [docs/dimensions.md](docs/dimensions.md) for the full rationale
and the old→new id mapping. This is the default taxonomy shipped with the
binary (`stoa-aiuc-8`, v2.0, replacing `stoa-default-8` v1.0); a custom
taxonomy supplied via `[dimensions] taxonomy` is unaffected.

Two new optional declared fields, both additive and both attestation-only
(never scored — see [docs/dimensions.md](docs/dimensions.md)):
`business.societal_risk_flags` (list, subset of `critical_infrastructure |
biosecurity_adjacent | mass_influence`) and `governance.harmful_output_policy`
(string pointer). Two new recognized `evidence` categories:
`safety_testing` and `vendor`, same `{kind, ref, date?}` shape as the
existing categories.

`assurance-packet/1.1` (produced by `stoa export --assurance`, not part of
`stoa-registry.json` itself): the packet's 14 areas become 18, each now
carrying a `group` key (one of `index`, `A`–`F`, `G`) that groups them under
the six categories common to AI agent trust standards plus a seventh,
Stoa-only group for insurance-specific exposure. See
[docs/assurance-export.md](docs/assurance-export.md).

## Schema 1.4 additions (Runtime trace overlay)

All optional, emitted **only** by `stoa runtime merge` / `stoa scan
--with-runtime` — a plain scan serializes byte-identically to `1.3` apart
from `schema_version`. See [docs/runtime.md](docs/runtime.md).

**On an agent candidate** (merge only):

| Field | Type | Meaning |
|---|---|---|
| `runtime_evidence` | object | Observed-behavior summary for the analyzed window: `{window: {start, end}, span_count, spans_by_kind, error_rate, observed_capabilities, observed_integrations, observed_providers, observed_models, capability_counts, integration_counts, high_impact_actions, high_impact_approved, approval_rate_high_impact, max_observed_amount, window_total_amounts, evidence_quality, delegations_to, trace_files}` |
| `liveness_state` | string | The field reserved since 1.0, now live: `"active"` (spans observed in window) or `"idle"` (registry agent, zero spans). `"deprecated"` stays reserved — inferring it needs more than one window. |

**On a finding** (RT-family only): `trace_ref` — `{file, line, span_id}`,
the trace-side evidence pointer, sibling to the DECL family's
`declared_ref`. RT findings (`RT001`–`RT005`) are appended by merge to the
agent's `findings` list; the scan-time `summary.findings` counts are
deliberately not rewritten (they describe the static scan) — merged RT
findings are counted in the top-level `runtime` block instead.

**On a `dimension_assessment` entry** (merge only, the two proxy dimensions
only, and only when spans cover the agent): `assessability` may become
`"runtime"`, accompanied by `evidence_window` (`{start, end, span_count}`,
always non-empty — enforced by a property test) and `runtime_basis` (the
observed signals the exposure re-bucketing used, so the bucket is auditable
from the registry alone). Entries still labeled `proxy` remain capped at
`moderate` exactly as before.

**Top-level** (merge only): `runtime` — `{analysis_schema, window, span_count,
agents_covered, agents_total, unmatched_agents, rt_findings,
evidence_quality}`.

**`stoa diff`** ignores `runtime_evidence`, `liveness_state`, and RT-family
findings unconditionally: a diff describes call sites added or removed in
code, and runtime data varies run to run.

### Companion schemas (separate documents, not part of the registry)

| Schema | Producer | Notes |
|---|---|---|
| `stoa-trace/1.0` | the `stoa.runtime` SDK | JSONL, one span per line; line 1 is a header record (`{kind: "header", schema, sdk_version, redaction, dropped_spans}`). Span fields: `kind` (`agent_run \| llm_call \| tool_call \| action \| approval \| retrieval \| delegation`), `trace_id`, `span_id`, `parent_span_id`, `agent_id` (12-hex or null + `agent_hint`), `start_ts`/`end_ts` (ISO-8601 UTC — trace files are the one place timestamps live in content), `status`, `redaction`, and optional `capability`/`integration`/`provider` (scanner vocabulary ids; off-vocabulary values are flagged `vocabulary: "custom"`), `model`, `tool`, `amount {amount, currency}`, `approval {approved_by, method}`, `approval_span_id`, `from_agent_id`/`to_agent_id` (delegation), `attrs` (hashes/lengths by default — see redaction). Reserved fields: `enforcement`, `session_id`, `cost`. |
| `runtime-analysis/1.0` | `stoa runtime analyze` | Deterministic body given identical traces; wall-clock in `header.generated_at` only. `agents` (per-id summaries), `unmatched_agents` (never silently dropped), `no_runtime_evidence` (explicit). |
| `runtime-baseline/1.0` | `stoa runtime baseline` | Committed like `.stoa/approvals.toml`, reviewed like code. |
| `runtime-drift/1.0` | `stoa runtime drift` | Drift events (`high \| medium \| info`) + the exact thresholds used. |

`assurance-packet/1.2` (produced by `stoa export --assurance`): the reserved
`observed` status/provenance is live — Areas 12 (Monitoring) and 18 (Claims
evidence) populate from a runtime-enriched registry, and RT findings join
the contradictions table. A packet from a registry without runtime data is
byte-identical to `1.1` apart from the schema string.

## Schema 1.5 additions (Regulatory crosswalk)

A presentation/labeling layer that anchors findings to frameworks a reader
already knows. **It never participates in scoring** — dimension scores,
exposure buckets, and the proxy cap are byte-for-byte identical to `1.4`
(guarded by a pre-change golden snapshot). Versioned as `stoa-crosswalk-1`
and overridable via `stoa.toml` `[crosswalk] path`.

**On every finding:** `crosswalk` — `{owasp_llm_2025, eu_ai_act, relation,
so_what}`. `owasp_llm_2025` is one OWASP LLM Top 10 (2025) class (`LLM01`–
`LLM10`) or `null` where no honest class fits; `eu_ai_act` is one article
(e.g. `"Art. 15"`); `relation` is `exposure` or `control-observed`; `so_what`
is a plain-English gloss (says/never-says vocabulary — never
"compliant"/"protected"/"secure").

**On each `dimension_summary` dimension:** `crosswalk` — `{owasp_llm_2025:
[...], eu_ai_act: [...]}`, the union of the framework tags of the rules that
contributed to that dimension (OWASP codes sorted `LLM01`→`LLM10`).

**Top-level:** `crosswalk` — `{id, version, owasp_llm_version,
eu_ai_act_reference}`, attributing the mapping to a reviewed version.

The pre-existing per-finding `owasp` object (schema 1.1) is unchanged and
independent — the crosswalk lives under `crosswalk`, never overwriting it.

**SARIF:** results and rules gain `owasp:<LLMxx>` and `euaiact:<article>`
tags alongside the existing `stoa-dim:<dimension>` tags. A blank OWASP
mapping emits no `owasp:` tag rather than a fake one.

## Schema 1.8 additions (dashboard data contract)

Three additive fields consumed by the dashboard (`stoa-dashboard.html`). No
score, exposure, or existing field changes.

**On `repository`:** `head_commit` — `{hash, date}` of HEAD. `date` is the
commit's own ISO-8601 committer date (`git log -1 --format=%cI`), so it is a
pure function of the commit, never a wall-clock read; two scans of the same
commit agree byte for byte. Omitted with `--no-git` or outside a repository.

**On every `dimension_assessment.dimensions[]` entry:** `score_before_controls`
— the same clamped integer as `score`, taken before control credit is
subtracted. `score` and `exposure` are unchanged; consumers may show the pair
as inherent versus residual without a second formula. Always present, so a
1.8 registry differs from 1.7 by this integer per entry and the version string.

**Top-level `risk_register`** (only when `stoa-declared.toml` has a
`[[risk_register]]` block): the declared treatment of scored exposures, one
object per entry —

| Field | Type | Meaning |
|---|---|---|
| `risk_id` | string | `<dimension-id>/<agent-id>` — binds to a `dimension_assessment` entry |
| `owner` | string | accountable person or team |
| `treatment` | `accept \| mitigate \| avoid \| transfer \| null` | declared treatment |
| `rationale` | string | why |
| `review_by` | ISO date (optional) | next review |
| `status` | `open \| in_progress \| closed` (optional) | workflow state |

Entries with a malformed `risk_id` or an unknown `treatment` are dropped with a
warning; an entry naming an agent id absent from the scan is kept and warned
about, so a stale row stays visible.

The dashboard's own envelope (`stoa-dashboard/1.0`) wraps the registry
together with the `stoa-diff/1.0` document, history summaries
(`stoa-history-entry/1.0`, under `.stoa/history/`), the assurance packet, and
static rule and taxonomy tables. It is a separate document and is not part of
`stoa-registry.json`.

## Schema 1.7 additions (tool inventory)

Tools are first-class objects. An agent that binds tools carries a `tools`
array; agents with no recognized tool binding omit the key, so their records
are byte-identical to `1.6` apart from `schema_version`.

**On an agent candidate:** `tools` — a list of:

| Field | Type | Meaning |
|---|---|---|
| `name` | string | tool name (function name, schema `name`, action-group function, UC function short name) |
| `path`, `line` | string, int | where the tool is defined — usually **not** the agent's file |
| `kind` | string | `langchain_tool`, `openai_function_tool`, `mcp_tool`, `json_schema`, `ts_tool`, `uc_function`, `bedrock_action_group` |
| `params` | list | `{name, type?}` from the signature, zod/JSON schema, or `function_schema` |
| `capabilities`, `integrations` | list | what the tool's body reaches (same vocabulary as the agent's); for a Bedrock action group, what its Lambda's role allows |
| `high_impact` | bool | any capability in the high-impact set |
| `money_action` | bool | the tool moves money (refund, payout, transfer, reissue, waive, …) |
| `guards` | list | numeric or membership checks on a parameter observed in the body (`amount > 500`) |
| `retry` | string or null | what wraps the tool in a retry, if anything (`stop_after_attempt (via _post_refund)`) |
| `idempotency_key` | bool | an idempotency key or dedupe check is visible on the path |
| `resolved` | bool | false when only a name or schema was seen (UC functions, unmatched JSON schemas) |

The agent's `capabilities` and `integrations` are the union of its own and
its tools'. `autonomy_level` gains `tool:<name>` signals: a bound tool that
reaches a high-impact sink is a model-driven side effect even when no taint
flow is visible in the agent's own file, and IaC agents no longer take
approval or bounding credit from free text in the resource file.

New rule **AI008** — *Non-idempotent money action under retry* (high;
dimensions `unreviewed-high-impact-action`, `control-coverage-gap`; OWASP
LLM06; EU AI Act Art. 9). New provider id `databricks` (`ChatDatabricks`,
`databricks_langchain`).

## Schema 1.6 additions (IaC-discovered agents)

Agents that are *configured* in infrastructure code rather than written in
application code — Databricks Model Serving endpoints and Amazon Bedrock
agents found in Terraform — join the registry as ordinary agent candidates. Three optional
fields say where an agent came from; they are **emitted only when
non-default**, so a code-only scan is byte-identical to `1.5` apart from
`schema_version`.

**On an agent candidate:**

| Field | Type | Meaning |
|---|---|---|
| `source` | string | `"iac"` — discovered in infrastructure code. Absent ⇒ `"code"`. |
| `discovery_tier` | string | `"recognized"` — inventoried from a resource definition, not deep-scanned; `"full"` once joined to scanned code. Absent ⇒ `"full"`. |
| `platform` | string | `"databricks"`, `"bedrock"` (0.7.1), `"dialogflow_cx"` or `"vertex_ai_agent_builder"` (0.7.2). |

IaC agents carry `language: "terraform"`, `confidence: "high"` (a deployed
endpoint is not ambiguous), and evidence at the resource block's `file:line`:
`AGENT_IAC_SERVING_ENDPOINT` / `AGENT_IAC_BEDROCK_AGENT`, `IAC_GRANT`
(privileges and scope, with the service principal they were attributed
through), `IAC_IAM_POLICY` (IAM actions and resources, with the role and tool
Lambda they were attributed through), `IAC_TOOL_BINDING`, `IAC_KNOWLEDGE_BASE`,
`IAC_CONTROL_*` (guardrail, rate limit, observability stated by an `ai_gateway`
block, a `guardrail_configuration`, or invocation logging), `IAC_MODEL_EGRESS`,
`IAC_FOUNDATION_MODEL`. Detection is scoped to the Terraform *module* (all
`.tf` files in one directory); evidence from another file of the module says
so in its description (`… (in infra/iam.tf)`). Evidence ids are not schema
fields and may be added in a patch release.
Controls stated by IaC are credited in `dimension_assessment` exactly as
code-observed controls are.

**Identity and vocabulary.** An IaC agent's `symbol` is
`<resource_type>.<resource_name>` (e.g. `databricks_model_serving.refund_agent`),
so two resource types sharing a name in one file never collide on `id`. From
0.7.2 the symbol carries a `count` / `for_each` instance (`type.name["key"]`,
`type.name[1]`) and, for an agent defined in a local module, the call path
(`module.billing.google_dialogflow_cx_agent.this`), with `path` the defining
file inside the module; agents read from a `--tf-plan` take the plan file as
`path` and anchor evidence at line 1 (`IAC_PLAN_SOURCE`). Symbols of agents
defined directly in a root module are unchanged;
`name` is the endpoint's human-facing name. `frameworks` is empty for IaC agents
(the platform is carried by `platform`, not mislabeled as an agent framework).
`integrations` gains the id `databricks` (schema 1.6), recognized in code too —
an agent importing `databricks.vector_search` and the serving endpoint that
deploys it share the integration; Bedrock agents carry `aws` (and `ses` when
their tools may send email); Google agents carry `gcp` (and `bigquery`). `[iac] enabled = false` in `stoa.toml` turns
IaC agent discovery off; `.tf` files are still scanned for secrets.

**Caveat.** `autonomy_level` on an IaC agent is inferred from code taint the
resource definition does not carry, so it reads `recommend_only` until the
endpoint is joined to the code that registers its model. Read reach
(`capabilities`) and `controls_observed`, not autonomy, on IaC agents. Reach
is read from `databricks_grants` privileges or from IAM Allow statements
mapped conservatively to capability ids; a value the module cannot resolve
(`var.*`, remote state, `data.*` policy documents) is left unresolved, never
guessed.

## Top-level document

```json
{
  "schema_version": "1.0",
  "tool": { "name": "stoa", "version": "0.1.0" },
  "repository": {
    "name": "payments-service",
    "root": ".",
    "git_ref": "abc1234",
    "base_ref": "origin/main"
  },
  "summary": { "...": "see below" },
  "agents": [ "...agent records..." ],
  "repository_findings": [ "...finding records..." ],
  "skipped_files": [ { "path": "node_modules/", "reason": "..." } ],
  "warnings": [ "...scan warnings, e.g. diff fail-open notices..." ]
}
```

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | `"<major>.<minor>"` |
| `tool.name` / `tool.version` | string | Producer identity |
| `repository.name` | string | Sanitized (credentials stripped from remote URLs); falls back to the root directory name |
| `repository.root` | string | Always `"."`; paths in the document are relative to it |
| `repository.git_ref` | string \| null | Abbreviated HEAD commit, when available |
| `repository.base_ref` | string \| null | The `--base` ref, when diff-aware scanning was requested |
| `agents` | array | Agent-candidate records, sorted by `(path, symbol)` |
| `repository_findings` | array | Findings in files that are **not** agent candidates, sorted by `(path, line, rule_id)` |
| `skipped_files` | array | Skipped files or pruned directories (directory entries end with `/`) with reasons |
| `warnings` | array of strings | Non-fatal scan warnings (e.g. diff-gating fail-open) |

### `summary`

```json
{
  "files_scanned": 347,
  "agent_candidates": 4,
  "high_confidence_candidates": 3,
  "integrations": 6,
  "findings": { "critical": 1, "high": 2, "medium": 5, "low": 0, "info": 3 },
  "new_findings": { "critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0 },
  "suppressed_findings": 2
}
```

`findings` and `new_findings` count **unsuppressed** findings only.
`new_findings` is all zeros unless a diff base was resolved.

## Agent record

```json
{
  "id": "9f2c41d0a3b7",
  "name": "refund_agent",
  "symbol": "refund_agent",
  "path": "src/refund_agent.py",
  "language": "python",
  "confidence": "high",
  "detection_score": 10,
  "evidence": [
    { "rule_id": "AGENT_LANGCHAIN", "line": 41, "description": "LangChain agent construct" }
  ],
  "providers": ["openai"],
  "frameworks": ["langchain"],
  "integrations": ["postgres", "stripe"],
  "capabilities": ["database_read", "payment_access", "tool_calling"],
  "call_sites": { "postgres": 1, "stripe": 2 },
  "last_touched_by": "Alice Smith",
  "last_commit": { "hash": "abc1234", "date": "2026-07-18T12:30:00-07:00" },
  "codeowners": ["@payments-team"],
  "findings": [ "...finding records for this candidate's file..." ],
  "highest_severity": "critical"
}
```

Notes:

- `id` is `sha256("<path>:<symbol>")[:12]` — stable across scans of the same
  source identity.
- `confidence` is `high` / `medium` / `low`, derived from weighted evidence
  (see README). An agent record is always a **candidate**, never a confirmed
  agent.
- `call_sites` counts statically observed call sites per integration. It is
  **not** a runtime API call count.
- `last_touched_by` is the most recent non-bot commit author name (never an
  email address). It is not ownership.
- When one file yields multiple candidates, each candidate carries the file's
  findings; deduplicate by `fingerprint` when aggregating.
- `highest_severity` is `null` when the candidate's file has no unsuppressed
  findings.

## Finding record

```json
{
  "fingerprint": "3f7a9c2e51b8d4f0",
  "rule_id": "SEC001",
  "title": "Possible hardcoded API credential",
  "category": "secret",
  "severity": "critical",
  "confidence": "high",
  "path": "src/refund_agent.py",
  "line": 15,
  "column": 12,
  "snippet": "api_key = \"sk-pro…[REDACTED:a18c45f21a0e]\"",
  "remediation": "Load the credential from a secret manager or environment variable.",
  "suppressed": false,
  "suppression_reason": null,
  "is_new": true
}
```

Notes:

- `fingerprint` is `sha256("<rule_id>:<path>:<normalized redacted context>")[:16]`,
  stable across pure line-number movement. Identical contexts in one file are
  disambiguated with an occurrence index.
- `snippet` is always redacted before serialization; raw secrets never appear
  in this document.
- `severity` ∈ `info | low | medium | high | critical`;
  `confidence` ∈ `low | medium | high`.
- `category` ∈ `secret | injection | reliability | network | control`.
- `is_new` is `true` only when the finding's line intersects an added-line
  range of the diff against `repository.base_ref`; it is always `false` when
  no base was resolved.

## Reserved field names

The following field names are **reserved for future schema versions** and
must not be used for any other purpose by producers or consumers of this
schema. They are not emitted in version 1.0 and carry no behavior today:

| Reserved field | Future purpose |
|---|---|
| `autonomy_level` | ~~Reserved~~ — live since 1.2 (static autonomy inference) |
| `loss_scenarios` | Mapping of findings and capabilities to loss-scenario descriptors |
| `liveness_state` | ~~Reserved~~ — live since 1.4 (`active`/`idle` from the runtime overlay; `deprecated` still reserved) |
| `policy_lines` | Mapping to insurance policy-line identifiers |
| `exposure_class` | Normalized exposure categorization |

Reserving these names now prevents breaking schema changes later.

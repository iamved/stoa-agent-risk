# Stoa JSON Schema

This document describes the structure of `stoa-registry.json`, the JSON
document produced by `stoa scan`.

**Current schema version: `1.2`**

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
block: `{taxonomy: {id, version}, dimensions: [{id, assessability, exposure,
score, contributing_findings, contributing_capabilities, controls_observed,
statement}]}`. `exposure` ∈ `elevated | moderate | low | none-observed |
not-assessable` (never "safe"/"covered"); proxy-tier dimensions are capped at
`moderate`. **On a finding:** `dimensions` — the dimension ids it contributes
to. **Top-level:** `dimension_summary` — org rollup (per-dimension max exposure
and agent counts); `degraded_files` — files whose AST parse degraded.

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
max_customer_dependency?}`. `governance` — `{release_approval,
incident_response, risk_acceptance?}`. `evidence` — pointers only, grouped by
category (`testing`, `monitoring`, `contracts`, `historical`), each entry
`{kind, ref, date?}`. All three present only when `stoa-declared.toml` exists.

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
| `autonomy_level` | Static inference of human-in-loop vs. autonomous action |
| `loss_scenarios` | Mapping of findings and capabilities to loss-scenario descriptors |
| `liveness_state` | Runtime-derived Active / Idle / Deprecated status |
| `policy_lines` | Mapping to insurance policy-line identifiers |
| `exposure_class` | Normalized exposure categorization |

Reserving these names now prevents breaking schema changes later.

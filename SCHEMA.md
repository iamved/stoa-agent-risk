# Stoa JSON Schema

This document describes the structure of `stoa-registry.json`, the JSON
document produced by `stoa scan`.

**Current schema version: `1.0`**

## Versioning policy

- The schema is **additive-first**. New optional fields bump the **minor**
  version (`1.0` → `1.1`).
- Breaking changes (removing or renaming a field, changing a field's type or
  meaning) bump the **major** version (`1.x` → `2.0`).
- **Consumers must ignore unknown fields.** New fields may appear in any
  minor release.
- No generated timestamps appear in the document, so output is deterministic
  for a given tree and configuration.

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

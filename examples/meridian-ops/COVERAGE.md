# Feature coverage

The [`run-e2e.sh`](run-e2e.sh) driver asserts **53 checks** across every Stoa
feature. Map of feature → where it's exercised.

## Detection
- **Agent detection, 8 frameworks** — LangChain, LangGraph, CrewAI, AutoGen,
  PydanticAI, OpenAI Agents SDK, Agno, Vercel AI SDK (`≥10 candidates`).
- **Multi-language** — Python + TypeScript (`support_bot.ts`).
- **Providers / capabilities / integrations** — OpenAI, Anthropic; payment,
  db-write/read, shell, cloud, source-control, email, messaging, vector_search,
  web_search, external_http; Stripe, Postgres, Pinecone, Zendesk, Slack,
  SendGrid, AWS.

## Core rules
SEC001 (credential), SEC002 (password — **now redacted**), SEC003 (interpolated
SQL), REL001 (swallowed exception), NET002 (timeout, **severity overridden to
info** via `stoa.toml`), CTRL001/002 (auth/validation not observed).
CTRL003 **disabled** via config; NET001 **superseded** by AI005.

## AI rules (OWASP LLM Top 10)
- **AI001** prompt exposure (taint) · **AI002** all four sink classes
  (exec/markup/sql/request); exec is `gate_eligible` · **AI003** unobserved
  approval · **AI004** sensitive→model · **AI005** all four variants
  (trust-remote-code, unpinned-artifact, floating-alias, insecure-endpoint) ·
  **AI006** secret→egress · **AI007** sampling · **CTRL004** observability.
- **Taint `flow` arrays** present and redacted.
- **Supersedes dedup** — AI002/sql ⊃ SEC003, AI005 ⊃ NET001, AI006 ⊃ AI004.

## Dimensions
- `dimension_summary` with all 8 dimensions; data-exfiltration reaches
  **elevated**; **proxy dims capped** (never elevated).
- **Controls observed (good news)** — `compliance_agent` shows all six control
  types: approval, authentication, validation, deterministic_sampling,
  pinned_model, observability.
- Findings carry `dimensions`; `--no-dimensions` omits the block; a **custom
  taxonomy** routes unmapped rules to `unclassified`.

## Trust controls
- **Suppressions** — inline (`SEC003` in `lib/db.py`), file-wide (`CTRL001,
  CTRL002` in `agents/legacy.py`); counted, not hidden.
- **`.stoaignore`** — `vendor/` excluded (its secret never appears).
- **False positives** — embeddings-only + `UserAgentParser` not agents;
  placeholder test key at low confidence; parameterized SQL not flagged.

## Drift, reports, safety
- **`stoa diff`** — new agent, capability escalation, `dimension_delta`,
  Markdown changelog with the sticky-comment marker.
- **`--fail-on-drift high`** fails on unapproved escalation; **`stoa approve`**
  writes `.stoa/approvals.toml` with reason + approver.
- **SARIF** with `stoa-dim:*` tags · **GitHub annotations** (`::error`) + job
  summary · **`--strict` gate** exits 1 on the AI002 exec finding.
- **Redaction** — no raw secret (credential *or password*) in any artifact.
- **Determinism** — two scans byte-identical.

## Bug found by this test bed
`SEC002` was emitting the raw password value in its snippet (only API-key shapes
were redacted). Fixed in the same change; regression test in
`tests/test_redaction.py::test_sec002_password_value_is_redacted`.

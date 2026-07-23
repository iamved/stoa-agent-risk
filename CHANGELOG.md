# Changelog

All notable changes to Stoa are documented here. The registry JSON schema is
versioned separately (see [SCHEMA.md](SCHEMA.md)).

## 0.2.0a1 — unreleased alpha (v0.2 "Dimension Exposure", in progress)

This is a **pre-release**. `pipx install stoa-agent-risk` continues to install
the stable 0.1.x line; install this alpha explicitly with
`pip install --pre stoa-agent-risk` or `pip install stoa-agent-risk==0.2.0a1`.

The v0.2 "Dimension Exposure" release ships in phases. This alpha contains the
first three phases (AST engine + eight new AI rules). The dimension exposure
matrix and `stoa diff` are still in progress and **not** in this build.

### Added — AST analysis layer (registry schema → 1.1)
- A tree-sitter AST layer with vendored, pinned grammars for Python, JS, TS/TSX
  (no grammar is downloaded at runtime). On by default; `--no-ast` opts out to
  regex-only. A degraded parse is recorded in `degraded_files`, never dropped.
- An honest intra-file taint engine (`stoa.flow`): source → sink flows within a
  single file (assignment chains, f-string/template/`.format`/`%`/concat,
  collection construction, same-file calls). Every flow snippet is redacted.
- Schema 1.1 (strictly additive): findings may now carry `id`, `canonical_name`,
  `owasp`, `variant`, `flow`, `gate_eligible`, `dimensions`, `supersedes`,
  `evidence_tags`, `message`. A schema-1.0 reader still consumes 1.1, and a scan
  with no AI findings serializes byte-identically to 1.0 apart from the version.

### Added — eight AI security rules (OWASP LLM Top 10)
Pattern/correlation (no data flow), report-only:
- **AI005** `STOA-LLM05-UNPINNED-MODEL` — `trust_remote_code=True`, unpinned
  `from_pretrained`, floating model aliases, insecure/dynamic endpoints.
- **AI003** `STOA-LLM08-UNOBSERVED-APPROVAL` — high-impact tool capability with
  no approval construct observed (one review prompt per candidate).
- **AI007** `STOA-SAMPLING-CONFIG` — deterministic sampling not observed on a
  high-impact-adjacent model call (proxy signal).
- **CTRL004** `STOA-CTRL-OBSERVABILITY` — tool-binding agent with no logging or
  tracing construct observed.

Taint-based (flow source → sink):
- **AI001** `STOA-LLM01-PROMPT-EXPOSURE` — untrusted input into prompt
  construction; system-role placement escalates confidence.
- **AI002** `STOA-LLM02-OUTPUT-EXEC` — model output into an exec/SQL/deserialize/
  markup/request sink. **The one AI rule that is gate-eligible by default**, and
  only for the exec class at high confidence (zero false positives required on
  the clean corpus — the bar is met).
- **AI004** `STOA-LLM06-SENSITIVE-INTERPOLATION` — secret/PII identifiers into an
  external model call.
- **AI006** `STOA-EXFIL-NETWORK` — secret/PII/model output into non-provider
  network egress; `[rules.AI006].allowed_hosts` exempts approved destinations.

### Added — configuration
- `[gate].additional_rules` — opt in extra rules to the gate.
- `[rules.AI006].allowed_hosts`, `[rules.AI004].pii_terms`.

### Changed
- Gate logic: AI rules gate **only** via `gate_eligible` (AI002 exec/high) or an
  explicit `[gate].additional_rules` opt-in — never from severity alone.
- Deduplication: one root cause, one finding — AI002/sql supersedes SEC003,
  AI005 insecure-endpoint supersedes NET001, AI006 supersedes AI004.

### Fixed
- Writing a report to `/dev/null` (or any non-regular file) no longer errors,
  so the "discard" idiom and correct gate exit codes work.

## 0.1.3 — 2026-07-20
- Vercel AI SDK detection (`generateText`/`streamText`, `createGroq`/`@ai-sdk/*`
  factories, agentic markers); six more frameworks (Mastra, smolagents, DSPy,
  Agno, Google ADK, AWS Strands); LangChain-JS `createReactAgent`; xAI provider;
  vector-DB + MCP capabilities. Summary-first HTML report with an exposure chart.

## 0.1.1 — 2026-07-19
- Widened the NET002 timeout look-ahead window (fixed a false positive).

## 0.1.0 — 2026-07-19
- First public release: local-first AI agent inventory and risk scanner.

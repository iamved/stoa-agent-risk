# Changelog

All notable changes to Stoa are documented here. The registry JSON schema is
versioned separately (see [SCHEMA.md](SCHEMA.md)).

## 0.2.1

### Fixed
- **P0 redaction:** SEC002 (hardcoded password) emitted the raw password value
  in its snippet — only API-key shapes were redacted. The detected value is now
  redacted in every artifact (JSON, HTML, SARIF, annotations, summary).
  Regression test added. Found by the new Meridian end-to-end test bed.

### Added
- `examples/meridian-ops/` — a comprehensive end-to-end test bed (8 agents
  across every framework, both languages, one deliberately well-controlled
  agent) with a `run-e2e.sh` driver asserting 53 checks over the whole tool
  surface, wired into the pytest suite.

## 0.2.0 — v0.2 "Dimension Exposure"

**Every agent assessed across eight risk dimensions — five verified statically,
three flagged for runtime follow-up, all with line-level evidence.**

Registry schema → 1.1 (additive); diff schema `stoa-diff/1.0`.

### Added — dimension exposure ([docs/dimensions.md](docs/dimensions.md))
- An eight-dimension risk taxonomy (`data/dimensions.toml`, replaceable) with
  deterministic scoring and assessability tiers. Proxy-tier dimensions are
  capped at `moderate` (a property test enforces it — Stoa never implies it
  measured behavior it only saw a config signal for).
- Per-agent `dimension_assessment` + top-level `dimension_summary` in the
  registry; a no-JavaScript **Dimension Exposure Matrix** (glyph + color + text)
  with anchor drill-downs and print styles at the top of the HTML report.
- Custom taxonomies with an `unclassified` safety net; `--no-dimensions`,
  `--taxonomy`. SARIF output (`--sarif`) with `stoa-dim:<dimension>` tags.

### Added — `stoa diff` capability drift ([docs/diff.md](docs/diff.md))
- Registry-to-registry drift (`stoa-diff/1.0`): capability/integration/provider/
  population/finding drift + dimension deltas, with a rename pass and a drift
  severity model. `stoa diff BASE HEAD`, `--base-ref` (git worktree), and
  `stoa scan --diff-against`. Markdown changelog for a sticky PR comment.
- In-repo approvals (`.stoa/approvals.toml`, `stoa approve`) bound to a
  line-independent evidence fingerprint — stale when the code changes, never
  hidden. `--fail-on-drift`, `--fail-on-dimension-increase`.
- `stoa init github` wires the drift step into the workflow.

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

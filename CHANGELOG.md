# Changelog

All notable changes to Stoa are documented here. The registry JSON schema is
versioned separately (see [SCHEMA.md](SCHEMA.md)).

## 0.5.0 — "Runtime trace overlay"

Registry schema → 1.4 (additive); assurance packet → `assurance-packet/1.2`.
Everything below is additive and dormant without runtime config/traces: a
repo that never touches the overlay behaves byte-for-byte as 0.4.0 across
`scan`/`diff`/`graph`/`export` apart from the two schema strings. Zero new
required dependencies; zero telemetry — traces are local JSONL files and
never leave the customer's infrastructure. v1 is shadow mode: observe only,
never enforce. See [docs/runtime.md](docs/runtime.md) and
[docs/design/runtime-overlay.md](docs/design/runtime-overlay.md).

### Added — `stoa.runtime` instrumentation SDK
- `configure()` / `@stoa_trace` / `with stoa_span(...)` writing
  `stoa-trace/1.0` JSONL (stdlib-only; the `[runtime]` pip extra is reserved
  for the deferred OTLP exporter). Redact-by-default: string attrs become
  SHA-256 + length; `capture_content=True` + `redaction_hook` to opt in.
  Buffered hot path (~µs), size rotation, warn-once no-op on unwritable
  dirs — instrumentation never crashes or blocks the customer's agent.
  Reuses the scanner's capability/integration/provider vocabulary verbatim.

### Added — `stoa runtime` command group + `stoa scan --with-runtime`
- `analyze` (`runtime-analysis/1.0`; deterministic body, unmatched agents
  and zero-evidence agents always explicit), `map` (agent-id suggestions),
  `baseline` (`runtime-baseline/1.0`, committed like approvals), `drift`
  (`runtime-drift/1.0`; high/medium/info classes, hand-recomputable
  frequency-ratio statistic, `[runtime.drift]` thresholds, report-only
  unless `--fail-on-drift`), `merge` (registry enrichment), and
  `stoa init runtime` scaffolding. `stoa diff` exit-code conventions.

### Added — RT001–RT005, the runtime contradiction detector
- Declared/scanned vs **observed**, each finding citing `trace_ref` +
  `declared_ref`. All `gateable=false` (shadow mode). Config suppression
  for trace-anchored findings (`[runtime].suppress`), counted, never
  hidden. One docs page per rule.

### Added — registry/graph/report/packet integration
- Per-agent `runtime_evidence`; `liveness_state` (reserved since 1.0) now
  live; RT findings on agents; top-level `runtime` block. Graph: reserved
  `"observed"` provenance + `"delegates"` kind now emitted by the overlay —
  corroborated static edges gain `observed: true` (thick in the report,
  "(observed)" in Mermaid), runtime-only reach and delegation render
  dashed/dotted; CSP hash-pinning untouched. Assurance: Area 12 gains
  `observed` monitoring rows, Area 18 populates its reserved `observed`
  provenance; RT findings join the contradictions table (📡 glyph).
- `stoa diff` unconditionally ignores runtime fields and RT findings — no
  phantom drift in code diffs.

### Added — `runtime` dimension assessability tier
- With trace coverage, Conduct variability and Dependency drift re-bucket
  from observed signals per agent per window — no longer capped at
  `moderate` in either direction — carrying `evidence_window` +
  `runtime_basis` and a window-stating statement. Proxy entries without
  runtime evidence stay capped; the original property test is untouched and
  a new one enforces the evidence-window invariant.

### Fixture
- `examples/meridian-ops/traces/` — a hand-auditable 12-span trace fixture
  engineered against Meridian's real declarations (RT001 ×2, RT002, RT003,
  a delegates edge, corroborated edges, a runtime-tier dimension upgrade).

## 0.4.0 — "AIUC-1 alignment"

Registry schema → 1.3 (additive); assurance packet schema → `assurance-packet/1.1`.

### Changed — dimension taxonomy renamed and grouped
- The default taxonomy (`stoa-aiuc-8`, v2.0, replaces `stoa-default-8` v1.0)
  renames all eight dimensions and groups them under the six standard
  categories of [AIUC-1](https://www.aiuc-1.com/), the AI agent trust
  standard — Data & Privacy, Security, Safety, Reliability, Accountability,
  Society. Every `dimension_assessment`/`dimension_summary` entry gains a
  `group` field. See [docs/dimensions.md](docs/dimensions.md) for the full
  old→new id mapping. Custom taxonomies (`[dimensions] taxonomy`) are
  unaffected; `group` is optional and defaults to empty.
- The HTML report's Dimension Exposure Matrix renders a group header row
  above the dimension columns.

### Added — assurance packet grouped under AIUC-1 + a new insurance-only group
- `stoa export --assurance`'s 14 areas become 18, organized under the same
  six AIUC-1 categories plus a seventh Stoa-only group (`G` — insurance-
  specific exposure: business exposure, economic authority, claims evidence)
  that AIUC-1 doesn't cover. New areas: Security testing (split out from the
  old combined Testing area), Safety evaluation, Reliability scores
  (surfaces per-agent Reliability-group dimension scores in the packet for
  the first time), Vendor due diligence, and Societal impact (declared,
  attestation-only, never scored). "Governance" is renamed "Accountability".
  See [docs/assurance-export.md](docs/assurance-export.md).
- Two new declared fields: `business.societal_risk_flags`,
  `governance.harmful_output_policy`. Two new `evidence` categories:
  `safety_testing`, `vendor`. See [docs/declarations.md](docs/declarations.md).

This grouping is a display header and interoperability aid, not an AIUC-1
certification claim — certification requires their accredited-auditor process.

### Added — "Download report" button
- `stoa-report.html` now has a "Download report" button that saves the
  currently-rendered page as a standalone `.html` file — client-side only
  (no server, no new dependencies), useful whether the report was opened
  locally or from a shared/hosted link. Its script is fixed, repo-data-free
  content, CSP hash-pinned like the existing architecture-graph scripts —
  never `'unsafe-inline'`.

## 0.3.0 — "Real-world detection quality"

Driven by running Stoa against a production codebase. Three problems it exposed —
a missed agentic surface, a wall of low-value noise, and control false negatives —
are addressed directly.

### Agent inventory accuracy
- **Framework-independent agentic control flow.** Stoa now detects a model call
  inside a loop (via AST) and multi-step generation (≥2 model call sites) as
  agentic, so hand-rolled agents built on direct provider SDKs — not LangChain/
  CrewAI/etc. — are inventoried instead of slipping through.
- **MCP servers are an agentic surface.** `FastMCP(...)`, `@mcp.tool`, and
  `@modelcontextprotocol/sdk` are detected (framework `mcp`) and mapped to the
  scope-violation and unauthorized-action dimensions.
- **Provider/pipeline files are no longer mislabeled agents.** A candidate now
  requires an actual agentic signal (loop-driven or multi-step model use, tools,
  an execution surface, or an agent constructor); an LLM SDK import plus a single
  one-shot generation call — an image/TTS/generation utility — no longer qualifies.

### Noise reduction & prioritization
- **NET001 (insecure HTTP) and REL001 (swallowed exception) are dropped to `low`**
  and **skipped in test paths**, where they were the dominant false positives.
  They are code smells, rarely risks.
- **Every finding now carries a `message`.** Core rules previously left the field
  null in JSON, breaking downstream prioritization; it is now always populated.

### Control detection
- **Broadened control recognition** — auth (Firebase/Clerk/Auth0/JWT/session),
  input validation, rate limiting, and observability (Loki/Datadog/Sentry/OTel/
  Prometheus) — so common stacks are credited.
- **Repo-level control awareness.** A CTRL prompt now fires only when the control
  is observed neither in the file nor anywhere in the repository, eliminating
  "not observed" findings for controls that live in shared middleware/infra.

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

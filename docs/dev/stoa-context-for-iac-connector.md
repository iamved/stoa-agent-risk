# Stoa — full feature context (for designing the Terraform / IaC connector)

This is a self-contained brief on what the `stoa-agent-risk` package does today
(v0.6.1, registry schema 1.5) so an external assistant can help design an
Infrastructure-as-Code (Terraform / Databricks Asset Bundle) connector that fits
the existing architecture. Everything below is verified against the source
tree; nothing is aspirational except the final section, which states the gap
the connector must close.

---

## 1. What Stoa is

**A local-first AI agent inventory and risk scanner.** It statically scans a
repository, finds *AI agent candidates* with supporting evidence, maps each
one's providers / frameworks / integrations / capabilities, runs a rule set
(secrets, injection, OWASP-LLM data-flow rules, missing-control prompts,
declared-vs-observed contradictions), scores every agent across an
eight-dimension risk taxonomy, and emits a deterministic JSON registry plus a
self-contained HTML report. It can gate CI on *newly introduced*
high-confidence critical findings and on *capability drift* between two scans.

Hard invariants the whole design honors:

- **Local-first.** No network calls, no telemetry, no uploads, no accounts.
  tree-sitter grammars ship in the wheel; nothing is downloaded at runtime.
- **Secrets are redacted the moment they are matched** — a credential becomes
  `prefix…[REDACTED:sha256-fingerprint]` before it reaches JSON, HTML, SARIF,
  annotations, logs, or terminal output.
- **Deterministic output.** No timestamps in the registry; same tree + same
  config → byte-identical JSON. Dimension scores are guarded by golden
  snapshots.
- **Evidence, not verdicts.** Everything is a "candidate" with line-level
  evidence. Vocabulary discipline is enforced by tests: Stoa says "exposure
  observed" / "none observed" / "control observed"; it never says "safe",
  "covered", "compliant", "protected", "mitigated".
- **Additive-only schema.** Consumers must ignore unknown fields. New
  optional fields bump the minor version. Reserved field names exist for
  future layers.
- **Report-only by default.** Only a small, documented set of rules can ever
  fail a build.

Stack: Python ≥3.10, dependencies `pathspec`, `tree-sitter` + 
`tree-sitter-language-pack`, `tomli` on <3.11. Package `stoa`, entry point
`stoa = stoa.cli:main`. MIT. Published on PyPI as `stoa-agent-risk`.

---

## 2. Languages and file traversal (the current input surface)

- **Scanned languages: Python, JavaScript, TypeScript only.** Extensions
  mapped in `traversal.py`: `.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`,
  `.tsx`. Anything else is invisible — **`.tf`, `.hcl`, `.yml`, `.yaml`, `.json`
  are not read today.** This is the gap the IaC connector closes.
- Traversal respects the repo-root `.gitignore` and `.stoaignore` (gitignore
  syntax), a built-in ignore list (`node_modules`, `dist`, …), `max_file_bytes`
  (1 MB default), `follow_symlinks`, `--include` / `--exclude` patterns.
  `include_extensions` is a `stoa.toml` key, so adding extensions is already a
  config-level concept.
- Each file gets a `language` and an `is_testlike` flag (test/fixture paths
  are still scanned for secrets but downweighted for agent detection, and
  NET001 / REL001 are skipped there).
- Skipped files and pruned directories are listed in the registry
  (`skipped_files`, with a reason). Files whose AST parse degraded are listed
  in `degraded_files`. Nothing is silently dropped.

---

## 3. The scan pipeline (`scanner.run_scan`)

Order of operations, because a connector has to slot into it:

1. Load config (`stoa.toml`), traverse, read every file once.
2. **Repo-wide control pre-pass** (`scan_repo_controls`): learn which
   controls (auth, validation, rate limiting, observability) exist *anywhere*
   in the repo so per-agent "control not observed" prompts do not fire for
   controls that live in shared middleware.
3. Per file:
   - parse inline suppressions (`# stoa: ignore[RULE]`);
   - `detect_risks` (regex core rules SEC/REL/NET) + `detect_ai005`;
   - `detect_providers`;
   - AST parse (tree-sitter, cached) → `detect_ai_taint` (AI001/002/004/006
     intra-file source→sink flows);
   - `detect_agents` → zero or more detections with a score, confidence,
     frameworks, evidence list, and a stable id;
   - if any agent: `detect_capabilities`, `detect_permission_tags`,
     `detect_integrations` (with call-site counts), then per medium/high
     candidate the CTRL prompts (CTRL001–004, AI003 correlations, CTRL005,
     CTRL006, CTRL007);
   - build `AgentCandidate` objects; every agent in a file carries that
     file's findings.
4. Disambiguate colliding agent names by source file (`payments·agent`).
5. Git metadata: repo name, HEAD ref, `last_touched_by`, `last_commit`,
   CODEOWNERS.
6. Diff marking (`--base`): findings on added lines get `is_new = true`.
7. Supersedes pass (e.g. AI002/sql supersedes SEC003 on the same site).
8. **Autonomy inference** per agent (`infer_autonomy`).
9. Load `stoa-declared.toml` (opt-in by presence); attach `declared` per
   agent; run the **contradiction detector** (DECL001–007).
10. **Dimension assessment** per agent + org-level `dimension_summary`.
11. Sort deterministically, return `ScanResult`.

Then the CLI writes JSON (`report_json.build_document`, which also annotates
the regulatory crosswalk), HTML (`report_html`), optional SARIF, GitHub
annotations / job summary, and evaluates the gate.

Key in-memory models (`models.py`):

- `AgentCandidate`: `id, name, symbol, path, language, confidence,
  detection_score, display_name, evidence[], providers[], frameworks[],
  integrations[], capabilities[], permission_tags[], call_sites{},
  last_touched_by, last_commit, codeowners[], findings[],
  dimension_assessment, declared, autonomy_level`.
- `Finding`: `fingerprint, rule_id, title, category, severity, confidence,
  path, line, column, snippet, remediation, suppressed, suppression_reason,
  is_new, canonical_name, owasp, flow[], gate_eligible, dimensions[],
  supersedes[], variant, evidence_tags[], message, declared_ref`.
- `Evidence`: `rule_id, line, description`.
- `ScanResult`: `repository, files_scanned, agents[], findings[],
  skipped_files[], warnings[], diff_available, degraded_files[],
  dimension_summary, business, governance, evidence, declaration_warnings[]`.

**Agent identity:** `id = sha256("<path>:<symbol>")[:12]`. It is stable across
scans of the same source identity and is the join key for declarations
(`[agents."<id>"]`), approvals, runtime traces (`agent_id`), and the graph.
An IaC-sourced agent needs an identity in the same shape (a path + a symbol,
e.g. `infra/main.tf:databricks_model_serving.refund_agent`).

---

## 4. Agent detection (what makes something an "agent candidate")

Weighted evidence scoring in `agent_detection.py`:

| Signal | Score |
|---|---|
| Framework agent constructor (LangChain, LangGraph, CrewAI, AutoGen, LlamaIndex, OpenAI Agents SDK, PydanticAI, Bedrock Agents, Semantic Kernel, Vercel AI SDK, Mastra, smolagents, DSPy, Agno, Google ADK, AWS Strands, MCP server) | +5 |
| Model call inside a loop (AST; SDK call or raw HTTP to a known model endpoint) | +4 |
| Execution surface (`exec`/`subprocess`/shell etc.) | +3 |
| Multi-step generation (≥2 model call sites) | +2 |
| Provider call | +2 |
| Tool binding (`tools=[...]` kwarg or `"tools": [...]` JSON key) | +2 |
| Provider import | +1 |
| Agent-like class name | +1 |
| Test-like path | −3 |

Thresholds: high ≥ 8, medium ≥ 5, low ≥ 3. A candidate **must** have an
actual agentic signal (loop/multi-step model use, tools, an execution surface,
or an agent constructor) — an SDK import plus one generation call is not an
agent. Every candidate lists *why* it was detected (`evidence[]`, each with a
rule id like `AGENT_LANGCHAIN`, a line, and a description).

**Vocabularies** (flat string ids reused everywhere — registry, graph,
runtime SDK, drift, dimensions). An IaC connector should emit these same ids
wherever a resource maps to them, and add new ones only when necessary:

- **Providers (15):** `openai, anthropic, google, azure_openai, bedrock, groq,
  cohere, together, mistral, xai, perplexity, huggingface, ollama, openrouter,
  litellm`.
- **Frameworks (17):** `langchain, langgraph, crewai, autogen, llamaindex,
  openai_agents_sdk, pydantic_ai, bedrock_agents, semantic_kernel,
  vercel_ai_sdk, mastra, smolagents, dspy, agno, google_adk, strands, mcp`.
- **Capabilities (23):** `tool_calling, function_calling, database_read,
  database_write, code_execution, shell_execution, filesystem_read,
  filesystem_write, web_search, browser_automation, external_http,
  email_send, messaging, payment_access, customer_support, source_control,
  document_processing, pdf_processing, cache_access, queue_access,
  cloud_resource_access, vector_search, mcp_tools`.
  A subset is `HIGH_IMPACT_CAPABILITIES` (payment, db-write, shell/code exec,
  email/messaging, filesystem write, source control, cloud resource access,
  mcp_tools) — these drive AI003, autonomy, drift severity, and dimensions.
- **Permission tags (higher-stakes layer over capabilities):** `move_funds,
  approve_transactions, sign_contracts, delete, communicate`.
- **Integrations (34):** `slack, stripe, github, gitlab, zendesk, salesforce,
  hubspot, twilio, sendgrid, ses, datadog, sentry, postgres, mysql, mongodb,
  redis, snowflake, bigquery, aws, gcp, azure, jira, linear, notion,
  confluence, servicenow, shopify, pinecone, weaviate, chroma, qdrant, milvus,
  google_places, eventbrite`. Each carries a `call_sites` count (static match
  count, explicitly *not* an API call count). Note: no `databricks` integration
  id exists yet.
- **Observed controls (credit exposure):** `approval, authentication,
  validation, rate_limit, observability, deterministic_sampling, pinned_model`.

---

## 5. Rules

All rules have a stable short id (used in suppressions, `stoa.toml`,
gating) and, for AI rules, a canonical name used in SARIF.

**Core (regex):**

| Rule | Title | Severity | Gates? |
|---|---|---|---|
| SEC001 | Possible hardcoded API credential | critical | yes, high confidence only |
| SEC002 | Possible hardcoded password | high → critical at high conf. | yes, high confidence only |
| SEC003 | Interpolated SQL statement | high | no |
| REL001 | Swallowed exception | low | no |
| NET001 | Insecure non-local HTTP endpoint | low | no |
| NET002 | Request timeout not observed | medium | no |
| CTRL001–003 | Auth / validation / rate-limit not observed | info | never |
| CTRL005 | Rate limiting not observed on a high-impact-capability loop | low | never |
| CTRL006 | Sandboxing not observed on an exec path | low | never |
| CTRL007 | No kill-switch signal on the agent's entry path | info | never |

**AI rules (OWASP LLM Top 10; AI001/002/004/006 are intra-file taint flows
via the tree-sitter AST, disabled by `--no-ast`):**

| Rule | Canonical | Severity | Gates? |
|---|---|---|---|
| AI001 | STOA-LLM01-PROMPT-EXPOSURE | high | opt-in |
| AI002 | STOA-LLM02-OUTPUT-EXEC (model output → exec/sql/deserialize/request sinks) | critical | **yes, exec class at high confidence** — the only AI rule that can fail a build |
| AI003 | STOA-LLM08-UNOBSERVED-APPROVAL (high-impact capability, tool-bound, no approval construct) | info | never |
| AI004 | STOA-LLM06-SENSITIVE-INTERPOLATION | medium / high for secrets | no |
| AI005 | STOA-LLM05-UNPINNED-MODEL (variants: floating-alias, trust-remote-code, unpinned-artifact, insecure-endpoint) | low–high | no |
| AI006 | STOA-EXFIL-NETWORK (egress outside `[rules.AI006] allowed_hosts`) | high | opt-in |
| AI007 | STOA-SAMPLING-CONFIG | info | never |
| CTRL004 | STOA-CTRL-OBSERVABILITY | info | never |

**Contradiction detector (declared vs scanned, needs `stoa-declared.toml`):**

| Rule | Fires when | Severity |
|---|---|---|
| DECL001 | declared `recommend_only`/`human_approved`, inferred `bounded_autonomous`/`unrestricted_autonomous` | critical |
| DECL002 | `economic_authority` declared, no bounding signal on the money path | high |
| DECL003 | money/contract permission tag, no `economic_authority` declared | high |
| DECL004 | scanner evidence of a data class not in declared `data_classes` | high |
| DECL005 | `production_status = "production"` but CTRL004 fired | medium |
| DECL006 | scanned agent has no declaration entry | medium |
| DECL007 | declared agent id matches no scanned agent | low |

Every DECL finding carries both `path`/`line` (code side) and
`declared_ref: {path, key}` (the exact TOML key it contradicts).

**Runtime contradiction detector (RT001–RT005)** — emitted only by
`stoa runtime merge`, never by `scan`; each carries a `trace_ref`. All
report-only.

**Suppression:** inline `# stoa: ignore[SEC003] reason` (same or preceding
line), file-wide `# stoa: ignore-file[CTRL001,CTRL002]`, always with explicit
rule ids, no blanket ignore. Suppressed findings are counted and shown, never
hidden. Trace-anchored RT findings suppress via `stoa.toml` `[runtime].suppress`.

**Gate:** only high-confidence findings from gate-eligible rules (SEC001,
SEC002, AI002 exec class, plus DECL001–005, plus `[gate] additional_rules`)
can fail a scan. Default `fail_on = "none"`, `fail_on_new = "critical"`
(applies only with `--base`). Exit codes: 0 pass, 1 gate failed, 2 bad
args/config, 3 scanner error.

---

## 6. Autonomy inference (always on)

Every agent gets `autonomy_level = {level, signals[], reason}` with `level ∈
recommend_only | human_approved | bounded_autonomous |
unrestricted_autonomous | indeterminate`, composed from existing signals:

- AI002 with a side-effecting variant ⇒ a side-effecting path exists (none ⇒
  `recommend_only`).
- AI003 firing ⇒ no approval gate; an `APPROVAL_CONSTRUCT` match without AI003
  ⇒ `human_approved`.
- A same-file bounding signal (hardcoded cap check, rate limiter) ⇒
  `bounded_autonomous`.
- Neither ⇒ `unrestricted_autonomous`; unresolvable ⇒ `indeterminate` with a
  stated reason (never a guess).

---

## 7. Declarations (`stoa-declared.toml`)

Human-supplied, git-reviewed facts, keyed by scanned agent id. Stubbed by
`stoa init declarations`. Sections:

- `[business]`: `industries[]`, `regulated_activities[]`,
  `max_customer_dependency` (low|medium|high|critical),
  `societal_risk_flags[]` (attestation only).
- `[agents."<id>"]`: `name, owner, purpose, users
  (internal|customers|public), geography[], production_status
  (dev|staging|production|deprecated), autonomy_intent (the four levels),
  data_classes[] (personal|financial|health|confidential|ip|authentication)`,
  and `[agents."<id>".economic_authority]` with `max_per_action`,
  `daily_aggregate`, `worst_case_customer_loss` as `{amount, currency}`.
- `[governance]`: `release_approval, incident_response,
  harmful_output_policy, [governance.risk_acceptance] {owner, date}`.
- `[[evidence.<category>]]` pointers `{kind, ref, date?}`; recognized
  categories `testing, safety_testing, monitoring, contracts, historical,
  vendor`.

Malformed TOML fails the scan; bad enum values / unknown keys / stale ids are
warnings (hard failures under `--strict`).

---

## 8. Dimension exposure (the scoring layer)

Default taxonomy `stoa-aiuc-8` v2.0 (`data/dimensions.toml`, replaceable via
`[dimensions] taxonomy`), grouped under the six categories AI agent trust standards share:

| Group | Dimension id | Assessability |
|---|---|---|
| A Data & Privacy | `boundary-leakage` | strong |
| B Security | `mandate-overreach` | strong |
| B Security | `injection-tamper-surface` | partial |
| B Security | `control-coverage-gap` | partial |
| C Safety | `unreviewed-high-impact-action` | strong |
| D Reliability | `output-fidelity` | partial |
| D Reliability | `conduct-variability` | proxy |
| D Reliability | `dependency-drift` | proxy |

Per agent per dimension:

```
score = min(100, Σ finding_weight(severity)×confidence_multiplier
              + Σ capability_weight (18 each mapped capability)
              + provider_weight (8, dependency-drift)
              − Σ control_credit (20 per observed control, floor 0))
buckets: 0 none-observed · 1–24 low · 25–54 moderate · ≥55 elevated
```

Proxy dimensions are capped at `moderate` (property-tested); only the runtime
overlay can lift the cap, and only with an `evidence_window`. The taxonomy
file maps `rule → dimensions`, `capability → dimensions`, and
`observed control → dimensions it credits`. Every entry carries
`contributing_findings`, `contributing_capabilities`, `controls_observed`, and
a plain-English `statement`. Registry: per-agent `dimension_assessment`,
top-level `dimension_summary` (max exposure + agent counts per dimension).
SARIF results carry `stoa-dim:<dimension>` tags.

**For the connector:** grants like `ALL_PRIVILEGES` on a catalog naturally
feed `mandate-overreach`; `MODIFY` on a payments table feeds `database_write`
→ `mandate-overreach` + `unreviewed-high-impact-action`; an `ai_gateway`
block with guardrails / rate limits / inference tables maps onto the existing
`validation`, `rate_limit`, `observability` controls, which *subtract*
exposure via `control_credit`.

---

## 9. Regulatory crosswalk (annotation only)

`data/crosswalk.toml` (`stoa-crosswalk-1`) maps each rule to one OWASP LLM
Top 10 (2025) class (or an honest blank) and one EU AI Act article, with a
plain-English `so_what`. Emitted as `crosswalk` on every finding, a roll-up on
each `dimension_summary` entry, and a top-level version block; SARIF gains
`owasp:` / `euaiact:` tags. Never touches scoring. Overridable via
`[crosswalk] path`.

---

## 10. Outputs

- **`stoa-registry.json`** (schema 1.5): top-level `schema_version, tool,
  repository {name, root, git_ref, base_ref}, summary {files_scanned,
  agent_candidates, high_confidence_candidates, integrations, findings{by
  severity}, new_findings{}, suppressed_findings}, agents[],
  repository_findings[] (findings in non-agent files), skipped_files[],
  warnings[], degraded_files[], dimension_summary, crosswalk, business,
  governance, evidence, runtime` (last four only when their source exists).
- **`stoa-report.html`**: self-contained, offline, strict CSP. Verdict-first
  IA: Verdict → Scoreboard → Fix first → Contradictions → Agents → Risk
  dimensions → Standards → Appendix; ≤5 printed pages; interactive
  Cytoscape architecture graph (hash-pinned scripts); "Download report" and
  "Generate underwriting evidence" buttons. Presentation thresholds in
  `data/report.toml` (overridable at `.stoa/report.toml`).
- **SARIF** (`--sarif`) for GitHub Code Scanning.
- **GitHub annotations** (`--github-annotations`) and a job-summary Markdown
  (`--summary-file`).
- **Mermaid graph** (`stoa graph`).
- **Assurance packet** (`stoa export --assurance`, `assurance-packet/1.2`,
  json or md): 18 areas under six trust-standard groups + a Stoa-only insurance
  group; every row has a status `scanned | declared | ingested | observed |
  not_provided`.
- **Underwriting evidence** (`stoa export --underwriting
  [--underwriting-config applicant.toml]`): a pre-filled AI Model Risk
  Assessment HTML (aiSure-style) with print-to-PDF.
- **Drift artifacts** (`stoa-diff/1.0` JSON + Markdown changelog).
- **Runtime artifacts** (`runtime-analysis/1.0`, `runtime-baseline/1.0`,
  `runtime-drift/1.0`, enriched registry).

---

## 11. CLI surface

```
stoa scan [PATH] --html --json --sarif --base REF --strict
          --fail-on {none,high,critical} --fail-on-new {…}
          --github-annotations --summary-file PATH --config PATH
          --no-git --no-ast --no-dimensions --no-graph --taxonomy PATH
          --include/--exclude PATTERN --verbose/--quiet
          --with-runtime TRACES_DIR
          --diff-against REF --diff-json PATH --diff-md PATH
          --fail-on-drift {none,low,medium,high}
          --fail-on-dimension-increase DIM=LEVEL --approvals PATH
stoa init {github|declarations|runtime} [--force] [--registry PATH]
stoa diff [BASE] [HEAD] | --base-ref REF  --json --md --summary
          --fail-on-drift --fail-on-dimension-increase --approvals
stoa graph [REGISTRY] --format mermaid --out PATH --focus AGENT_ID
stoa export [REGISTRY] --assurance | --underwriting
            [--underwriting-config PATH] --format {json,md} --out PATH
stoa approve --agent-id ID (--capability|--integration|--provider|--new-agent)
             --reason TEXT --by HANDLE [--expires DATE] | --list
stoa runtime {analyze|map|merge|baseline|drift} TRACES_DIR [--registry …]
```

`stoa init github` writes `.github/workflows/stoa.yml` (pinned PyPI install,
full-history checkout, diff against PR base, annotations, job summary,
artifacts, gate only on new high-confidence criticals, drift step),
`.stoaignore`, and `stoa.toml`.

---

## 12. Configuration (`stoa.toml`)

Keys: `fail_on, fail_on_new, max_file_bytes, follow_symlinks,
respect_gitignore, include_extensions[], ignore_paths[],
include_suppressed_in_json`, `[severity] RULE = level`, `[rules] RULE =
bool`, `[rules.AI006] allowed_hosts[]`, `[rules.AI004] pii_terms[]`, `[gate]
additional_rules[]`, `[dimensions] taxonomy`, `[crosswalk] path`, `[report]
path`, `[runtime] trace_dir / redaction / exporter / suppress[]`,
`[runtime.drift]` thresholds, `[runtime.dimensions]` error-rate thresholds.
Loaded into a `StoaConfig` dataclass in `config.py`. A connector would most
naturally add an `[iac]` table (enable, paths, platform hints) and extend
`include_extensions` with `.tf`, `.yml`, `.yaml`.

---

## 13. Capability drift (`stoa diff`) and approvals

Compares two registries and reports capability / integration / provider /
population / finding drift plus dimension deltas, as **call sites added or
removed in code**. Drift severity: existing agent gains a high-impact
capability or sensitive integration, or a new agent with one ⇒ **high**;
other additions / confidence increase ⇒ medium; removals ⇒ info. Renamed or
moved agents are matched by Jaccard ≥ 0.70 on line-independent evidence
fingerprints. Approvals live in-repo (`.stoa/approvals.toml`), bound to an
evidence fingerprint, go stale when the code changes, and never hide drift.
`stoa diff` ignores runtime fields and RT findings unconditionally.

IaC-sourced agents and their reach must participate in this drift model: a
Terraform change that widens a grant from `SELECT` to `ALL_PRIVILEGES` is
exactly the "existing agent gains a high-impact capability" event.

---

## 14. Architecture graph

`graph_model.build_graph(registry)` derives nodes from registry fields on
demand (no schema change): `agent` (rectangle), `mcp_server` (hexagon,
frameworks includes `mcp`), `tool` (one per integration/provider id),
`resource` (one per capability class). Edge kinds `tool_call, mcp, reads,
writes, network, delegates`; provenance `declared` (static) or `observed`
(runtime overlay). Edges carry the specific findings that explain them via a
rule-id correlation table. A new IaC node type (serving endpoint, grant, or a
`platform` attribute on the agent node) would extend this model.

---

## 15. Runtime trace overlay (shadow mode)

`stoa.runtime` SDK: `configure()`, `@stoa_trace`, `stoa_span` write
`stoa-trace/1.0` JSONL (stdlib-only, redact-by-default, µs hot path, never
crashes the host). Span kinds: `agent_run, llm_call, tool_call, action,
approval, retrieval, delegation`; spans reuse the scanner's capability /
integration / provider vocabulary. `stoa runtime analyze / map / baseline /
drift / merge` and `stoa scan --with-runtime` add per-agent
`runtime_evidence`, `liveness_state` (`active|idle`), RT001–RT005, observed
graph edges, a `runtime` dimension tier, and assurance Areas 12/18. v1
observes and never enforces.

---

## 16. Examples and tests

- `examples/meridian-ops` (8 agents, every framework, both languages,
  `run-e2e.sh` with 53 assertions, plus a hand-auditable trace fixture),
  `examples/sparkwing`, `examples/support-desk`, `examples/threshold-voice`.
- `tests/` — ~38 pytest modules covering each layer, parity between report
  and registry, HTML escaping, redaction, property tests (proxy cap,
  evidence-window invariant), golden snapshots for scores, and report budget.
- Documentation site in `site/` (Vercel) plus `docs/` (rules, dimensions,
  diff, declarations, autonomy, graph, runtime, crosswalk, assurance,
  underwriting, report).

---

## 17. The IaC gap and the Tidewater fixture (what the connector must do)

`examples/tidewater/` is an untracked, already-written acceptance fixture for
the connector: a fictional payments company with two Databricks-hosted agents.

- `infra/main.tf` (Terraform, provider `databricks/databricks`): two
  `databricks_model_serving` endpoints (`support_agent` with a full
  `ai_gateway` block — PII guardrail `BLOCK`, output `safety = true`,
  `inference_table_config`, `rate_limits 100/minute`, `usage_tracking`;
  `refund_agent` with **no** `ai_gateway` and an `OPENAI_API_KEY` env var
  pointing at a secret scope); `databricks_grants` (support: `SELECT` on
  `prod.customers.transactions`; refund: `ALL_PRIVILEGES` on catalog `prod`
  plus `SELECT, MODIFY` on `prod.payments.refunds`); a
  `databricks_vector_search_index` (RAG source); two
  `databricks_service_principal` identities.
- `databricks.yml`: the same two endpoints as a Databricks Asset Bundle —
  the second input format.
- `agents/support_agent.py` and `agents/refund_agent.py`: code that registers
  the Unity Catalog models `prod.agents.support_agent` /
  `prod.agents.refund_agent`. The endpoint's `served_entities.entity_name` is
  the **join key** between IaC and code.
- `stoa-declared.toml`: `refund_agent` declared `human_approved` (planted
  DECL001); `support_agent` declared accurately.

**Today (v0.6.1)** the scan reads 2 files, finds 2 code agents, and the IaC
layer is invisible.

**Acceptance criteria written into the fixture's README:**

1. Find both serving endpoints from `infra/main.tf` and `databricks.yml` as
   agents with `source: iac`, `platform: databricks`, and evidence at the
   resource's `file:line`.
2. Read `support_agent`'s reach as one `SELECT` on
   `prod.customers.transactions` and credit its `ai_gateway` guardrail, rate
   limit, and inference tables as **controls observed**.
3. Read `refund_agent`'s `ALL_PRIVILEGES` on `prod` as **mandate overreach**,
   its `MODIFY` on `prod.payments.refunds` as write reach, and the absent
   `ai_gateway` as a **control coverage gap**.
4. Join each endpoint's `entity_name` to the code that registers that UC
   model, and hand that code to the taint scanner (so AI002 / DECL001 on the
   refund agent attach to the deployed endpoint, not just the file).

The fixture README also documents four *code-side* detector gaps discovered
while building it (Spark `spark.sql` not a SQL sink; `tool_calls[...].function.arguments`
not a model-output taint source; the approval heuristic matching comments and
docstrings; `tools=TOOLS` identifier bindings not recognized), each with a
proven regex/AST fix. Those are separate from the connector but interact with
criterion 4.

**Design constraints the connector inherits** (from everything above):

- Static, local, no network, no `terraform` binary or provider plugins
  required at scan time — parse HCL and YAML from disk.
- Deterministic output; new registry fields must be additive (schema → 1.6)
  and absent when no IaC is present, so a repo without IaC serializes
  byte-identically apart from `schema_version`.
- Agent ids must be stable (`sha256(path:symbol)[:12]` shape) so
  declarations, approvals, drift, graph, and runtime traces keep joining.
- Reuse the existing vocabulary ids for capabilities / integrations /
  providers / controls; where a platform concept has no id (e.g. a
  `databricks` integration, a `serving_endpoint` node type, `source`/
  `platform` agent fields), add it additively and document it in SCHEMA.md.
- Controls seen in IaC must flow into `observed_controls` /
  `controls_observed` so they *credit* exposure through the existing
  `control_credit` math rather than through a new scoring path; findings
  must map to existing dimensions via `data/dimensions.toml`.
- Evidence language stays "observed" / "not observed"; never "compliant".
- Redact anything secret-shaped in HCL/YAML (env vars, tokens) with the
  existing `redaction.py` helpers before any serialization.
- Must be exercised by the Tidewater fixture in the pytest suite, the way
  Meridian drives `test_e2e_meridian.py`.

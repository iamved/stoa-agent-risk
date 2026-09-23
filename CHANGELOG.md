# Changelog

All notable changes to Stoa are documented here. The registry JSON schema is
versioned separately (see [SCHEMA.md](SCHEMA.md)).

## Unreleased — "The dashboard"

Registry schema → 1.8 (additive). `stoa scan` now also writes
`stoa-dashboard.html`: one self-contained file, six screens, no server, no
network. See [docs/dashboard.md](docs/dashboard.md).

### Added — the dashboard
- **Six screens** over the scan: Overview (eight-dimension matrix by
  category, decomposable to the agents that produce each level; stat cards;
  top five findings as plain-English "so what" sentences; framework class
  strip with gaps kept visible; trends from history), AI inventory (category
  rail derived from the registry, per-category tables, an agent drawer with
  declared versus scanned, and the architecture graph), Findings (filters in
  the URL hash, a virtualized table that stays responsive at 5,000 rows, a
  drawer with What this check does / Why it matters / How to fix), Drift
  (the `stoa-diff/1.0` document grouped for review; unapproved authority
  increases first), Risk register (rows from the scanner's own levels,
  treatments declared in `stoa-declared.toml`, TOML snippet to paste), and
  Evidence (risk-officer and underwriter views, two print renderings).
- **Framework selector** (OWASP LLM Top 10 2025, EU AI Act, NIST AI RMF)
  changes labels and grouping only. No score moves.
- **CLI**: `stoa scan --dashboard PATH | --no-dashboard | --open |
  --no-history`; `stoa dashboard REGISTRY [--baseline REGISTRY] [--out]
  [--open]`. `--html` is now the legacy summary report and keeps working.
- **History**: each scan in a git repository records a per-commit summary
  under `.stoa/history/` (`[dashboard] history_keep`, default 10) for trend
  lines. Never used for drift.
- **Schema 1.8**: `repository.head_commit` (commit date, never wall clock),
  `score_before_controls` on every dimension entry, and a top-level
  `risk_register` echoing `[[risk_register]]` from `stoa-declared.toml`.
- **`[[risk_register]]`** in `stoa-declared.toml`: `risk_id`
  (`<dimension-id>/<agent-id>`), `owner`, `treatment`, `rationale`,
  `review_by`, `status`.

### Changed — the demo, and a scanner count
- The Meridian Pay example drops its Databricks stack. Its support agent is
  now a LangGraph chatbot in code that binds the account tools directly, the
  new customer-facing system of the September push. Its scan history shows
  the two months before: amounts capped in code, no tools on AWS yet, no
  chatbot. The Overview and Financial Exposure draw the largest single-agent
  modeled loss over that history: $3.4M, $3.5M, $5.0M.
- A finding on a tool bound by two agents was counted once per agent in the
  registry summary, SARIF and the CLI. It is one finding, on both agents,
  counted once.

### Changed — third review
- The demo is five agents in three places: three in code (front, account
  actions, the support chatbot), one on AWS (knowledge) and one on Databricks
  (escalation). Identity resolution and drift keep their end-to-end coverage
  on a second fixture (`ui/fixtures/two-stacks.envelope.json`: the example
  plus a Bedrock twin of account-actions).
- Overview: the verdict is one sentence derived from the trend and the
  history (how much the modeled loss rose, over what span, which push did it,
  what went live and which cap came off). Agent Inventory says who the agents
  serve and names the newest one. Risk Mapping lists each high-severity
  finding with its agent. Protection Level carries a four-safeguard scorecard
  with the Controls screen's counts. The cost tile draws the declared policy
  limit and the cover that applies to AI losses as reference lines. What
  changed is three lines; Needs your attention rows say what the scan saw,
  why it matters and the fix, with no rule ids or dimension names.
- Declared Scope names agents the way every other screen does.

### Changed — second review
- Overview tiles are Agent Inventory, Risk Mapping, Protection Level and
  Estimated Failures Cost. Risk Mapping names the high-severity findings.
  Estimated Failures Cost draws the modeled bad-year loss over past scans;
  history entries (schema 1.1) now carry the agent fields the loss model
  reads, and the model takes the unique agent with its records merged.
  "Needs your attention" is three items in plain words; findings carry plain
  titles and actions on the summary screens (the scanner's sentences stay in
  the drawer). The elevated-exposure and register cards are gone. The flow
  graph draws two agent safeguards, harness first. Financial Exposure gains
  "How the modeled loss has moved" and shows at most two cases per loss
  type, US financial services first, then other US sectors, then elsewhere;
  Data Loss and Corruption and Performance Failure are not listed.

### Changed — after review
- The header names the applicant's company; the scope strip is gone. No
  demo banner. Controls & Safeguards drops its headline tiles, lists
  safeguards without human approval and sandboxing, and ends with
  "Recommended controls to add": three, in plain words. Financial Exposure
  drops the curve, the year tiles and the declared-limits table, and shows
  only US financial-services cases with a public record under $300M. The
  flow graph has no side panel.

### Added — the Agent Risk Flow Graph
- The Overview ends with one agent's risk path in five steps (request, agent,
  approval gate, tools, reach), with safeguards and guardrails marked
  detected or not, findings placed on the step they belong to, and a detail
  panel per box. Drawn for unique agents from the same data as the tiles
  above it. Merged tools now carry the effects seen in any of their records.

### Added — beyond the demo
- **Open your own scan in any dashboard page.** `stoa scan --dashboard-json`
  and `stoa dashboard --json-out` write the dashboard's data (redacted like
  the embedded copy). The reviewer menu, a drop anywhere on the page, and a
  banner on the hosted demo open that JSON or a whole `stoa-dashboard.html`.
  The file is read in the browser under `connect-src 'none'`; its shape is
  validated first, and a refused file leaves the scan on screen unchanged.
- **The scan at a glance in the terminal.** `stoa scan` appends dimensions
  above low exposure, the top findings (one per rule first) and what to set
  up next; `stoa dashboard --summary` prints the full view. Same data as the
  page, the scanner's own vocabulary, plain deterministic text.
- `stoa init underwriting` scaffolds `.stoa/underwriting.toml`, inert until
  filled in. `[repository] name` in `stoa.toml` overrides the reported name.
- Fixtures and browser tests for a first scan (`first-run`) and a scan that
  finds no agents (`no-agents`). The hosted demo is now generated by
  `scripts/build_site_dashboard.sh`, and a test fails when it goes stale.

### Fixed — the assessment only answers what the scan evidences
- The insurance assessment asserted "Drift mitigation: Yes" on every scan,
  "Post-deployment monitoring: Yes" on a scan with no agents, and that the
  scan "runs in CI", all labeled *from scan*. The applicant signs this form.
  Drift is now claimed only with a baseline diff or two recorded scans,
  monitoring only when there were agents to observe, and CI never; an
  unevidenced field reads *To be confirmed*.
- The legacy report and `stoa export --underwriting` rendered a fictional
  applicant ("XYZ Financial Technologies") when no identity was configured,
  in every customer's `stoa-report.html`. They now derive a placeholder from
  the scanned repository, as the dashboard already did.
- The indicative coverage trigger no longer mentions "fraud-triage".
- A scan with no agents no longer offers an assessment to print and sign.

### Security
- The dashboard's data is escaped (`<`, `>`, `&`, U+2028, U+2029) and
  embedded in a JSON script tag; every inline script and stylesheet is
  hash-pinned in a CSP with `default-src 'none'` and `connect-src 'none'`.
  A hostile fixture, a zero-network browser test, a redaction test, and a
  determinism test guard this in CI.

### Packaging
- The compiled UI (`stoa/templates/dashboard.html`) is built by the release
  workflow and shipped in the wheel. Users never need Node. A development
  checkout without it gets a warning from `stoa scan` and a clean error
  from `stoa dashboard`.

## 0.7.4 — "Tools are first-class"

Registry schema → 1.7 (additive). An agent's reach is mostly in its tools,
and its tools mostly live in another file; until now the scanner read the
agent's file and stopped. See `examples/meridian-pay/` — one refund agent
built as LangGraph code, Bedrock Terraform, and Databricks Agent Framework.

### Added — tool inventory
- **Definition pass** over every file: `@tool` / `@function_tool` /
  `@mcp.tool` functions, `StructuredTool.from_function`, raw JSON function
  schemas (with the dispatcher that implements them), TS `tool({...})` and
  `server.tool("name", …)`, `UCFunctionToolkit(function_names=[…])`, Bedrock
  action-group `function_schema` names. Each tool records parameters, reach
  (capabilities and integrations from its body, or its Lambda role's reach),
  numeric guards on its parameters, retry wrapping (one hop into same-file
  helpers), and whether an idempotency key is visible.
- **Binding pass** per agent: names passed to `bind_tools`, `ToolNode`,
  `tools=`, `create_react_agent`, TS `tools:`, list variables expanded,
  resolved through the one-hop import graph. MCP servers, JSON-schema lists
  and UC toolkits in the agent's file bind everything they define.
- `tools` array on the agent record (schema 1.7); agent `capabilities` and
  `integrations` include the tools'. The architecture graph and both exports
  inherit the wider reach.
- **Autonomy sees tools.** A bound tool reaching a high-impact sink is a
  model-driven side effect; `tool:<name>` signals; IaC agents take no
  approval or bounding credit from free text. On Meridian Pay the
  account-actions agent reads `unrestricted_autonomous` and **DECL001 fires
  in all three stacks** against its `human_approved` declaration.
- **AI008 — non-idempotent money action under retry** (high). A money or
  write tool wrapped in `tenacity`, `backoff`, `RetryPolicy`, `max_retries`
  or a Lambda retry, with no idempotency key or dedupe check on the path: a
  timeout after the upstream commits posts it again, and each attempt is
  checked against the per-call limit on its own. Crosswalk: OWASP LLM06, EU
  AI Act Art. 9.
- Provider id `databricks` (`ChatDatabricks`, `databricks_langchain`).

### Known limits
Tools registered dynamically, built in loops, or loaded from config stay
unresolved. UC functions and unmatched JSON schemas are name-only
(`resolved: false`): money classification comes from the name. Guards are
recorded, not yet turned into a finding (limits stated in prompts only).

## 0.7.3 — "Design-partner feedback: coverage, noise, control credit"

Three complaints from a first design partner, each pinned by a test in
`tests/test_feedback_fixes.py`. Dimension scores on the shipped examples move
where these change what is observed; the golden snapshot is regenerated.

### Fixed — agentic surface
- **Retry loops are not agent loops.** `for attempt in range(3)`,
  `while retries < MAX`, `for attempt in Retrying(...)` around one model call
  no longer make a provider wrapper an agent candidate. The loop header
  decides; a loop the model steers still counts.
- **Hosted-model and media providers**: `replicate`, `fal`, `elevenlabs`,
  `stability`, `runway` join the provider vocabulary, `replicate.run` /
  `fal_client.run` count as model calls for the loop and multi-step signals,
  and their API hosts are recognized endpoints. A generation pipeline on
  Replicate is no longer invisible.
- **Hand-rolled tool loops are characterized, not just found.** `tools=TOOLS`
  (a name, not a literal) is a tool binding; the model's `tool_calls` /
  `function.arguments` are a taint source, so arguments flowing into a shell
  or SQL sink raise AI002; `spark.sql(...)`, DB-API `.execute(...)` are SQL
  sinks. A loop that runs `subprocess` on model-chosen arguments now reads
  `unrestricted_autonomous` with a critical AI002, as it should.

### Fixed — noise
- **Namespace and identifier URIs are not insecure endpoints.** XMP / RDF /
  Dublin Core / IPTC / license / XML-schema hosts (`ns.adobe.com`,
  `purl.org`, `iptc.org`, `creativecommons.org`, `schema.org`, `*.w3.org`,
  `www.apache.org`, …) are excluded from NET001; media pipelines carry these
  in bulk.

### Fixed — control credit
- **Controls one import hop away are credited to the agent.** An agent
  reached only through a route file that carries authentication, rate
  limiting, validation or logging is covered by them; the new import graph
  (`stoa.imports`) links the agent's file to the files that import it and the
  files it imports (Python module paths, JS/TS relative specifiers). Approval
  and kill-switch remain agent-local. Previously the per-agent assessment
  read the agent's own file only, so "auth on every route" showed as
  *not observed* on every agent behind those routes.
- **Approval must be code, not commentary.** `# needs human approval` and a
  docstring no longer credit the approval control or the `human_approved`
  autonomy level (`code_only()` strips comments and docstrings first).

## 0.7.2 — "Resolved Terraform, and agents built in the Google console"

Two things that make the IaC collector hold up on a real repository. Schema
stays at 1.6 (`platform` gains `dialogflow_cx` and `vertex_ai_agent_builder`;
new evidence ids are not schema fields). See [docs/iac.md](docs/iac.md).

### Added — resolved Terraform
- **Variables, tfvars, locals, interpolation.** `variable` defaults,
  `terraform.tfvars` / `*.auto.tfvars` (now scanned files — a secret in a
  tfvars is found), `locals`, and `${var.x}` / `${local.y}` interpolation
  resolve before detection. `.tfvars` joins the default extension list.
- **`count` / `for_each` expansion** with `toset` / `tolist` / `concat`, and
  `cond ? a : b` once the condition resolves to a boolean. Instances carry
  their key in the symbol (`type.name["key"]`, `type.name[1]`).
- **`data "aws_iam_policy_document"`** statements are read as the policy —
  the most common "reach unresolved" on AWS is gone.
- **Local module calls.** `module "x" { source = "./…" }` instantiates the
  directory with the call's inputs over its defaults; each call is its own
  agent (`module.x.<type>.<name>`, path inside the module, `IAC_MODULE_CALL`
  evidence at the call site). Module directories emit no bare agents.
- **`stoa scan . --tf-plan plan.json`** reads `terraform show -json` output
  (plan or state): values fully resolved, module instances grouped by
  address, resource links restored from the configuration's expression
  references so a role ARN unknown until apply still links. Replaces
  file-based agent discovery when given; `.tf` secrets scanning continues.
  Unreadable plans degrade to a warning.
- Anything still unknown — a variable with no default, a module output read
  by the parent, other functions, remote state — remains an unresolved
  reference, never a guess.

### Added — Google connector (Dialogflow CX / Vertex AI Agent Builder)
- `google_dialogflow_cx_agent` → an agent with `platform: dialogflow_cx`,
  provider `google`, integration `gcp`.
- **Controls**: `google_dialogflow_cx_security_settings` (redaction →
  `validation`, retention recorded, insights export → `observability`);
  Cloud Logging / interaction logging → `observability`; generative safety
  banned phrases → `validation`; the generative model recorded.
- **Tools**: `google_dialogflow_cx_webhook` → `tool_calling`, followed from
  its URI to the Cloud Function / Cloud Run service, its service account,
  and every `google_*_iam_member` / `_binding` naming that account; GCP roles
  map conservatively to capabilities, primitive roles (`roles/editor`) called
  out as broad reach, unknown roles reported as not in the dictionary.
  `google_dialogflow_cx_tool` (OpenAPI / function / data store specs).
- **RAG**: knowledge connectors on flows and pages, Discovery Engine data
  stores and chat engines. A chat engine that creates its own agent is an
  agent (`platform: vertex_ai_agent_builder`); one that links a CX agent is
  attributed to it.
- Marlowe example (`examples/marlowe/`): one local module called twice with
  contrasting inputs plus a chat engine; 18 new tests (suite: 579).

### Known limits
Resolution is module-local; the plan input is the complete answer. GCP IAM
is evaluated by role name only (no conditions, no custom-role expansion);
GUI agent builders without a Terraform provider (Copilot Studio, Agentforce,
ServiceNow) remain invisible. A missing control is still visible but does
not yet raise exposure.

## 0.7.1 — "Agents configured in AWS"

Second platform in the IaC dictionary: **Amazon Bedrock Agents**. Registry
schema stays at 1.6 (`platform` gains the value `"bedrock"`; new evidence ids
are not schema fields). See [docs/iac.md](docs/iac.md).

### Added — Bedrock in the IaC collector
- `aws_bedrockagent_agent` → an agent with `platform: bedrock`, providers
  `bedrock` plus the hosted vendor read from `foundation_model`
  (`anthropic` / `cohere` / `mistral`), integration `aws`.
- **Tools** from `aws_bedrockagent_agent_action_group`: Lambda executors →
  `tool_calling` (function names listed in evidence), `RETURN_CONTROL` noted,
  `AMAZON.CodeInterpreter` → `code_execution`. **RAG** from knowledge-base
  associations → `vector_search`.
- **Controls**: a `guardrail_configuration` → `validation` (the referenced
  `aws_bedrock_guardrail` is named with its policies);
  `aws_bedrock_model_invocation_logging_configuration` → `observability`,
  account-wide.
- **Reach from IAM.** Allow-statement actions on the agent's role and on each
  tool Lambda's role are mapped conservatively to capability ids
  (`dynamodb:*` → `database_write`, `ses:Send*` → `email_send`,
  `sns:Publish` → `messaging`, `s3:Put*` → `filesystem_write`, `*` →
  `cloud_resource_access`, plumbing such as `bedrock:InvokeModel` and
  `iam:PassRole` → nothing). Three policy forms parse: `jsonencode({...})`,
  heredoc / literal JSON, and AWS managed policy ARNs. `Deny` grants nothing;
  a policy that is a reference (`data.aws_iam_policy_document`) is reported
  as unresolved. Wildcard actions and full-access managed policies are called
  out as broad reach in `IAC_IAM_POLICY` evidence.
- **Module scope.** IaC detection now runs over all `.tf` files in a
  directory (Terraform's own unit), so an agent in `agents.tf` is linked to
  its IAM in `iam.tf` and its guardrail in `guardrails.tf`. Cross-file
  evidence says where it came from. This also attributes Databricks grants
  split out of the endpoint's file. Agent ids are unchanged (still built from
  the defining file's path).
- HCL extractor: heredocs, quoted keys (`"Version" = …` / JSON `"Key": …`),
  and comma-separated object literals.
- Kestrel example (`examples/kestrel/`): two Bedrock agents across five `.tf`
  files with no model call in code; 17 new tests (suite: 561).

### Known limits
IAM evaluation is deliberately shallow (no `Condition`, no resource-ARN
narrowing, no effective permissions); roles or policies created outside the
module are unresolved; a missing guardrail is visible but does not yet raise
exposure; autonomy remains uninformative on IaC agents.

## 0.7.0 — "Agents configured in infrastructure"

Registry schema → 1.6 (additive). The IaC collector finds agents that are
*configured*, not coded — Databricks Model Serving endpoints defined in
Terraform — and emits them as ordinary agent candidates. A repository with no
`.tf` files serializes byte-identically to 1.5 apart from `schema_version`.
Static, local, deterministic; no `terraform` binary or provider plugins at
scan time. See [docs/iac.md](docs/iac.md).

### Added — IaC collector
- `.tf` is a scanned language. A zero-dependency HCL block extractor parses
  `resource` blocks (nested/repeated blocks, lists, references); values the
  file cannot resolve (`var.*`) are left unresolved, never guessed.
- `databricks_model_serving` → an agent with `source: iac`,
  `platform: databricks`, `discovery_tier: recognized`, symbol
  `databricks_model_serving.<name>`, high confidence, and evidence at the
  resource block's `file:line`.
- Controls stated by the endpoint's `ai_gateway` (guardrails → `validation`,
  rate limits → `rate_limit`, inference tables / usage tracking →
  `observability`) are credited per endpoint through the existing
  `control_credit` math. Reach is read from `databricks_grants` (`SELECT` →
  `database_read`; `MODIFY`/`ALL_PRIVILEGES` → `database_write`, catalog-wide
  privileges called out); model egress from environment keys.
- The core secret rules run on HCL too — a literal API key in a `.tf` is
  caught and redacted as in code.
- IaC agents participate in declarations, `stoa diff` (a grant widened from
  `SELECT` to `ALL_PRIVILEGES` is high-severity drift), the graph, and the
  assurance and underwriting exports.
- New integration id `databricks`, recognized in code as well. `stoa.toml`
  `[iac] enabled = false` turns discovery off while keeping secret scanning.
- `examples/tidewater`: a fixture with two Databricks-hosted agents planted
  for contrast (one fenced by an AI Gateway with a narrow grant, one with no
  gateway and catalog-wide privileges), driving 15 tests.

### Known limits (documented, not hidden)
Terraform only (no Asset Bundles yet); Databricks only; grants attributed via
the service principal's name stem; a missing control is visible in
`controls_observed` but does not yet raise exposure; autonomy on IaC agents
is uninformative until the endpoint→code join lands.

## 0.6.1 — Detection: hand-rolled / raw-REST agents

A detection-quality fix. Two regexes in the agent scorer had reproducible
gaps that hid agents built without an official SDK. No schema change; scores
and every example's agent count are otherwise unchanged.

### Fixed
- **Raw HTTP model calls now feed the framework-independent signals.** A
  hand-rolled agent that loops on `requests.post(...)` / `httpx` / `fetch`
  against a recognized model endpoint (instead of an SDK method) now trips the
  "model call in a loop" and "multiple call sites" detectors. Gated on
  `DIRECT_MODEL_ENDPOINTS`, so an ordinary POST — or a single raw call — never
  counts (a webhook loop and a lone generation call both stay non-agents).
- **The `tools` signal accepts a quoted JSON key.** A raw REST payload writes
  `"tools": [...]` (a JSON dict key); detection previously required the
  unquoted kwarg `tools=[...]`. Both now count.

## 0.6.0 — "Regulatory crosswalk & the explainable report"

Registry schema → 1.5 (additive); crosswalk `stoa-crosswalk-1`. Everything is
additive and presentation-only: dimension scores, weights, and the proxy cap
are byte-for-byte unchanged (guarded by a pre-change golden snapshot). Zero new
required dependencies; zero telemetry; renders fully offline.

### Added — regulatory crosswalk
- `data/crosswalk.toml` maps every rule to one primary OWASP LLM Top 10 (2025)
  class and one EU AI Act article, plus a plain-English gloss. Versioned and
  overridable via `[crosswalk] path`; honest blanks where no genuine OWASP
  class fits; unmapped rules render explicitly, never dropped.
- Registry gains a per-finding `crosswalk` object, a per-dimension roll-up on
  `dimension_summary`, and a top-level `crosswalk` version block. SARIF results
  and rules gain `owasp:` / `euaiact:` tags alongside the existing `stoa-dim:`.

### Changed — the report is now verdict-first and ≤5 printed pages
- New information architecture: Verdict → Scoreboard → Fix first →
  Contradictions → Agents → Risk dimensions → Standards → Appendix. The old
  12×8 dimension matrix and its duplicated renders are gone; one dimension
  section survives, each row leading with a single canonical gloss.
- An inline explainability layer (a one-line "how to read this", per-section
  captions, `<abbr>` term definitions, an inline severity legend) and an
  executive summary that names the single highest-impact finding.
- Agent names are disambiguated by source file when they collide
  (`payments·agent`), consistently across report, registry, and SARIF.

### Added — underwriting-evidence export (`stoa export --underwriting`)
- Renders a pre-filled AI Model Risk Assessment (modeled on the aiSure™
  template) as an offline HTML view with print-to-PDF. Technical fields are
  sourced from scan evidence; identity and real model-performance figures come
  from an applicant TOML (`--underwriting-config`), falling back to a clearly
  labeled sample. Also reachable from a "Generate underwriting evidence" button
  in the report. See `examples/underwriting-config.example.toml`.

### Added — report presentation config
- `data/report.toml` (overridable at `.stoa/report.toml`): fix-first cap,
  agent-collapse tier, contradiction grouping threshold, proxy-merge.

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

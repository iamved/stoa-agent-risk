# Stoa Dashboard, Phase 1: plan

Status: **awaiting approval**. No code under `ui/` or `src/stoa/` changes until
this plan is approved. Everything in section 1 is verified against the source
tree at 0.7.4 (registry schema 1.7).

---

## 1. What the code actually does today

### Outputs and schemas

| Artifact | Produced by | Identifier | Notes |
|---|---|---|---|
| `stoa-registry.json` | `report_json.build_document` | `schema_version: "1.7"` (bare string, additive-minor policy in `SCHEMA.md`) | No timestamps. Byte-identical for the same tree and config. |
| `stoa-report.html` | `report_html.render_html` | none | Self-contained. CSP `default-src 'none'` with every inline script SHA-256 hash-pinned. No `'unsafe-inline'`. Prints to about five pages. |
| diff document | `registry_diff.diff_registries` | `schema: "stoa-diff/1.0"` | Deterministic. Rename matching by evidence-fingerprint Jaccard. Approvals from `.stoa/approvals.toml`. |
| assurance packet | `assurance.build_packet` | `assurance-packet/1.2` | 18 areas, rows tagged scanned / declared / ingested / not_provided. |
| underwriting HTML | `underwriting.render_underwriting_html` | none | Munich Re style questionnaire, print button, offline. |
| SARIF | `sarif.write_sarif` | 2.1.0 | with `stoa-dim:*` tags. |

### Configuration files (all TOML, no YAML anywhere)

| File | Purpose |
|---|---|
| `stoa.toml` | scanner config; precedence CLI > file > defaults (`config.py`) |
| `stoa-declared.toml` | declared facts: per-agent `owner`, `purpose`, `autonomy_intent`, `economic_authority`; `[governance]`; `[[evidence]]` (`declarations.py`) |
| `.stoa/approvals.toml` | intentional drift approvals bound to an evidence fingerprint (`approvals.py`) |
| `.stoa/report.toml` | report collapse thresholds (`data/report.toml`) |
| `.stoa/crosswalk.toml` | optional crosswalk override |

`src/stoa/templates/stoa.yml` is the GitHub workflow template written by `stoa init github`, not a config file.

### CLI (`cli.py`, argparse)

`scan`, `init`, `diff`, `graph`, `export` (`--assurance`, `--underwriting`), `approve`, `runtime` (`analyze`, `map`, `merge`, `baseline`, `drift`). `scan` already has `--diff-against GIT_REF`, `--diff-json`, `--diff-md`, `--fail-on-drift`, `--approvals`, `--with-runtime`, `--sarif`, `--no-graph`. Commands that consume a registry file (`graph`, `export`, `diff`) take its path positionally.

### Dimensions

`data/dimensions.toml` (`stoa-aiuc-8` v2.0) defines eight dimensions with `assessability` = strong | partial | proxy and `group` = A | B | C | D. Per-agent `dimension_assessment.dimensions[]` entries carry `id, group, assessability, exposure, score, contributing_findings, contributing_capabilities, controls_observed, statement`. `dimension_summary.dimensions[]` carries `max_exposure, agents_elevated, agents_moderate` plus a `crosswalk` roll-up. Scoring is `min(100, Σ finding_weight + Σ capability_weight − Σ control_credit)`, floor 0, bucketed, then proxy-capped at `moderate`. Golden snapshot: `tests/fixtures/dimension_scores_golden.json`.

### Crosswalk

`data/crosswalk.toml` (`stoa-crosswalk-1` v1.0). Each rule: one `owasp_llm_2025` (may be blank), one `eu_ai_act` article, `relation` (exposure | control-observed), and a plain-English `so_what`. Stamped onto every finding as `finding.crosswalk`. NIST AI RMF rolls up once at report level (`report_html._nist_rollup`). A banned-words test enforces vocabulary.

### Graph

`graph_model.build_graph(registry)` produces nodes and edges; `report_graph.render_graph_section` inlines a vendored `templates/cytoscape.min.js` (435 KB) plus a byte-fixed glue script, both hash-pinned in the CSP. Graph data sits in a `<script type="application/json" id="stoa-graph-data">` tag, escaped by `report_graph._escape_json_for_script`. `graph_mermaid.py` renders the same model as Mermaid for `stoa graph`.

### Redaction

`redaction.py` redacts at match time inside `risk_detection.py` and `flow.py`. Snippets in the registry are already `prefix…[REDACTED:sha256-…]`. `tests/test_redaction.py` enforces that no raw secret reaches any output surface.

### Packaging and CI

setuptools, `package-data = templates/*, data/*`. `ci.yml` runs pytest on Python 3.10 and 3.12. `release.yml` runs `python -m build` on a published release and publishes via Trusted Publishing. No Node anywhere today. Local machine has Node 26.

### Tests that constrain this work

- `test_report_ia.py::test_report_byte_identical_across_runs` (determinism)
- `test_report_budget.py` (five printed pages, collapse-not-omit)
- `test_html_escape.py`, `test_report_graph.py` (CSP and escaping)
- `test_redaction.py` (no raw secret on any surface)
- `test_dimensions_phase4.py` with the golden snapshot (scores never move)
- `test_crosswalk.py` banned-words test

---

## 2. Data contract

### 2.1 The dashboard payload is an envelope, not a new registry schema

The registry stays schema 1.7 (plus the two additive fields in 2.3). The dashboard embeds a versioned envelope that wraps documents the scanner already produces:

```json
{
  "schema": "stoa-dashboard/1.0",
  "registry": { "...": "stoa-registry.json, unchanged" },
  "diff": { "...": "stoa-diff/1.0, or null when no baseline" },
  "assurance": { "...": "assurance-packet/1.2" },
  "underwriting": { "...": "output of underwriting._derive_from_registry" },
  "history": [ { "...": "summaries, see 2.4" } ],
  "register": [ { "...": "merged register rows, see 2.5" } ],
  "rules": { "AI002": { "title": "...", "description": "...", "remediation": "..." } }
}
```

Why: the prompt's `drift`, `confidence`, and evidence data all already exist as separate documents. Wrapping them keeps every existing consumer, test, and golden untouched, and lets the UI say "scanner is the source of truth" literally. `rules` is the static `RULES` table so the findings drawer can show What / Why / Fix without shipping `docs/rules/*.md`.

### 2.2 Registry fields the UI consumes

`schema_version`, `tool.version`, `repository.{name, git_ref, base_ref}`, `summary.*`, `agents[].{id, name, display_name, symbol, path, language, confidence, detection_score, evidence[], providers, frameworks, integrations, capabilities, permission_tags, call_sites, last_touched_by, last_commit, codeowners, findings[], highest_severity, dimension_assessment, declared, autonomy_level, tools[], source, discovery_tier, platform}`, `repository_findings[]`, each finding's `{fingerprint, rule_id, title, category, severity, confidence, path, line, column, snippet, remediation, suppressed, suppression_reason, is_new, canonical_name, flow[], gate_eligible, dimensions, variant, evidence_tags, message, declared_ref, crosswalk}`, `dimension_summary`, `business`, `governance`, `evidence`, `crosswalk`, `warnings`, `degraded_files`, `skipped_files`.

### 2.3 Additive registry changes (schema 1.7 → 1.8)

1. `repository.head_commit = {hash, date}` when git metadata is available. `date` is the commit's own ISO date from `git log -1 --format=%cI`, which is deterministic per commit. This is the dashboard's "scan timestamp". **No wall-clock `generated_at` anywhere**, in keeping with the determinism invariant.
2. `dimension_assessment.dimensions[].score_before_controls`: the same integer `score` computed without the control-credit subtraction. `score` and `exposure` are unchanged. This is what lets the register show inherent (bucket of `score_before_controls`) and residual (existing `exposure`) without inventing a formula. The golden snapshot test compares the existing fields; the plan for M1 is to confirm it does not compare whole dicts, and extend it if it does.

Both are emitted only when applicable, so code-only scans without git stay byte-identical to 1.7 apart from `schema_version`.

### 2.4 History

`stoa scan` appends a **summary**, not a full registry, to `.stoa/history/<commit-hash>.json` (schema `stoa-history-entry/1.0`): `git_ref`, `head_commit`, `scanner_version`, `agent_candidates`, `findings` counts, and `dimension_summary`. Keyed by commit hash so rescanning the same commit overwrites rather than duplicates. Retention `history_keep = 10` in `stoa.toml [dashboard]`. Disabled with `--no-history` or when not in a git repo. History drives Overview sparklines only. It is **not** used for the drift screen, because comparing registries produced by different scanner versions is exactly the rule-version skew the diff docs warn about.

### 2.5 Drift

The `diff` slot is filled from one of:
- `stoa scan --diff-against REF`, which rescans REF with the current scanner (preferred, no skew);
- `stoa dashboard REGISTRY --baseline OTHER_REGISTRY`, for the CI pattern where the main branch's registry is downloaded as an artifact.

The UI groups the existing diff fields: capability added (high_impact flag), integration added (sensitive flag), provider added, capability or integration removed, new and resolved findings, dimension deltas, confidence change, renamed agents, approvals applied and stale. "Authority increased" is defined as: high-impact capability added, sensitive integration added, or a dimension delta with direction `increased`. The UI adds no new severity logic; it sorts by the diff's `drift_severity`.

### 2.6 Risk register

Rows are derived per (dimension, agent) where the agent's exposure for that dimension is `moderate` or `elevated`, with `risk_id = <dimension-id>/<agent-id>`. Inherent = bucket of `score_before_controls`, residual = `exposure`, linked controls = `controls_observed`, linked findings = `contributing_findings`.

Declared state lives in `stoa-declared.toml`, not a new YAML file:

```toml
[[risk_register]]
risk_id   = "unreviewed-high-impact-action/agents/refund.py:RefundAgent"
owner     = "jane.doe@example.com"
treatment = "mitigate"        # accept | mitigate | avoid | transfer
rationale = "Dual approval being added in Q4"
review_by = "2026-12-01"
```

Parsed by `declarations.py` alongside the existing blocks; unknown `risk_id`s produce a warning the same way unknown agent ids do. Edits in the UI produce a TOML snippet with a Copy button.

### 2.7 Schema check

At startup the UI checks `envelope.schema` major = 1 and `registry.schema_version` major = 1. Anything else renders a friendly error screen with the versions found and the scanner version to install.

---

## 3. Directory layout

```
ui/                              Vite + React 19 + TypeScript strict + Tailwind
  package.json, pnpm-lock.yaml   pinned; Node version in .nvmrc
  src/
    data/types.ts                hand-written types for the envelope and registry
    data/provider.ts             DataProvider interface
    data/embedded.ts             EmbeddedProvider (reads #stoa-data, the only place)
    data/selectors.ts            pure functions: filters, groupings, register rows
    app/router.ts                hash routing
    screens/{overview,inventory,findings,drift,register,evidence}/
    components/                  shell, tables, drawers, badges, matrix
    graph/                       thin wrapper around the vendored cytoscape glue
  fixtures/
    meridian-pay.envelope.json   generated from examples/meridian-pay (see 5)
    meridian-pay.baseline.json
    hostile.envelope.json
    large.envelope.json          generated, 5,000 findings
  tests/                         Vitest (provider, selectors, filters)
  e2e/                           Playwright (file://, routes, zero-network, print)
src/stoa/dashboard/
  __init__.py
  envelope.py                    build_envelope(registry, diff, history, declarations)
  inject.py                      safe JSON escaping + single exact placeholder replace
  history.py                     .stoa/history read/write/prune
  template.py                    locate templates/dashboard.html, clear error if absent
src/stoa/templates/dashboard.html   BUILD OUTPUT, gitignored, produced by CI
tests/test_dashboard_*.py
docs/dashboard.md                user docs, CI pattern
```

---

## 4. Build and packaging

**Decision: build the template in CI from a pinned lockfile; never commit the artifact.**

- A minified megabyte in git is unreviewable, and for a security tool that is a supply-chain smell.
- `release.yml` gains a Node step (`pnpm install --frozen-lockfile && pnpm build`) before `python -m build`. The artifact lands at `src/stoa/templates/dashboard.html`, which the existing `package-data` glob already ships.
- `ci.yml` gains a job: build UI, build wheel, install the wheel in a fresh venv **without Node on PATH**, run `stoa dashboard` on the fixture, run the Playwright smoke test against the output.
- A test asserts the built wheel contains `stoa/templates/dashboard.html`.
- Developer path: `make ui` or `pnpm --dir ui build`. `stoa dashboard` and `stoa scan` print one clear line if the template is missing and continue (scan still writes the registry and report; the dashboard is skipped with a warning, never a failed scan).
- Reproducibility: `.nvmrc`, frozen lockfile, and a CI check that two consecutive builds produce identical bytes.

Reuse rather than duplicate: the UI imports Cytoscape from `src/stoa/templates/cytoscape.min.js` via a Vite alias so there is one vendored copy, and the graph tab reuses the layout and style logic from `report_graph._GLUE_JS` ported to a module.

---

## 5. Fixtures

The prompt asks for a fictional fintech with a refund agent. `examples/meridian-pay` already **is** that: a payments app with code, Databricks, and AWS agents, a `stoa-declared.toml`, and it is the public demo scan. Fixtures will be generated from it by a script (`ui/fixtures/build.py`) so they only ever contain data the scanner can produce. The baseline fixture is the same example with the refund tool's payment capability and an integration removed, so the drift story is "payment authority appeared". A declared `economic_authority` change supplies the "limit changed" narrative honestly, as a declared fact. The hostile fixture injects `</script><script>alert(1)</script>`, `<!--`, U+2028 and U+2029 into snippets and names. The large fixture is synthesized to 5,000 findings.

---

## 6. CLI surface

- `stoa scan`: additionally writes `stoa-dashboard.html` by default. New flags `--dashboard PATH`, `--no-dashboard`, `--open`, `--no-history`. When `--diff-against` is given, the diff is embedded.
- `stoa dashboard REGISTRY [--baseline REGISTRY] [--declarations PATH] [--out PATH] [--open]`. Follows the `graph` and `export` convention of taking the registry path positionally.
- Existing `--html` report keeps working. Its help text gains "(legacy summary report)". Nothing is removed.

---

## 7. Security

1. **Escaping.** `inject.py` serializes with `ensure_ascii=False` then replaces `<`, `>`, `&`, U+2028, U+2029 with `<`, `>`, `&`, ` `, ` `, and `str.replace`s exactly one placeholder token, asserting it occurs exactly once. No regex touches user-derived content. Test with the hostile fixture: count of `<script` tags in output equals the template's count, and Playwright confirms the payload renders as text.
2. **CSP stays hash-pinned.** `default-src 'none'; script-src 'sha256-<bundle>'; style-src 'sha256-<css>'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'`. The bundle and stylesheet are fixed at build time, so their hashes are computed once and written into the template. The data tag is `application/json` and never executes. This is stricter than the prompt's "allow inline script" and matches the existing report. If React or Radix needs inline `style=""` attributes, `style-src-attr 'unsafe-inline'` is the fallback, and only that; script-src never widens. Verified in M2.
3. **Redaction.** Snippets are already redacted upstream. `inject.py` runs `redaction.redact_line` over every string in the envelope as defense in depth and a test proves a planted key never appears in the output.
4. **No HTML from data.** ESLint bans `dangerouslySetInnerHTML` and `innerHTML`. All report strings render as text nodes.
5. **Zero network.** Playwright opens the file via `file://`, visits every route, and fails on any request.
6. **Determinism.** Same envelope produces byte-identical HTML; a test asserts it.

---

## 8. Conflicts between the prompt and the code, and how they are resolved

| Prompt says | Code says | Resolution |
|---|---|---|
| schema `stoa-risk-report/1.x` | bare `schema_version: "1.7"` in `stoa-registry.json` | use the registry; add a separate envelope schema |
| `stoa.yaml` with `risk_register` | all config is TOML; declared facts live in `stoa-declared.toml` | `[[risk_register]]` in `stoa-declared.toml`; no YAML, no new dependency |
| add `confidence` per dimension | `assessability` already exists with the same values and mapping | consume as is; label it "confidence" in the UI |
| `meta.generated_at` | no timestamps, byte-identical output, golden tests | `repository.head_commit.date` (commit date); no wall clock |
| `drift` as a new structure | `stoa-diff/1.0` exists with severities, renames, approvals | embed the diff document; UI groups its fields |
| history as baseline for drift | diff docs warn about scanner-version skew; `--diff-against` rescans | history for sparklines only; drift from same-version diff or explicit `--baseline` |
| "today the output is a one-pager" | verdict-first report with graph, fix-first, contradictions, standards strip, NIST roll-up, download, underwriting link | dashboard reuses these; legacy report kept |
| Evidence underwriter view to be built | `stoa export --underwriting` and `--assurance` exist | embed their derived data in the envelope; UI renders, never re-derives |
| Python side redacts before embedding | redaction already at match time | keep as defense in depth |
| nine inventory categories | scanner inventories agents, tools, providers, integrations, capabilities, IaC agents, declarations | rail shows only categories with data: Agents (code), Agents (infrastructure), Tools, Providers and models, Integrations, Declarations |
| refund limit and duplicate-refund bypass in fixture | numeric limits are declared, not scanned; AI008 covers idempotency gaps on money tools | fixture uses declared `economic_authority` for the limit and a real AI008 finding for the bypass |
| CSP allows inline script | report pins every script by hash | hash-pinned bundle |
| template under 1.5 MB | Cytoscape alone is 435 KB | budget kept; system font stacks plus one inlined serif face for titles (about 40 KB); measured size reported per milestone |
| `stoa.yaml` parsing tests | none exist | replaced by `stoa-declared.toml` register parsing tests |
| no em dashes in docs or comments | the existing tree uses them throughout | rule applies to new files only |
| "do not describe Stoa as local" | README leads with local-first | UI copy says "Generated by Stoa" and "offline"; positioning docs untouched |

---

## 9. Milestones

Each ends with tests green, the fixture dashboard regenerated, a size figure, and one commit.

- **M1 Data contract.** Schema 1.8 additive fields; `envelope.py`; history entry schema; `[[risk_register]]` parsing; fixtures generated from meridian-pay plus baseline, hostile, large; TypeScript types; `DataProvider` + `EmbeddedProvider`; schema check. Golden snapshot verified.
- **M2 Pipeline.** `ui/` scaffold, single-file build with hash-pinned CSP, `inject.py`, `history.py`, `stoa dashboard`, `stoa scan --open/--no-dashboard`, wheel packaging, CI job without Node. Exit: `stoa dashboard ui/fixtures/meridian-pay.envelope.json --open` shows the shell with placeholder screens.
- **M3 Shell and Overview.** Matrix by group, decomposable headline, stat cards, framework selector, coverage strip, top five so-what sentences from `crosswalk.so_what`, sparklines when history has more than one entry.
- **M4 Inventory and Findings.** Rail, tables, drawers, graph tab, URL-persisted filters, virtualization.
- **M5 Drift.** Groupings over the diff document, authority-increase priority, approvals shown, empty state.
- **M6 Register.** Derived rows, declared merge, TOML snippet with Copy, transfer → Evidence.
- **M7 Evidence.** Risk-officer and underwriter views from the embedded assurance and underwriting data, two print stylesheets.
- **M8 Hardening.** Hostile, zero-network, determinism, 5,000-finding performance, accessibility pass, `docs/dashboard.md` with the CI baseline pattern, README section, CHANGELOG, this file updated to what was built.

If scope needs trimming, M5 history sparklines and M6 are the cleanest to defer to Phase 2 without touching the envelope shape.

---

## 10. Decisions needed before M1

1. Register in `stoa-declared.toml` (recommended) versus a separate `.stoa/register.toml`.
2. CI-built template (recommended) versus committed artifact.
3. Keep the 1.5 MB budget with system font stacks (recommended) versus fully inlined fonts at roughly 2 MB.
4. `stoa dashboard` as a new subcommand (recommended, mirrors `graph`) versus `stoa export --dashboard`.

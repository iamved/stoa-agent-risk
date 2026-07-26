# Feature coverage

What `examples/sparkwing` actually exercises, verified by running `stoa scan`
against it (not asserted from docstrings) — mirrors
[`meridian-ops/COVERAGE.md`](../meridian-ops/COVERAGE.md)'s format at a
smaller scale.

## Detection
- **Frameworks** — LangChain (`portfolio_certifier`, `project_sandbox`,
  `progress_notifier`), LangGraph + LangChain-Anthropic (`mentor_matcher`),
  framework-free raw agentic loop (`sector_advisor`).
- **Capabilities** — `database_write`, `email_send`, `external_http`,
  `shell_execution`, `tool_calling`.
- 8 files scanned → 8 agent candidates, all high confidence, 0 skipped,
  0 degraded (every file parses cleanly under the AST layer).

## Core + AI rules
SEC001 (credential, `tests/test_portfolio.py` — placeholder, low confidence,
never gates), SEC003 (superseded by AI002/sql, confirmed absent from output),
REL001 (swallowed exception, `progress_notifier`), NET002 (missing timeout,
`progress_notifier`).

AI001 (`sector_advisor` — untrusted student chat → prompt), **AI002** both
`sql` (`portfolio_certifier`) and `exec` (`project_sandbox`, gate-eligible),
AI003 (unobserved approval, fires on every tool-bound agent except the golden
baseline), AI005 all three variants exercised except `insecure-endpoint`
(floating-alias on every `gpt-4o` call site), AI006 (`progress_notifier` —
PII → unapproved egress), AI007 (no sampling bound, correlates with
`database_write`/`email_send`/`shell_execution`), CTRL006 (`project_sandbox`
— exec sink with no sandbox construct).

## Assurance layer (the differentiator)
- **DECL001** — `portfolio_certifier` declared `human_approved`, scanner
  infers `unrestricted_autonomous`; fires on both the `agent` and `executor`
  symbols with correct `declared_ref` keys into `stoa-declared.toml`.
- **DECL006** — `project_sandbox` is scanned but has no declaration entry at
  all (left out on purpose); fires on both symbols.
- `stoa export --assurance` (both `--format md` and `--format json`) — the
  Contradictions section surfaces all 4 DECL findings with both evidence
  links; the 14-area packet renders with no crash.
- **Zero declaration warnings** — every `stoa-declared.toml` key validates
  (no unknown agent ids, no invalid enum values).

## Dimensions
All 8 populate with non-zero, non-"not-assessable" evidence:
scope-violation and unauthorized-action reach **elevated** (via DECL001/006);
data-exfiltration, output-integrity, adversarial-manipulation reach
**moderate**; behavioral-instability and model-drift correctly stay **low**
(proxy dimensions, capped below elevated by design); operational-control
stays **low** (its evidence is inherently low-severity review prompts).

## False positives (precision proof)
- `lib/content_search.py` — embeddings-only OpenAI call → **not** flagged as
  an agent.
- `lib/session_client.py` — a `UserAgentParser` class → **not** flagged
  despite the generic `*Agent`-adjacent name.
- `progress_notifier.py`'s SendGrid path (`sg.send(...)`) → not a recognized
  egress sink, so it stays quiet while the actual analytics-vendor call gets
  flagged (AI006).

## CLI surface stress-tested against this fixture
`--sarif` (valid SARIF 2.1.0, machine-parsed back), `--github-annotations`,
`--summary-file`, `--no-ast` (taint rules and CTRL006 correctly disappear;
DECL001 correctly disappears too since autonomy can't be inferred without
AI002 — DECL006 correctly still fires), `--no-dimensions`, `--strict` (exits
1), `stoa init github` (valid workflow, respects an existing `stoa.toml`).

**`stoa diff` + `stoa approve`**, in a throwaway git copy: escalated
`project_sandbox` with a new `cloud_resource_access` capability and an `aws`
integration as a head commit → `stoa diff --base-ref` detected both and
failed the gate unapproved → `stoa approve` (capability, then integration) →
re-ran the diff → gate passes. Full loop, no special-casing needed for this
fixture.

## Redaction
The placeholder key in `tests/test_portfolio.py` never appears raw in
`sample-output/` — only `REDACTED:<fingerprint>` does, in both the HTML
report and the JSON registry.

## Reproducing `sample-output/`
```bash
cd examples/sparkwing
stoa scan . --no-git --html sample-output/report.html --json sample-output/registry.json
```
Re-running this is deterministic: `summary` and `dimension_summary` are
byte-identical to what's committed (git ref and timestamp aside).

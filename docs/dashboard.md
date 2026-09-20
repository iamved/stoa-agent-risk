# The dashboard

`stoa scan` writes `stoa-dashboard.html` next to the registry: one
self-contained file, seven screens in two groups, no server, no network. Open it from disk,
email it, attach it to a ticket. It works over `file://` because everything
it needs (code, styles, fonts, and the scan data) is inside the file.

```bash
stoa scan .                 # writes stoa-dashboard.html, stoa-report.html, stoa-registry.json
stoa scan . --open          # and opens the dashboard in your browser
stoa scan . --no-dashboard  # skip it
```

The legacy summary report (`stoa-report.html`) keeps working and prints to
about five pages. The dashboard is for exploring: filtering findings,
drilling into an agent, reviewing drift, maintaining the risk register.

| Group | Screen | What it shows |
|---|---|---|
| AI estate | Overview | the eight-dimension matrix by category, stat cards, the five findings to read first, framework classes, trends |
| AI estate | Agent Inventory | agents in code and infrastructure, tools, providers, integrations, the architecture graph |
| AI estate | Declared Scope | `stoa-declared.toml` next to what the scan inferred, with contradictions |
| Risk model | Risk Dashboard | three tabs: Findings (filters in the URL, virtualized table, What / Why / Fix drawer), Drift, Risk register |
| Risk model | Controls & Safeguards | controls observed per agent, tool guards, control gaps by rule |
| Risk model | Estimated Financial Loss | the AI loss outlook for a scanned agent (bad-year and average-year loss, exceedance curve, suggested limit and retention, gaps against current policies, comparable public events, what-if levers), plus the declared limits the scan checks |
| Risk model | AI Risk Insurance | the pre-filled AI Model Risk Assessment as it would be submitted (every field tagged from scan, declared, applicant, to confirm, or indicative), the schedule, the steps to submission, and the evidence pack behind it |

## The loss outlook

Estimated Financial Loss runs a seeded Monte Carlo over 50 public AI loss
events (hallucinations, prompt injection, data leakage, IP, performance
failure, bias, erroneous transactions, data loss). Frequency per category
comes from the agent's dimension scores, autonomy and observed approval
controls; severity comes from comparable events scaled to the company's
revenue and blended with a prior by credibility. It reports the expected
annual loss, 1-in-20 / 100 / 250 year losses, an exceedance curve, a
suggested limit and retention, per-category gaps against current policies,
the closest past cases, and the levers that would lower the figure.

The agent's inputs come from the scan (money-moving tools and the declared
per-action limit, data classes, write capabilities, inferred autonomy,
approval controls, dimension scores); the page lists exactly which scan fact
set each input. Business context comes from an `[intake]` block in
`.stoa/underwriting.toml`:

```toml
[intake]
revenue               = 40000000
sector                = "fintech"          # fintech | healthtech | edtech | software | retail | legal
jurisdictions         = ["AU", "US"]
records               = 1500000            # personal records held
regulated             = true
minors                = false
monthly_action_volume = 200000

[[intake.existing_coverage]]
type         = "cyber"                     # cyber | tech_eo | crime
limit        = 5000000
ai_exclusion = true
```

Without it the page says so and runs on placeholder context, with the
snippet to save. Everything can be adjusted on the page; edits stay in
memory. The model is seeded, so the same inputs always give the same
figures, and its dataset, assumptions version and parameters are shown on
the page. It is an indication for discussion with a licensed broker and
carrier: not a quote, not a premium, not advice. When business context is
declared, the assessment schedule on AI Risk Insurance takes the suggested
limit and retention as indicative terms.

The declared limits table stays below the outlook: those figures were
written by a person, and Stoa checks whether the code enforces them.

## The assessment

AI Risk Insurance renders the same pre-filled AI Model Risk Assessment that
`stoa export --underwriting` produces, from the same facts. Technical
answers (robustness evidence, inventory, critical findings, monitoring,
drift) come from the scan. Identity, model-performance figures, and the
policy schedule come from an applicant config, read from
`.stoa/underwriting.toml` when present or from `--underwriting-config PATH`
on `stoa scan` and `stoa dashboard`:

```toml
[identity]
company       = "Acme Payments Inc"
contact_name  = "Dana Okafor"
contact_title = "Head of ML Risk"
model_name    = "Acme Transaction-Risk Agent"

[[performance]]
metric  = "Ground-truth accuracy"
value   = "98.1%"
cadence = "Monthly, held-out labeled set"

[schedule]                      # optional: terms agreed with the carrier
carrier                = "Munich Re"
product                = "aiSure"
policy_limit           = "US$ 25,000,000"
aggregate_deductible   = "US$ 100,000"
```

Without a `[schedule]`, the schedule shows indicative terms sized off
exposure and says so; without `[[performance]]`, sample figures are shown
and marked to confirm. Without any config the placeholder identity is
derived from the repository name and every contact field reads "To be
confirmed". The page never states that coverage exists.

**Edit assessment** on the page makes identity, performance figures, and
schedule terms editable in place; the printed form uses the edited values,
and a config snippet appears to save as `.stoa/underwriting.toml`. Answers
that come from scan evidence (robustness findings, inventory, critical
findings, monitoring, drift) stay read-only: they change when the code
changes.

## From an existing registry

```bash
stoa dashboard stoa-registry.json                        # no drift screen
stoa dashboard stoa-registry.json --baseline main.json   # drift against a saved registry
stoa dashboard stoa-registry.json --out review.html --open
```

`--baseline` takes a registry produced by the **same Stoa version**; drift
between scanner versions is rule drift, not code drift, and `stoa diff`
refuses taxonomy mismatches for the same reason. Inside a repository,
`stoa scan --diff-against origin/main` is the preferred route: it rescans the
base ref with the current scanner and embeds that diff.

## What is inside the file

A `stoa-dashboard/1.0` envelope in a `<script type="application/json">` tag:

| Slot | Source |
|---|---|
| `registry` | `stoa-registry.json`, unchanged (schema 1.8) |
| `diff` | `stoa-diff/1.0` from `--diff-against` or `--baseline`, else `null` |
| `history` | summaries from `.stoa/history/` (trend sparklines) |
| `register` | risk-register rows derived from dimension scores, merged with `[[risk_register]]` in `stoa-declared.toml` |
| `assurance` | the assurance packet (`stoa export --assurance`) |
| `underwriting` | the underwriting derivation (`stoa export --underwriting`) |
| `rules`, `taxonomy`, `frameworks` | static labels: rule metadata, crosswalk tags, dimension names, NIST roll-up |

The UI is a view layer. It never recomputes, reweights, or alters a score,
and the framework selector only changes labels. What you see is what the
scanner wrote.

## History and trends

Each scan inside a git repository records a small summary under
`.stoa/history/<commit>.json` (agent count, finding counts, per-dimension
exposure, the commit date). The dashboard shows a sparkline per dimension
once more than one entry exists. Entries are keyed by commit, so rescanning
the same commit overwrites rather than duplicates. Configure retention in
`stoa.toml`:

```toml
[dashboard]
enabled = true        # false: never write the dashboard
history_keep = 10     # entries kept under .stoa/history/
```

`--no-history` skips recording for one run. History is never used for the
drift screen; it is summaries, not registries.

## Risk register

Rows are derived per agent and dimension wherever the scanner scored
exposure at `moderate` or above. **Inherent** is the score before observed
controls are credited; **residual** is the scanner's own exposure level. Both
come straight from the registry. Treatment, owner, rationale, and review
date are declared in `stoa-declared.toml`, reviewed like code:

```toml
[[risk_register]]
risk_id   = "unreviewed-high-impact-action/b8f0111742fc"   # <dimension-id>/<agent-id>
owner     = "digital-servicing@example.com"
treatment = "mitigate"        # accept | mitigate | avoid | transfer
rationale = "Dual approval being added in Q4"
review_by = "2026-12-01"
status    = "in_progress"     # open | in_progress | closed
```

The dashboard cannot write to your repository. Editing a row in the UI
produces the TOML snippet to paste, with a Copy button. A declared row whose
`risk_id` matches nothing in the current scan is shown as unmatched rather
than dropped.

## Security properties

- **No network.** `default-src 'none'` and `connect-src 'none'` in a
  Content-Security-Policy meta tag; the browser tests fail on any request.
- **Hash-pinned scripts.** Every inline script and stylesheet is fixed at
  build time and allowed by SHA-256 hash. There is no `'unsafe-inline'` for
  scripts, the same policy as the legacy report.
- **Inert data.** The envelope is escaped (`<`, `>`, `&`, U+2028, U+2029) so
  a scanned snippet can never close the data tag; a hostile fixture with
  `</script><script>alert(1)</script>` in every field class is part of the
  test suite. No string from the scan is ever rendered as HTML.
- **Redacted twice.** Snippets are redacted by the scanner at match time and
  every string is passed through the redactor again before embedding.
- **Deterministic.** Same registry, same file, byte for byte.

## CI pattern

Upload the dashboard as a build artifact and pass the main branch's registry
as the baseline so pull requests get a drift screen:

```yaml
- name: Download the main-branch registry
  uses: dawidd6/action-download-artifact@v6
  with:
    workflow: stoa.yml
    branch: main
    name: stoa-registry
    path: baseline
  continue-on-error: true

- run: stoa scan . --diff-against origin/main --dashboard stoa-dashboard.html

- uses: actions/upload-artifact@v4
  with:
    name: stoa-dashboard
    path: stoa-dashboard.html
```

With a full-history checkout, `--diff-against origin/main` alone is enough
and rescans the base with the same scanner; the downloaded registry is the
fallback for shallow clones (`stoa dashboard stoa-registry.json --baseline
baseline/stoa-registry.json`).

## Developing the UI

The UI lives in `ui/` (Vite, React, TypeScript). The compiled template is not
committed; the release workflow builds it and packs it into the wheel. In a
checkout:

```bash
scripts/build_dashboard.sh          # needs Node (ui/.nvmrc) and pnpm
stoa dashboard ui/fixtures/meridian-pay.envelope.json --open
```

`ui/fixtures/build.py` regenerates the fixtures from `examples/meridian-pay`;
a test fails when they are stale. `pnpm --dir ui test` runs the unit tests,
`STOA_BIN=.venv/bin/stoa pnpm --dir ui test:e2e` the browser tests over
`file://`.

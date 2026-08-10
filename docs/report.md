# The report

`stoa scan` writes a self-contained `stoa-report.html` — no network, no
accounts, opens offline. It is **verdict-first**: the answer to "how bad is
it, and what do I fix" is at the top; the exhaustive detail is one collapse
away.

## Information architecture

The report reads top to bottom as a decision, not a database:

| Section | The question it answers |
|---|---|
| **Verdict** | one generated sentence — agent count, how many at the worst tier, and the theme of the risk |
| **Scoreboard** | how much risk, and where it sits — agents by exposure tier + a one-line findings ribbon |
| **Fix first** | what to repair, in order — the shortest path that clears every critical finding |
| **Contradictions** | where declarations don't match the code — what a self-attested questionnaire can't catch |
| **Agents** | which agents carry the risk — the severe tier up front, the rest one click down |
| **Risk dimensions** | what kinds of risk, and which rules they map to |
| **Standards** | which OWASP LLM classes were assessed — gaps kept visible |
| **Appendix** | full agent detail, every finding, NIST alignment, and the architecture graph — collapsed |

Every number reconciles, and nothing is deleted — only demoted. The full
finding list, the per-agent breakdowns, and the graph all live in the
Appendix; the body leads with the verdict and the fixes.

## Built to be read by a first-timer

An inline explainability layer decodes Stoa's vocabulary in place, without a
glossary section:

- a one-line **"how to read this"** under the verdict (*exposure = what the
  code makes possible, not what has happened*);
- a short caption under every section header naming the question it answers;
- hover definitions on the terms that carry weight — *proxy-tier*, *static
  exposure*, *gate-eligible*, the exposure levels, *suppressed*;
- each risk dimension leads with its plain-English gloss, then its rule IDs
  and [framework tags](/docs/crosswalk).

## Fix first, in four lines

Each remediation item is exactly: a title, a one-line impact, the fix, and a
`rule · file:line · OWASP · Article` reference. Findings that share a rule and
a fix are merged into one item; a critical contradiction points down to the
Contradictions section rather than repeating its detail. Flow analysis and
methodology caveats sit behind a **Why this fired** expander.

## Properties

- **Offline & self-contained** — fonts and scripts are inlined; the report
  makes no network request. Its content-security policy hash-pins every inline
  script and forbids remote loads.
- **Print-ready** — the default view prints to about five pages; the appendix
  stays collapsed.
- **Deterministic** — the same registry produces byte-identical HTML.
- **Configurable** — `data/report.toml` (overridable at `.stoa/report.toml`)
  sets the fix-first cap, the agent-collapse tier, and the contradiction
  grouping threshold. See [Configuration](/docs/configuration).

There is also a **Download report** button, and a **Generate underwriting
evidence** action — see [Underwriting evidence](/docs/underwriting).

> Open a live one: the [demo scan report](/demo-report) is a real scan of the
> [Meridian](/docs/example) reference app.

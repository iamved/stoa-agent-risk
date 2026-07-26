# Sparkwing — a deliberately risky K-12 ed-tech demo

A fictional mentored-project-learning platform (mentor matching, student
project sandboxes, portfolio certification, a project-sector chat advisor,
parent progress updates) used to demonstrate what `stoa scan` surfaces in an
ed-tech agentic pipeline. **Every risk in here is planted on purpose** — see
[RISK_MAP.md](RISK_MAP.md) for the finding-by-finding mapping, organized
around Stoa's eight risk dimensions, and [COVERAGE.md](COVERAGE.md) for what's
been verified end-to-end against this fixture (CLI flags, the diff/approve
loop, redaction, false-positive precision).

Kept deliberately smaller than [`examples/meridian-ops`](../meridian-ops):
five agents, no MCP layer, no multi-language surface — a scenario, not an
exhaustive feature exercise.

## The pipeline

```
                 ┌──────────────────┐         ┌────────────────────┐
  staff  ──────► │  mentor_matcher  │         │  progress_notifier │ ◄── weekly
  (confirms)     │  (LangGraph,     │         │  (LangChain,       │     cron
                 │   recommend-only)│         │   SendGrid + HTTP) │
                 └──────────────────┘         └────────────────────┘

  student chat ► sector_advisor (framework-free, raw loop)

  submission  ─► project_sandbox (LangChain, runs a model-suggested
                 shell check against it — no sandbox construct)

  submission  ─► portfolio_certifier (LangChain, decides + writes the
                 badge outcome straight to the DB — no gate)
```

Non-agent controls: `lib/content_search.py` (embeddings-only — not an agent)
and `lib/session_client.py` (a `UserAgentParser`, not an *AI* agent despite
the name). `tests/test_portfolio.py` carries a placeholder key, reported at
low confidence, never gates.

## Try it

```bash
pipx install stoa-agent-risk
stoa scan examples/sparkwing
open stoa-report.html
```

Pre-generated outputs from exactly that command (with `stoa-declared.toml`
loaded) are committed in [`sample-output/`](sample-output/).

```bash
stoa scan examples/sparkwing --strict   # exits 1 — see RISK_MAP.md
```

## The assurance packet

```bash
stoa export --assurance examples/sparkwing/sample-output/registry.json --format md
```

Surfaces all 14 assurance areas for Sparkwing, plus a dedicated Contradictions
section citing both DECL001 (declared vs. scanned) and DECL006 (never
declared) with evidence on both sides.

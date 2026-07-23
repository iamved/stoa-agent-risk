# Stoa

**[stoa-agent-risk.dev](https://stoa-agent-risk.dev)** · [Case study](https://stoa-agent-risk.dev/case-study) · [Live demo report](https://stoa-agent-risk.dev/demo-report) · [PyPI](https://pypi.org/project/stoa-agent-risk/)

**A local-first AI agent inventory and risk scanner** that identifies agent
candidates with supporting evidence, maps their capabilities and integrations,
and prevents newly introduced high-confidence critical risks from entering
the codebase.

Stoa scans Python, JavaScript, and TypeScript repositories statically — no
runtime hooks, no uploads, no accounts.

## What Stoa does

- **Discovers likely AI agents** (LangChain, LangGraph, CrewAI, AutoGen,
  LlamaIndex, OpenAI Agents SDK, PydanticAI, Bedrock Agents, Semantic Kernel,
  LiteLLM, and raw provider calls) using weighted evidence, and shows exactly
  *why* each candidate was detected.
- **Maps providers, frameworks, integrations, and capabilities** — e.g. an
  agent candidate with payment access, database reads, and Slack messaging.
- **Detects high-confidence risks**: hardcoded credentials, hardcoded
  passwords, interpolated SQL, swallowed exceptions, insecure HTTP, missing
  request timeouts, and control-review prompts.
- **Produces local reports**: a manager-friendly self-contained HTML report
  and a deterministic, versioned JSON registry.
- **Gates only newly introduced critical findings by default** — existing
  debt never blocks an unrelated pull request.

Stoa reports *candidates* and *evidence*, not certainties. A "control not
observed" prompt is a review nudge, not a proven vulnerability.

## Quick start

```bash
pipx install stoa-agent-risk
cd my-repository
stoa scan .
open stoa-report.html
```

`stoa scan .` writes `stoa-report.html` and `stoa-registry.json` and exits 0
(report-only) unless a gate is configured. The JSON is designed to be read by
coding assistants too:

```bash
stoa scan . --json stoa-registry.json
```

## GitHub Actions

```bash
stoa init github
```

This creates (without overwriting existing files — use `--force` to
overwrite):

- `.github/workflows/stoa.yml` — full-history checkout, pinned Stoa install,
  full-repository scan, diff against the PR base branch, GitHub annotations,
  a job summary, uploaded HTML/JSON artifacts, and a gate that fails **only**
  when the PR introduces a new high-confidence critical finding.
- `.stoaignore` — gitignore-style path exclusions.
- `stoa.toml` — configuration with documented defaults.

## CLI

```bash
stoa scan [PATH]
  --html PATH               HTML report (default stoa-report.html)
  --json PATH               JSON registry (default stoa-registry.json)
  --base GIT_REF            enable diff-aware behavior (e.g. origin/main)
  --strict                  fail on all unsuppressed high-confidence criticals
  --fail-on {none,high,critical}
  --fail-on-new {none,high,critical}   applies with --base
  --github-annotations      emit ::error/::warning workflow commands
  --summary-file PATH       write a GitHub job-summary Markdown file
  --config PATH             explicit stoa.toml
  --no-git                  skip git metadata
  --no-ast                  disable the AST layer and flow-based AI rules
  --include / --exclude     extra path patterns (repeatable)
  --verbose / --quiet
```

Exit codes: `0` gate passed · `1` gate failed · `2` invalid arguments or
configuration · `3` scanner execution error.

Only high-confidence findings from gate-eligible rules can fail a scan —
SEC001, SEC002, and AI002 (exec class). SQL-interpolation, network, and
review-prompt rules report but never gate, because static analysis cannot
prove exploitability. Data-flow AI rules (AI001/AI002/AI004/AI006) use a
tree-sitter AST layer that is on by default; `--no-ast` runs regex-only.

## Suppression

Inline, on the same or preceding line, always with explicit rule IDs:

```python
# stoa: ignore[SEC003] trusted identifier from internal enum
query = f"SELECT * FROM {table_name}"
```

```javascript
const endpoint = "http://staging.internal.corp"; // stoa: ignore[NET001]
```

File-wide:

```python
# stoa: ignore-file[CTRL001,CTRL002]
```

Suppressed findings are counted and shown in reports — never silently
discarded. There is no blanket `ignore-all`.

## Configuration

`stoa.toml` in the repository root (all values shown are defaults):

```toml
fail_on = "none"          # gate on all findings at/above this severity
fail_on_new = "critical"  # gate on newly introduced findings (with --base)
max_file_bytes = 1000000
follow_symlinks = false
respect_gitignore = true

ignore_paths = [          # merged with built-in defaults (node_modules, dist, …)
  "tests/snapshots/**",
]

[severity]                # per-rule severity overrides
NET001 = "info"

[rules]                   # per-rule enable/disable
CTRL003 = false

[gate]                    # opt extra rules into the gate (beyond AI002 exec)
additional_rules = ["AI001"]

[rules.AI006]             # org-approved network egress destinations
allowed_hosts = ["api.internal.corp", "hooks.slack.com"]

[rules.AI004]             # extra PII identifiers to match
pii_terms = ["employee_id", "account_number"]
```

`.stoaignore` uses gitignore syntax for path exclusions. Tests and fixtures
are *not* ignored by default — secret scanning is still useful there — but
they are downweighted for agent detection and placeholder-secret heuristics
apply.

## Rules

Core rules (regex/pattern):

| Rule | Title | Default severity | Gates? |
|---|---|---|---|
| SEC001 | Possible hardcoded API credential | critical | yes (high confidence only) |
| SEC002 | Possible hardcoded password | high (critical at high confidence) | yes (high confidence only) |
| SEC003 | Interpolated SQL statement | high | no |
| REL001 | Swallowed exception | medium | no |
| NET001 | Insecure non-local HTTP endpoint | medium | no |
| NET002 | Request timeout not observed | medium | no |
| CTRL001–003 | Auth / validation / rate-limit control not observed | info | never |

### AI agent security rules (OWASP LLM Top 10)

New in v0.2 (see [docs/rules/](docs/rules/)). Three require data-flow analysis
and use the tree-sitter AST layer (on by default; `--no-ast` disables it and
these rules). All are report-only except AI002 exec-class.

| Rule | Canonical | OWASP | Default severity | Gates? |
|---|---|---|---|---|
| AI001 | STOA-LLM01-PROMPT-EXPOSURE | LLM01 | high | no (opt-in) |
| AI002 | STOA-LLM02-OUTPUT-EXEC | LLM02 | critical | **yes — exec class at high confidence** |
| AI003 | STOA-LLM08-UNOBSERVED-APPROVAL | LLM08 | info | never |
| AI004 | STOA-LLM06-SENSITIVE-INTERPOLATION | LLM06 | medium (high for secrets) | no |
| AI005 | STOA-LLM05-UNPINNED-MODEL | LLM05 | low–high by variant | no |
| AI006 | STOA-EXFIL-NETWORK | LLM06 | high | no (opt-in) |
| AI007 | STOA-SAMPLING-CONFIG | LLM05 | info | never |
| CTRL004 | STOA-CTRL-OBSERVABILITY | LLM10 | info | never |

AI002 is the only new rule that can fail a build, and only for the exec class
(model output reaching `eval`/`exec`/`subprocess`, …) at high confidence — the
one case a static flow can essentially prove.

## Security model

- **Local-first.** No source code is uploaded anywhere; Stoa makes no network
  calls and collects no telemetry.
- **Secrets are redacted before serialization.** A detected credential is
  replaced with `prefix…[REDACTED:sha256-fingerprint]` the moment it is
  matched; the raw value never reaches terminal output, JSON, HTML,
  annotations, summaries, or logs.
- Static analysis has **false positives and false negatives**. Findings are
  evidence for review, not verdicts.

## Schema stability

The JSON output is versioned and additive-first — see [SCHEMA.md](SCHEMA.md).
Consumers must ignore unknown fields. The field names `autonomy_level`,
`loss_scenarios`, `liveness_state`, `policy_lines`, and `exposure_class` are
reserved for future versions. Treat `stoa-registry.json` as a CI artifact;
committing it to the repository is not recommended.

## Limitations

- Regex and pattern-based; no AST or semantic analysis.
- No runtime behavior: capability evidence does not prove a code path
  executes, and call sites are not API call counts.
- No cross-repository or organization-wide infrastructure visibility: a
  control "not observed in this file" may exist elsewhere.
- No definitive ownership inference — "last touched by" is commit history,
  not ownership; CODEOWNERS support covers the common gitignore-style subset
  of GitHub's pattern syntax (order-sensitive last-match-wins; bracket
  character classes and per-file section syntax are not supported).
- Python, JavaScript, and TypeScript only.
- Data-flow (AI001/AI002/AI004/AI006) analysis is **intra-file** — flows through
  other files are not visible.
- Only the repository-root `.gitignore` and `.stoaignore` are consulted.

## CI bypass considerations

- The workflow installs a **pinned** Stoa release from PyPI rather than
  executing scanner code from the pull request, so a PR cannot modify the
  scanner to bypass enforcement.
- Protect `.github/workflows/stoa.yml`, `stoa.toml`, and `.stoaignore` with
  CODEOWNERS and branch protection — a PR that edits them can weaken the
  gate, so those edits deserve review.
- Inline suppressions (`# stoa: ignore[...]`) change what the gate sees;
  review them like any other security-relevant change.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## License

MIT — see [LICENSE](LICENSE).

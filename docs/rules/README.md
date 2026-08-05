# Stoa rules

Each rule has a stable short ID (used in suppressions, `stoa.toml`, and
gating) and, for AI rules, a canonical name (used in reports and SARIF).

Suppress any rule inline by short ID:

```python
value = "..."  # stoa: ignore[AI002] reviewed: dispatched through a static allowlist
```

## Core rules

| ID | Title | Severity | Gates? |
|---|---|---|---|
| SEC001 | Possible hardcoded API credential | critical | yes (high conf.) |
| SEC002 | Possible hardcoded password | high→critical | yes (high conf.) |
| SEC003 | Interpolated SQL statement | high | no |
| REL001 | Swallowed exception | low | no |
| NET001 | Insecure non-local HTTP endpoint | low | no |
| NET002 | Request timeout not observed | medium | no |
| CTRL001–003 | Auth / validation / rate-limit not observed | info | never |
| CTRL005 | Rate limiting not observed on a high-impact-capability loop | low | never |
| CTRL006 | Sandboxing not observed on an exec path | low | never |
| CTRL007 | No kill-switch signal on the agent's entry path | info | never |

## AI agent security rules (OWASP LLM Top 10, v0.2)

| ID | Canonical | Page |
|---|---|---|
| AI001 | STOA-LLM01-PROMPT-EXPOSURE | [AI001.md](AI001.md) |
| AI002 | STOA-LLM02-OUTPUT-EXEC | [AI002.md](AI002.md) |
| AI003 | STOA-LLM08-UNOBSERVED-APPROVAL | [AI003.md](AI003.md) |
| AI004 | STOA-LLM06-SENSITIVE-INTERPOLATION | [AI004.md](AI004.md) |
| AI005 | STOA-LLM05-UNPINNED-MODEL | [AI005.md](AI005.md) |
| AI006 | STOA-EXFIL-NETWORK | [AI006.md](AI006.md) |
| AI007 | STOA-SAMPLING-CONFIG | [AI007.md](AI007.md) |
| CTRL004 | STOA-CTRL-OBSERVABILITY | [CTRL004.md](CTRL004.md) |

All AI rules report line-level evidence. The three data-flow rules
(AI001/AI002/AI004/AI006) carry a redacted `flow` array (source → propagation →
sink) and are intra-file only: *flows through other files are not visible.*

## Contradiction detector (Assurance layer)

Cross-checks [declared facts](../declarations.md) against what the scan
observed — the one thing a self-attested questionnaire can't do. Every
`DECL*` finding carries both a code-evidence `path`/`line` and a
`declared_ref` (the exact `stoa-declared.toml` key it contradicts).

| ID | Title | Severity | Gates? |
|---|---|---|---|
| [DECL001](DECL001.md) | Declared autonomy contradicts inferred autonomy | critical | yes |
| [DECL002](DECL002.md) | Declared economic authority has no enforcement observed | high | yes |
| [DECL003](DECL003.md) | Money/contract permission with no declared economic authority | high | yes |
| [DECL004](DECL004.md) | Scanned data class not present in declared data classes | high | yes |
| [DECL005](DECL005.md) | Production agent has no observability observed | medium | yes |
| [DECL006](DECL006.md) | Scanned agent has no declaration entry | medium | no |
| [DECL007](DECL007.md) | Declaration references an agent id no longer scanned | low | no |

## Runtime contradiction detector (Runtime trace overlay)

Cross-checks declared facts and scanned reach against what **traces
observed** ([docs/runtime.md](../runtime.md)). Emitted only by
`stoa runtime merge`, never by `stoa scan`. Every finding carries both a
`trace_ref` (file + line + span id) and, where a declaration is involved,
a `declared_ref`. All report-only in v1 (shadow mode) — the only runtime
gate is the opt-in `stoa runtime drift --fail-on-drift`. Trace-anchored
findings suppress via `stoa.toml` `[runtime].suppress`.

| ID | Title | Severity | Gates? |
|---|---|---|---|
| [RT001](RT001.md) | Declared human oversight not observed at runtime | critical | no |
| [RT002](RT002.md) | Observed monetary action exceeds declared economic authority | high | no |
| [RT003](RT003.md) | Observed capability absent from both registry and declarations | high | no |
| [RT004](RT004.md) | Monitoring declared for a production agent, but no traces observed | medium | no |
| [RT005](RT005.md) | Approval gate observed firing on all high-impact actions | info | never |

# Risk map: what Stoa sees in this pipeline

Output of `stoa scan examples/support-desk` (v0.1.1, committed in
[`sample-output/`](sample-output/)): **14 files → 9 agent candidates (5 high
confidence), 3 critical / 1 high / 3 medium findings, 27 review prompts,
1 suppressed.** Every finding below is planted on purpose.

## The inventory Stoa builds

| Agent candidate | Confidence | Framework | Reaches | Worst finding |
|---|---|---|---|---|
| `billing_agent` / `billing_executor` | high | LangChain | Stripe (payments), Postgres, outbound HTTP | **critical** |
| `account_agent` / `crew` | high | CrewAI | Postgres (writes), SendGrid (email) | **critical** |
| `research_agent` | high | OpenAI Agents SDK | web search, intranet KB | medium |
| `workflow` (orchestrator) | medium | LangGraph | routes to everything above | — |
| `escalation_agent` | medium | raw Anthropic + tools | Zendesk, Slack | medium |
| `triage_agent` | medium | PydanticAI | ticket DB via tool | — |
| `support_widget` (TS) | medium | raw OpenAI + tools | Zendesk | — |

The exposure ranking in the HTML report puts **billing** and **account** on
top: they combine LLM-driven behavior with money movement and database
writes — exactly the pairing a reviewer should see first.

## Finding → risk, agent by agent

### Billing agent — the highest-exposure path
- **SEC001 · critical · high confidence** (`billing_agent.py:16`) — a
  hardcoded API key in a "temporary" fallback. Anyone with repo read access
  owns the key; it also ships in every clone and CI log that prints source.
- **SEC003 · high** (`billing_agent.py:38`) — customer ID interpolated into
  SQL. Combined with an LLM deciding tool inputs, a prompt-injected message
  ("my customer id is `1 OR 1=1`") becomes a data-exfiltration attempt.
- **NET002 · medium** (`billing_agent.py:43`) — ledger sync with no timeout:
  a hung internal service stalls the refund path.
- **Capability pairing** — Stoa flags `payment_access` + `database_read` +
  `tool_calling` on the same candidate: an agent that both *decides* and
  *moves money*. That pairing, not any single finding, is the headline risk.

### Account agent — writes + identity
- **SEC002 · critical · high confidence** (`account_agent.py:15`) — hardcoded
  production DB password, on an agent with `database_write` and `email_send`.
  The combination is an account-takeover toolkit: change the email, send the
  reset link.

### Escalation agent — silent failure
- **REL001 · medium** (`escalation_agent.py:44`) — the on-call Slack ping
  swallows all exceptions. Escalations can silently vanish, which for a
  support desk is an availability incident nobody notices.

### Research agent — untrusted ingress
- **NET001 · medium** (`research_agent.py:31`) — plain-HTTP intranet KB.
  Web search + KB content also make this the pipeline's prompt-injection
  ingress: content fetched here flows back toward agents with real powers.

### Review prompts (info, never gate)
27 `CTRL001–003` prompts — one per candidate per control — ask the only
honest question static analysis can: *auth, input validation, and rate
limiting were not observed in these files; do they exist elsewhere?*

## Just as important: what did NOT fire

| File | Why it matters |
|---|---|
| `embeddings.py` | OpenAI import + API call, but embeddings-only → **not an agent** |
| `utils/user_agent.py` | `UserAgentParser` → generic `*Agent` names are weak evidence, **not flagged** |
| `tests/test_billing.py:3` | placeholder key → reported at **low confidence**, can never fail a build |
| `tools/database.py:40` | interpolated-but-reviewed query → **suppressed with a reason**, still counted and listed |
| parameterized queries | `%s` placeholders throughout `database.py` / `account_agent.py` → no SEC003 noise |

## Turning this into a gate

```bash
cd examples/support-desk && stoa init github
```

On every PR, only a **newly introduced, high-confidence critical** (like the
billing key) fails the build. The SQL interpolation, the missing timeout, and
all 27 review prompts inform the report without blocking anyone — pre-existing
debt never punishes an unrelated change.

---

*Stoa reports static evidence, not runtime proof: "payment access" means the
code can reach Stripe, not that any prompt path will. The narratives above are
the reviewer's job — Stoa's job is making sure the reviewer sees them.*

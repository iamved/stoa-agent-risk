# Support Desk — a deliberately risky multi-agent demo

A realistic customer-support orchestration system used to demonstrate what
`stoa scan` surfaces in an agentic pipeline. **Every risk in here is planted
on purpose** — see [RISK_MAP.md](RISK_MAP.md) for the finding-by-finding
mapping.

## The pipeline

```
                      ┌──────────────────┐
  customer chat ────► │  orchestrator.py │  LangGraph supervisor
                      └────────┬─────────┘
        ┌──────────────┬───────┴───────┬────────────────┐
        ▼              ▼               ▼                ▼
  triage_agent   billing_agent   account_agent   escalation_agent
  (PydanticAI)   (LangChain +    (CrewAI +       (Anthropic +
   intent         Stripe +        Postgres +      Zendesk + Slack)
   routing        Postgres)       SendGrid)
                                       ▲
                                 research_agent
                                 (OpenAI Agents SDK + Tavily)
```

Shared tooling: `tools/database.py` (Postgres + Redis), `tools/diagnostics.py`
(subprocess health checks), `web/support_widget.ts` (TypeScript front-door
agent). `embeddings.py` and `utils/user_agent.py` are intentional
**non-agents** — controls for false positives.

## Try it

```bash
pipx install stoa-agent-risk
stoa scan examples/support-desk
open stoa-report.html
```

Pre-generated outputs from exactly that command are committed in
[`sample-output/`](sample-output/).

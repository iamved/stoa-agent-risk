# Meridian — a full end-to-end test bed for Stoa

**Meridian** is a fictional neobank's multi-agent backend, engineered so that a
single `scan` + `diff` + `approve` exercises **every** Stoa feature. It is both
a showcase and an executable acceptance test.

Every risk here is planted on purpose. Crucially, one agent
(`agents/compliance.py`) is **well-controlled** — so the report shows contrast
(good-news `controls_observed`), not just a wall of red.

## Run it

```bash
pipx install stoa-agent-risk
./run-e2e.sh                 # 53 assertions across every feature
# or point at a dev build:  STOA=/path/to/stoa ./run-e2e.sh
```

The driver copies the fixture into a throwaway git repo, builds a base and head
commit (so `stoa diff` has drift to find), then runs the whole tool surface and
asserts each outcome. See [COVERAGE.md](COVERAGE.md) for the feature→assertion
map, or [WALKTHROUGH.md](WALKTHROUGH.md) for a step-by-step tour — one command
per step, each producing a different output (HTML report, SARIF, the diff
changelog, the assurance packet, the architecture graph) with real output
captured from this fixture.

## The agents

| Agent | Framework · lang | Planted to exercise |
|---|---|---|
| `agents/payments.py` | LangChain · py | SEC001, **AI002 exec (gates CI)**, AI002 sql, AI003, AI004, AI005 floating-alias, CTRL004 — the "everything on fire" agent |
| `agents/fraud.py` | CrewAI · py | AI001 (retrieval→prompt), AI006 (secret→egress), AI007, REL001, vector_search |
| `agents/devops.py` | Agno · py | SEC002, shell + cloud + source-control, AI005 insecure-endpoint (⊃ NET001) |
| `web/support_bot.ts` | Vercel AI SDK · ts | AI001, **AI002 markup**, Zendesk/Slack |
| `agents/compliance.py` | LangGraph · py | **well-controlled**: approval interrupt, structlog, `temperature=0`, dated snapshot, auth, validation |
| `agents/research.py` | OpenAI Agents SDK · py | AI005 trust-remote-code + unpinned-artifact, web_search |
| `agents/triage.py` | PydanticAI · py | low-risk baseline |
| `agents/marketing.py` | AutoGen · py | **head-only** — appears as a new agent in the diff |

Non-agents (`lib/embeddings.py`, `lib/user_agent.py`) and a parameterized-SQL
module (`lib/db.py`) are false-positive controls that must **not** fire.

## What the diff scenario covers

Between the base and head commits: a **new agent** (`marketing`), an
**escalation** (`devops` gains `cloud_resource_access`), a new integration
(`support_bot` gains Slack) — with `dimension_delta`, a Markdown changelog, the
`--fail-on-drift` gate, and `stoa approve` writing `.stoa/approvals.toml`.

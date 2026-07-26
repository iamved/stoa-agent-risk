# Threshold — a generic voice-agent stress test for Stoa

**Threshold** is a fictional voice-based screening/intake platform — the
kind of thing that could sit under hiring pre-screens, research-participant
recruitment, or program eligibility checks. It's deliberately horizontal:
the point isn't the business, it's the risk shape a live, unsupervised
conversation with a real person creates, and whether Stoa's detectors hold
up against it.

Every finding here is planted on purpose, designed backward from Stoa's 8
registry dimensions (one deliberate finding per dimension, not coincidental
coverage) and from two real detection gaps found while designing this
fixture — see [Discovered gaps](#discovered-gaps-not-bugs-to-fix-here) below.

## Run it

```bash
pipx install stoa-agent-risk
./run-e2e.sh                 # 26 assertions
# or point at a dev build:  STOA=/path/to/stoa ./run-e2e.sh
```

## Try it yourself

```bash
stoa scan examples/threshold-voice && open stoa-report.html
```

Look at the **Contradictions** section first — that's the headline. Then in
the agent risk map, compare `escalation_agent` (red, `unrestricted_autonomous`)
against `consent_manager` (the well-controlled baseline) to see what "good"
looks like next to "bad" in the same scan.

```bash
stoa graph stoa-registry.json --out threshold.mmd   # paste into a Mermaid viewer
stoa export --assurance stoa-registry.json          # the 14-area packet, Markdown by default
```

In the graph, `intake_tools` and `widget_client` render as identical hexagons
("MCP server") even though only one of them actually is one — that's the
misclassification gap in `graph LR` form.

## Architecture

```
caller (voice) → orchestrator → conversation_agent → intake MCP server
                      ↓                                     ↑
                 extraction_agent                  escalation_agent
                      ↓                                     ↓
                  (database)                          (database, no gate)
                                                             ↓
                                                        notifier → analytics

                                              incentive_agent → Stripe payout
                                                             ↓
                                                          (database)
```

## The agents

| Agent | Framework · lang | Planted to exercise |
|---|---|---|
| `agents/orchestrator.py` | hand-rolled · py | **AI001** (voice transcript → prompt), agentic-loop signal |
| `agents/conversation_agent.py` | LangGraph · py | AI005 floating-alias, MCP tool calls; declares `data_classes=[personal]` (see gaps) |
| `agents/extraction_agent.py` | hand-rolled · py | **AI002/sql** (model summary → INSERT), **CTRL005** (unpaced high-impact loop) — lands `indeterminate` on the autonomy ladder (see gaps) |
| `agents/escalation_agent.py` | CrewAI · py | **AI002/sql**, **AI003** (no gate on a database-write decision), AI007 — inferred `unrestricted_autonomous`; declared `human_approved` → **DECL001** |
| `agents/incentive_agent.py` | LangChain · py | pays participants via **Stripe** (`move_funds` permission), **AI002/sql**, a real hardcoded spend ceiling → inferred `bounded_autonomous` — but undeclared → **DECL003** (a real ceiling, never governed) |
| `agents/consent_manager.py` | LangChain · py | the well-controlled baseline: auth, validation, rate limit, observability, pinned+deterministic sampling — zero contradictions |
| `agents/notifier.py` | hand-rolled (not agentic) · py | **AI006** (participant email → third-party analytics egress) |
| `mcp/intake_tools.py` | MCP server · py | genuine MCP server exposing `save_response`/`flag_for_review`/`schedule_followup` |
| `integrations/calendar_client.py` | pure MCP client · py | **invisible on purpose** — no other agentic signal, never becomes an agent candidate |
| `web/widget_client.ts` | pure MCP client · ts | **misclassified on purpose** — labeled/rendered as an "MCP server" despite being a client |

`agents/notifier.py` is deliberately *not* an agent candidate — a plain
function calling SendGrid/an HTTP endpoint isn't itself agentic by Stoa's
model, the same way Meridian's `lib/` files are deliberately non-agents.
Its AI006 finding lands in `repository_findings`, not tied to any agent.

## The autonomy ladder, all four levels in one fixture

| Level | Agent | Why |
|---|---|---|
| `recommend_only` | `consent_manager`, `conversation_agent`, `orchestrator` | no side-effecting path from model output, or (orchestrator) no other correlating signal |
| `bounded_autonomous` | `incentive_agent` | a real hardcoded spend ceiling, no approval gate |
| `unrestricted_autonomous` | `escalation_agent` | high-impact database write, no approval, no bounding |
| `indeterminate` | `extraction_agent` | a real side-effecting sink and a real high-impact capability, but no tool-binding evidence — the classifier won't guess |

`human_approved` is the one level not demonstrated here — Meridian's
`payments.py` already covers it, and duplicating it here wouldn't add
anything.

## Dimension coverage

One deliberate finding per registry dimension — not incidental overlap:

| Dimension | Finding | Where |
|---|---|---|
| Adversarial-manipulation | AI001 | `orchestrator.py` — voice transcript is attacker-controlled input |
| Output-integrity | AI002/sql | `extraction_agent.py`, `escalation_agent.py` |
| Unauthorized-action / Scope-violation | AI003 + DECL001 (`escalation_agent`), DECL003 (`incentive_agent`) | escalation + incentive agents |
| Data-exfiltration | AI006 | `notifier.py` |
| Behavioral-instability | AI007 | `escalation_agent.py`, `extraction_agent.py` |
| Model-drift | AI005 (floating-alias) | multiple agents |
| Operational-control | CTRL005/007, `consent_manager` contrast | across the board |

## Discovered gaps (not bugs to fix here)

Building this fixture surfaced two real Stoa detection gaps worth knowing
about — the point of a stress-test fixture is to make gaps concrete, not to
paper over them:

1. **MCP client vs. server isn't disambiguated.** `mcp/intake_tools.py` is a
   genuine server; `web/widget_client.ts` only imports the SDK's *client*
   subpath. Both get `frameworks=["mcp"]` and render identically as an
   `mcp_server` node labeled "MCP server," because the JS/TS trigger is a
   bare substring match on `@modelcontextprotocol/sdk` with no path
   awareness. `integrations/calendar_client.py` demonstrates the inverse on
   the Python side: pure client glue with no other agentic signal never
   clears the agentic-signal floor at all — it's invisible, not
   misclassified.

2. **A declared data class can be scan-blind.** `conversation_agent`
   accurately declares `data_classes = ["personal"]`. DECL004 (undeclared
   data class) only cross-checks the `"authentication"` class today, tied
   specifically to a leaked-secret signal — there's no scan-side pattern for
   "this code touches personal/participant data" at all. The declaration is
   accurate and will never be contradicted, correct or not — Stoa has
   nothing to check it against.

A smaller, related note: `extraction_agent.py` has a real side-effecting
sink (AI002) and a real high-impact capability (`database_write`), but no
tool-binding decorator — so it lands `indeterminate` rather than
`unrestricted_autonomous`, because the autonomy ladder's unrestricted branch
requires tool-binding evidence, not capability alone. Left as-is rather than
forced into a cleaner-looking bucket, since it's a genuine, honest boundary
case for a hand-rolled (non-framework) batch job.

## The declaration story

`stoa-declared.toml` declares three of the eleven agent candidates —
realistic partial rollout, not full coverage:

- **`escalation_agent` (`decision_agent`)** — declared `human_approved`,
  scanner infers `unrestricted_autonomous` → **DECL001**, critical.
- **`conversation_agent`** — declares `data_classes=[personal]` accurately;
  demonstrates the scan-blindness gap above (no DECL004, correctly, since
  nothing contradicts it — but also nothing *could*).
- **`consent_manager`** — fully accurate declaration, matches inferred
  `recommend_only`, zero contradictions: the good-citizen baseline.

**`incentive_agent` is deliberately left out of the file entirely.** It has
a real `move_funds` permission and a real hardcoded spend ceiling in
code — but with no `economic_authority` declared, **DECL003** fires: the
ceiling exists, it was just never formally governed. This is what makes
the "Economic authority" area of `stoa export --assurance` non-empty for
this fixture — without a money-moving agent, that one area (of 14) would
have nothing to report at all, which is accurate but less useful as a
demonstration.

The other agent candidates are undeclared, which is itself realistic and
exercises **DECL006** (declared file exists, this agent isn't in it)
repeatedly.

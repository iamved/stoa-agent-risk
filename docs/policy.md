# Policies

A policy says what an agent may do with a tool, and what happens when it
tries to do more. Policies live in `stoa.policy.toml` at the repository root
(`stoa-policy/0.1`), are evaluated by the runtime SDK at tool-call entry, and
start in observe mode: the decision is recorded, the call proceeds. Enforce
per policy when a policy has earned it.

## Write one from the scan

```
stoa policy recommend --registry stoa-registry.json
stoa policy validate
```

`recommend` is deterministic. It takes thresholds from the declaration
(`economic_authority.max_per_action`, `daily_aggregate`) and the pack
defaults otherwise, and every policy carries `recommended_because` (rule
ids, dimension tiers, declaration fields) and `rationale`. A `gaps` list
names what the SDK cannot enforce yet (output policies need
`stoa_rt.check_output()` on the agent's reply) and what is optional because a
control was already detected in code.

## The file

```toml
version = "stoa-policy/0.1"
[defaults]
mode = "observe"            # observe | enforce

[[policies]]
id = "POL-PAY-001"
title = "Approval required above threshold"
scope = { agent = "account-actions", tool = "issue_refund" }   # agent = "*" for every agent
trigger = "tool_call"       # input | tool_call | output | any
condition = { all = [{ amount_gt = 200 }, { approval_missing = true }] }
action = "escalate"         # allow | block | escalate | mask | log
escalate_to = "console"
fail = "closed"             # closed: enforced under enforce mode; open: recorded only
evidence = ["amount", "currency", "approval_span_id"]
maps_to = { dimension = "unreviewed-high-impact-action", owasp_llm = "LLM06", eu_ai_act = "Art. 14" }
rationale = "Declared human_approved; the scan found no approval on the money path."
```

Conditions: `amount_gt`, `amount_gte`, `window_sum_gt { field, window, value }`,
`window_count_gt { window, value }`, `field_in` / `field_not_in { field, values }`,
`regex_match { field, pattern }`, `approval_missing`, `killswitch`,
`classifier { name = "prompt_injection" | "pii", threshold }`, `expr` (the
runtime's expression language), and `all` / `any` lists. Windows read a
small state file beside the traces; a blocked call never counts toward one.
Classifiers are local heuristics, not models, and say so in the evidence.

What an action does: `block` raises `StoaDenied` before the tool runs when
enforced, else records `would block`; `escalate` calls the hook registered
with `stoa_rt.on_approval(fn)` and cites the approval span it mints, and
fails closed when enforced with no hook; `mask` replaces identifier shapes in
text passed through `check_output()`; `log` records; `allow` records. Every
evaluation writes `policy_rules`, `policy_decisions`, `policy_actions` and
the span's `enforcement` (`allowed`, `observed`, `denied`).

## Packs

`stoa policy packs` lists them: `baseline` (kill switch, logging, declared
tools only), `payments` (approval threshold, daily aggregate, per-action
limit, repeated refund), `data` (mask personal data, egress allow-list,
prompt injection), `exec` (shell blocked, sandbox), `tools-mcp` (declared
MCP tools, no production credentials), `fintech-regulated` (approval on
every movement, tight aggregate, masking as the floor). `recommend` picks
packs from the registry: payments for money movers (fintech-regulated when
`[business]` declares regulated financial services), exec for shell or code
execution, data for declared personal data or external integrations,
tools-mcp for MCP clients and servers, baseline always.

## Kill switch

```
stoa kill --agent-id meridian-support --reason "duplicate refunds" --by @ved
stoa kill --agent-id meridian-support --release --by @ved
stoa kill --agent-id meridian-support --drill --traces stoa-traces
```

The flag lives in `.stoa/killswitch.json` (`STOA_KILLSWITCH=name,name` or
`*` overrides from the environment); the SDK reads it at every guarded call
with an mtime cache, no polling. The baseline pack's `POL-BASE-001` blocks
the next tool call while the flag is set. `--drill` sets the flag, times the
first blocked call, releases, and records `seconds_to_stop`: evidence that
the switch works, shown on the Policies screen.

## Where it shows

The dashboard's **Policies** screen lists the file, each policy's outcomes
in the trace window (evaluated, blocked, would block, escalated), the
money-moving and high-impact tools with no block or escalate policy, every
decision that changed or would have changed a call, and the drills. The
Agent Risk Flow Graph marks protected and unprotected tools. The registry
gains an additive `policies` block with the same counts.

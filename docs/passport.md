# Agent passport

One page per agent, from the scan: who it is, what it can do, how risky it
reads, what protects it, what the traces showed, and how far to trust the
page. `stoa-passport/0.1`.

```
stoa passport --agent-id meridian-support                       # passport-meridian-support.html
stoa passport --agent-id meridian-support --runtime stoa-traces  # with observed evidence and policy outcomes
stoa passport --agent-id meridian-support --baseline old-registry.json --json
```

The dashboard's **Passports** screen lists every agent with its primary
risk type, policies, observed spans, evidence mix and validity; each opens
as a printable page.

## What it carries

| Section | Source |
|---|---|
| Identity | the declaration (owner, purpose, status, users, intended autonomy) and the scan (inferred autonomy, where it is defined) |
| In plain words | five deterministic lines: what it can do, what could go wrong, what protects it, what is missing, how good the evidence is |
| Capabilities and reach | each capability with its evidence level: `static` (code), `reachable` (infrastructure), `observed` (traces) |
| Tools | name, money or high impact, guardrails detected |
| Exposure by category | the eight dimensions, with `traces` where the runtime tier re-bucketed one |
| Policies | the policies scoped to the agent, enforced or observe, and their outcomes in the window |
| Runtime, drills and tests | spans and approval rate observed, the last kill-switch drill, the policy test result (`tested` evidence) |
| Drift | unchanged, changed or added against the baseline, with the drift severity |
| Validity | `valid` or `lapsed`: lapses on drift above medium, or 90 days after the scan |
| Verify hash | a hash of the passport body; the registry hash it was built from is named beside it |

## Risk type

One primary type per agent, driven by its highest category:

| Category | Risk type |
|---|---|
| Data leaks | Data Leakage |
| Excess access | Erroneous Transactions, or Data Loss & Corruption when the agent writes but does not move money |
| Unchecked actions | Erroneous Transactions when it moves money, else Data Loss & Corruption |
| Unreliable output | AI Hallucinations |
| Injection risk | Prompt Injections |
| Inconsistent behavior | Algorithmic Bias when it decides about people, else Performance Failure |
| Dependency drift | Performance Failure |
| Missing safeguards | cross-cutting: lowers the confidence of whatever the primary is |

The same classification sits on every agent in the registry (`risk_type`,
`explanation`) and on the Agent Inventory drawer. No model is called; the
text comes from templates over the registry's own facts.

# Autonomy inference

Every agent candidate gets an `autonomy_level` — a static classification of
how unattended its side-effecting reach appears to be, derived entirely from
signals the scanner already computes. It's always present, regardless of
whether [declarations](declarations.md) exist, the same way `capabilities`
and `highest_severity` always are.

## The ladder

| Level | Meaning |
|---|---|
| `recommend_only` | No side-effecting path from model output was observed; output terminates in returns/logs/UI. |
| `human_approved` | A side-effecting path exists, and an approval construct was observed gating it. |
| `bounded_autonomous` | A side-effecting path exists, no approval gate, but a hardcoded cap check or rate limiter bounds it. |
| `unrestricted_autonomous` | A side-effecting path exists with no approval and no bounding. |
| `indeterminate` | The signals don't cleanly resolve. Never a guess — see below. |

## How it's derived

No second taint pass — autonomy inference composes signals the scanner
already produces:

- **AI002** (a model-output → sink flow) with a side-effecting `variant`
  (`exec`, `sql`, `deserialize`, `request`) means a side-effecting path
  exists at all. No such finding → `recommend_only`, immediately.
- **AI003** (a high-impact capability, tool-bound, with no approval
  construct observed) tells the classifier an approval gate is *absent*.
  Its absence, combined with an `APPROVAL_CONSTRUCT` pattern match, tells it
  a gate *is* present — AI003 firing means the scanner already concluded no
  approval was observed, so a stray "approve" elsewhere in the file doesn't
  count.
- **Bounding** (new): a hardcoded numeric cap check (`if amount > MAX_X`) or
  a rate-limiter construct (the same patterns [CTRL003](rules/README.md)
  looks for), searched in the same file as the side-effecting capability.
  This is a same-file proximity signal, not line-adjacency — deliberately
  coarse, and documented as such.

```python
# recommend_only — no side-effecting sink
resp = llm.invoke(prompt)
return resp.choices[0].message.content

# human_approved — approval construct observed, AI003 did not fire
if not human_input("approve refund?"):
    return
stripe.Refund.create(payment_intent=order_id, amount=amount)

# bounded_autonomous — cap check, no approval
if amount > MAX_REFUND:
    raise ValueError("too much")
stripe.Refund.create(payment_intent=order_id, amount=amount)

# unrestricted_autonomous — neither
stripe.Refund.create(payment_intent=order_id, amount=amount)
```

## `indeterminate` is a feature, not a bug

When a side-effecting sink is observed but nothing else correlates — no
high-impact capability, no tool binding, no approval, no bounding — the
classifier reports `indeterminate` with a stated reason, rather than
defaulting to a level it can't actually justify. A false autonomy
classification is worse than an admitted gap: it's exactly the kind of
overconfident, unverifiable claim a static scanner should never make. Check
`autonomy_level.reason` for why.

## Where it shows up

- `stoa-registry.json`: `agents[].autonomy_level = {level, signals, reason}`.
- `stoa-report.html`: a colored badge on each agent card.
- `stoa graph`: agent/MCP-server nodes carry `autonomy_level` in their
  Mermaid/interactive-graph metadata.
- `stoa export --assurance`: area 3 (Autonomy), alongside the declared
  `autonomy_intent` for comparison — see the
  [contradiction detector](declarations.md#contradiction-detector) for what
  happens when they disagree.

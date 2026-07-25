# DECL001 · Declared autonomy contradicts inferred autonomy

*`autonomy_intent` is declared `recommend_only`/`human_approved`, but the
scanner inferred `bounded_autonomous`/`unrestricted_autonomous`.*

- **Severity:** critical · **Gates:** yes (`gateable=True`, standard
  `--fail-on critical` policy — no special-casing).
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when an agent's declared `autonomy_intent`
([declarations](../declarations.md)) claims a human is in the loop, but
[autonomy inference](../autonomy.md) found a side-effecting path with no
correlated approval gate. This is the headline contradiction: a self-attested
"we always require approval" that the code doesn't back up.

## Example

```toml
# stoa-declared.toml
[agents."66d8239dad0b"]
autonomy_intent = "recommend_only"
```

```python
# agents/refund_agent.py — but the code does this unattended:
@tool
def refund(order_id, amount):
    stripe.Refund.create(payment_intent=order_id, amount=amount)
```

Both sides are cited: the code evidence (the AI002/AI003 signal that placed
the agent on the autonomy ladder) and the declared evidence
(`stoa-declared.toml` → `agents."66d8239dad0b".autonomy_intent`).

## Fix

Either add the missing approval control (so inference agrees with the
declaration), or correct the declaration if the autonomous behavior is
intentional.

Suppress: `# stoa: ignore[DECL001] reason`

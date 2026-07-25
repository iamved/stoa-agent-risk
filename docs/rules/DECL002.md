# DECL002 · Declared economic authority has no enforcement observed

*`economic_authority` is declared for this agent, but no cap check or rate
limiter was observed on its money-moving path.*

- **Severity:** high · **Gates:** yes.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when an agent has a declared `economic_authority` limit
(`max_per_action`/`daily_aggregate`/`worst_case_customer_loss`), has a
`move_funds`/`approve_transactions` [permission tag](../declarations.md),
but [autonomy inference](../autonomy.md) found no "bounding" signal (a
hardcoded cap check or rate limiter) anywhere in the file. A declared limit
that nothing in the code actually enforces is a paper control.

## Example

```toml
[agents."d4a34da08b8f".economic_authority]
max_per_action = {amount = 500, currency = "USD"}
```

```python
# no cap check anywhere near this call
stripe.Payout.create(amount=amount)
```

## Fix

Add the enforcement the declaration promises — a hardcoded ceiling, a
rate limiter, or both — or correct the declared limit if it describes a
policy enforced elsewhere (and note that in `governance`).

Suppress: `# stoa: ignore[DECL002] reason`

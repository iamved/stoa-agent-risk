# CTRL005 · Rate limiting not observed on a high-impact-capability loop

*A loop contains a high-impact-capability call site with no rate-limiter or
backoff construct observed within that loop.*

- **Dimension:** operational control (assurance area 8: technical controls).
- **Severity:** low (review) · **Gates:** never.
- **Kind:** AST proximity signal. **Cadence:** one per agent candidate.

## Detection

Fires when, for an agent candidate (confidence ≥ medium), an AST loop node
(`for`/`while`/comprehension) contains a call site matching a high-impact
capability (`payment_access`, `database_write`, `shell_execution`,
`code_execution`, `email_send`, `messaging`, `source_control`,
`cloud_resource_access`, `filesystem_write`) — and **no** rate-limiter or
backoff construct is observed within that same loop's text:

- Rate-limiter libraries (reused from CTRL003): `slowapi`, `flask-limiter`,
  `express-rate-limit`, `rate-limiter-flexible`, `@ratelimit`, `bottleneck`,
  hand-rolled `token_bucket`/`RateLimiter`.
- Backoff/sleep constructs: `time.sleep`, `await asyncio.sleep`,
  `setTimeout`, `backoff`, `tenacity`.

This is a proximity signal scoped to the loop's own text, not the whole file
— a limiter guarding a *different* loop does not silently satisfy this one.

## Vulnerable → remediated

```python
# FLAGGED — unbounded refund loop, no limiter or backoff anywhere in it
for order in orders:
    stripe.Refund.create(payment_intent=order.id, amount=order.amount)

# NOT FLAGGED — backoff observed within the loop
for order in orders:
    time.sleep(1)
    stripe.Refund.create(payment_intent=order.id, amount=order.amount)
```

Suppress: `# stoa: ignore[CTRL005] reason`

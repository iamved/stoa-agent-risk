# CTRL004 · STOA-CTRL-OBSERVABILITY

*Logging/observability construct not observed around agent tool execution.*

- **OWASP:** LLM10 adjacency (monitoring). Dimension: operational control.
- **Severity:** info (review) · **Gates:** never.
- **Kind:** capability correlation. **Cadence:** one per agent candidate.

## Detection

Fires when an agent candidate (confidence ≥ medium) binds at least one tool and
**no observability construct** is observed anywhere in its file. Recognized
constructs:

- Python: `logging.`/`logger.` calls, `structlog`, `loguru`, tracing SDKs
  (`langsmith`, `langfuse`, `opentelemetry`, `traceloop`, `wandb`),
  `tracer`/`span` usage.
- JS/TS: `winston`/`pino`/`bunyan`, `console.error`/`console.warn`, OTel
  `tracer.startSpan`.

`print()` and bare `console.log` do **not** qualify (not durable observability),
but their presence is noted with the `ad_hoc_output_observed` tag — evidence the
author wanted visibility. This is a floor check, not a logging-quality audit.

## Vulnerable → remediated

```python
# FLAGGED — tools execute with no observability construct in the file
@tool
def apply_discount(order_id, pct):
    db.orders.update(order_id, discount=pct)

# NOT FLAGGED — structured logging observed
logger = structlog.get_logger()
@tool
def apply_discount(order_id, pct):
    logger.info("tool.apply_discount", order_id=order_id, pct=pct)
    db.orders.update(order_id, discount=pct)
```

## Finding message

> Agent candidate binds tools executing capability call sites; no logging or
> tracing construct was observed in this file. Observability may exist at
> middleware or platform level and would not be visible to this scan. One review
> prompt per candidate.

Suppress: `# stoa: ignore[CTRL004] reason`

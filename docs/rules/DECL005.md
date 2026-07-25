# DECL005 · Production agent has no observability observed

*This agent is declared `production_status = "production"`, but no
observability construct was observed (CTRL004).*

- **Severity:** medium · **Gates:** yes.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when an agent's declared `production_status`
([declarations](../declarations.md)) is `"production"`, and
[CTRL004](CTRL004.md) (observability construct not observed) fired for that
same agent. A production agent with no logging or tracing is a monitoring
gap regardless of what it's declared as — this rule surfaces it specifically
because the declaration says it matters more.

## Fix

Add logging or tracing (see [CTRL004](CTRL004.md) for recognized
constructs), or correct `production_status` if the agent isn't actually in
production yet.

Suppress: `# stoa: ignore[DECL005] reason`

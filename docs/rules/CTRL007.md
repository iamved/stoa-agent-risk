# CTRL007 · No kill-switch signal observed on the agent's entry path

*No feature-flag or env-var gate was observed that could disable this agent
without a deploy.*

- **Dimension:** operational control (assurance area 8: technical controls).
- **Severity:** info · **Gates:** never.
- **Kind:** capability correlation. **Cadence:** one per agent candidate.

## Detection

Fires when an agent candidate (confidence ≥ medium) has no kill-switch
construct observed anywhere in its file:

- Env-var gates named for the purpose: `ENABLE_*`/`DISABLE_*`/
  `KILL_SWITCH*`/`FEATURE_FLAG*` read via `os.environ`/`os.getenv`/
  `process.env`.
- Feature-flag services: LaunchDarkly, Unleash, Flagsmith, or a
  `feature_flag`-named construct.

This is deliberately the **weakest signal** in the control set — informational
only, never above `info` severity. Most agents don't need a dedicated kill
switch, and this rule can't tell whether a repo-wide deploy gate exists
outside the file it's scanning. Suppressed by the same repo-level control
awareness as CTRL001-003: a kill-switch construct observed *anywhere* in the
repository satisfies every agent, since these gates are usually centralized.

## Vulnerable → remediated

```python
# FLAGGED — no flag or env-var gate anywhere in the file
executor = AgentExecutor(agent=a, tools=[refund_tool])

# NOT FLAGGED — a feature flag gates the agent
if feature_flag_enabled("refund_agent"):
    executor = AgentExecutor(agent=a, tools=[refund_tool])
```

Suppress: `# stoa: ignore[CTRL007] reason`

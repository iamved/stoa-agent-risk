# DECL004 · Scanned data class not present in declared data classes

*The scanner found evidence of a data class this agent touches that isn't in
its declared `data_classes`.*

- **Severity:** high · **Gates:** yes.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when an agent has a `SEC001`/`SEC002` finding (a hardcoded credential
or password) but `"authentication"` isn't in its declared `data_classes`
([declarations](../declarations.md) enum: `personal | financial | health |
confidential | ip | authentication`). A leaked credential is direct evidence
the agent touches authentication-class data, whether or not that was
declared.

This is the first of what's meant to be an extensible correlation — today it
checks one signal (`authentication` via secrets), the same
pattern-is-extensible spirit as every other rule table in Stoa.

## Fix

Add `"authentication"` (or whichever class applies) to the agent's declared
`data_classes`, or confirm the underlying `SEC001`/`SEC002` finding is a
false positive and suppress that instead.

Suppress: `# stoa: ignore[DECL004] reason`

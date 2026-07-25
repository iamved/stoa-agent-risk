# DECL007 · Declaration references an agent id no longer produced by the scanner

*A declared agent id no longer matches any scanned agent.*

- **Severity:** low · **Gates:** no.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per stale id.

## Detection

Fires when `stoa-declared.toml` declares an `[agents."<id>"]` block whose id
doesn't match any agent the current scan produced — the code likely moved,
was renamed, or was removed since the declaration was written. Unlike every
other `DECL` rule, this one has no scanned agent to attach to: it's a
**repository-level** finding pointing at `stoa-declared.toml` itself.

## Fix

Update the declaration to the agent's current id (agent ids are a content
hash of the file path + symbol, so they change if the agent moves or is
renamed), or delete the stale entry if the agent no longer exists.

Suppress: `# stoa: ignore[DECL007] reason`

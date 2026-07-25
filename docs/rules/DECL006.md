# DECL006 · Scanned agent has no declaration entry

*`stoa-declared.toml` exists but doesn't mention this scanned agent.*

- **Severity:** medium · **Gates:** no.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when a `stoa-declared.toml` file exists in the repository, but a
scanned agent has no `[agents."<id>"]` entry in it at all. This is the
"unowned agent" signal — once a repo starts declaring agents, an agent with
no entry is either an oversight or a newer agent that hasn't been declared
yet.

Never fires when no `stoa-declared.toml` exists — the whole assurance layer
is opt-in by presence, and an undeclared agent means nothing until the repo
has started declaring anything.

## Fix

Add an entry — even a partial one, just `name` and `owner`, is enough to
clear this. Run `stoa init declarations` to regenerate the stub with any
newly-scanned agent ids.

Suppress: `# stoa: ignore[DECL006] reason`

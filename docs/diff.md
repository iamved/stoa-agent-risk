# `stoa diff` — agent capability drift

`stoa diff` compares two deterministic registries and answers what a plain scan
cannot: *did any agent's reach change?* It reports capability, integration,
provider, population, and finding drift, plus dimension deltas — as **call sites
added or removed in code**, never runtime behavior. Nothing gates unless you
configure it; unresolvable inputs fail open with a warning.

## Modes

```bash
stoa diff BASE.json HEAD.json              # two committed registries
stoa diff --base-ref origin/main           # reconstruct BASE by scanning the ref
stoa scan . --diff-against origin/main      # scan the worktree, then diff
```

`--base-ref` / `--diff-against` add a temporary `git worktree` at the ref and
scan it with the **current** scanner, so both sides use identical detector
versions (no rule-version skew). A shallow clone or missing ref → a printed
warning and exit 0 (fail-open), never a silent pass.

## Outputs

```
--json PATH     stoa-diff/1.0 machine diff (deterministic, no timestamps)
--md PATH       Markdown changelog (sticky PR-comment template)
--summary       one-line terminal summary
```

## Drift severity

| Event | Drift |
|---|---|
| Existing agent gains a high-impact capability (payment, db-write, shell-exec, …) | **high** |
| Existing agent gains a sensitive integration (Stripe, prod DB, cloud-admin, …) | **high** |
| New agent whose initial set includes a high-impact capability | **high** |
| Non-high-impact capability, non-sensitive integration, or new provider; confidence increase | **medium** |
| Anything removed; provider removed; agent removed | **info** |

Renamed/moved agents are matched by evidence overlap (Jaccard ≥ 0.70 on
line-independent evidence fingerprints), so a move can't launder an escalation
as a fresh baseline.

## Gating

```bash
stoa diff --base-ref origin/main --fail-on-drift high
stoa diff --base-ref origin/main --fail-on-dimension-increase data-exfiltration=elevated
```

`--fail-on-drift` evaluates the **unapproved** max drift; `--fail-on-dimension-increase`
fails when any agent's dimension rises to at least the given level. Exit codes:
`0` pass · `1` gated · `2` bad args / taxonomy mismatch · `3` internal error.

## Approvals

Intentional changes are approved in-repo, reviewed like code — no bot, no server.

```bash
stoa approve --agent-id <id> --capability shell-exec \
  --reason "release-workflow trigger, reviewed in SEC-1234" --by @security-oncall
stoa approve --list
```

Approvals live in `.stoa/approvals.toml` (commit it; protect it with CODEOWNERS
so the named reviewer gates the PR). An approval binds to
`(agent_id, kind, value, evidence_fingerprint)`: if the call site changes
materially the fingerprint no longer matches and the approval is reported
**stale** — approvals can't be farmed once and reused for different code. Active,
stale, and expired approvals all surface; nothing is hidden.

## CI

`stoa init github` wires the drift step into the workflow (`--diff-against` the
PR base, `--fail-on-drift high`) and uploads `stoa-diff.json` +
`stoa-changelog.md` as artifacts. The workflow sets `fetch-depth: 0` so the base
ref resolves.

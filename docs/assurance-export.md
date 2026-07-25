# `stoa export --assurance`

Enterprise assurance frameworks — insurance underwriting, AIUC-1-style
standards, vendor security reviews — ask for data across 14 areas, split
across three source layers: **scanned** (derivable from code), **declared**
(human-supplied business facts, see [Declarations](declarations.md)), and
**ingested** (external artifacts — eval results, incident logs — Stoa
reserves structured slots for these but doesn't generate them).

`stoa export --assurance` walks all 14 areas and emits a packet where every
row is tagged with exactly one status — never silently omitted:

| Status | Meaning |
|---|---|
| `scanned` | Derived from the scan, with a rule id and file:line. |
| `declared` | From `stoa-declared.toml`, with the exact key path. |
| `ingested` | A pointer from the `evidence.*` block (kind, ref, date). |
| `not_provided` | Explicitly listed as a gap — an assurance reviewer needs to see what's missing as much as what's covered. |

## Usage

```bash
stoa export --assurance [REGISTRY] [--format json|md] [--out PATH]
```

- `REGISTRY` optional: read an existing `stoa-registry.json`; omitted → scans
  the current directory fresh.
- `--format md` (default): human/reviewer-readable, one table per area.
- `--format json`: the raw packet, `assurance-packet/1.0`.
- `--out PATH`: write to a file; omitted → stdout.

```bash
stoa scan .
stoa export --assurance stoa-registry.json --format md --out assurance.md
```

## The 14 areas

| # | Area | Layer(s) |
|---|---|---|
| 1 | Business exposure | declared |
| 2 | AI inventory | scanned + declared |
| 3 | Autonomy | scanned (inferred) + declared (intent) |
| 4 | Permissions | scanned |
| 5 | Economic authority | declared + scanned (enforcement check) |
| 6 | Data access | scanned + declared |
| 7 | Dependencies | scanned |
| 8 | Technical controls | scanned |
| 9 | Testing | ingested |
| 10 | Monitoring | ingested (+ CTRL004 scanned) |
| 11 | Governance | declared + ingested |
| 12 | Contracts | declared + ingested |
| 13 | Historical evidence | ingested |
| 14 | Claims evidence | ingested (reserved `observed` provenance — see below) |

Areas 2–6 and 8 are per-agent tables (one row set per scanned agent); areas
1, 7 (dependencies are also per-agent in practice), 9–14 are repository-level
tables.

Area 14 is deliberately all `not_provided` today: Stoa is a static scanner
and has no runtime traces to report. The `observed` edge-provenance value
(already reserved in [the architecture graph](graph.md) and `SCHEMA.md`) is
where a future runtime-trace overlay would surface here.

## Contradictions section

Every packet leads with a dedicated **Contradictions** section — every
`DECL001`-`DECL007` finding from the current scan, with both evidence sides
(code + declared) inline. This is the headline for a reviewer: it's the one
thing a self-attested questionnaire can't produce on its own.

## Determinism

The packet body is deterministic — identical registry input produces an
identical `areas`/`contradictions` output. The only place wall-clock or
caller-supplied values appear is the `header` block (`git_sha`,
`scan_timestamp`), matching the rest of Stoa's no-timestamps-in-content
invariant.

## Sample packet (Markdown, trimmed)

```markdown
## Stoa · Assurance Packet — support-desk

`a1b2c3d` · scanned 2026-07-25T12:00:00Z · Stoa `0.3.0` · registry schema `1.2` · 9 agent(s) · 1 contradiction(s)

### ⚠️ Contradictions (1)

| Rule | Severity | Title | Code | Declared |
|---|---|---|---|---|
| DECL001 | critical | Declared autonomy contradicts inferred autonomy | `agents/billing_executor.py:14` | `agents."509c9ce8c11d".autonomy_intent` |

### Area 1 — Business exposure (declared)

| Field | Status | Evidence |
|---|---|---|
| industries | 📝 declared | `business.industries` |
| revenue | ⬜ not_provided | — |
...
```

## `--sign`

No signing mechanism exists in Stoa today. This is a documented extension
point (`# TODO(assurance-sign)` in `src/stoa/cli.py`), not a built feature —
deliberately deferred rather than half-implemented.

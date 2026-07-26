# `stoa export --assurance`

Enterprise assurance frameworks — insurance underwriting, [AIUC-1](https://www.aiuc-1.com/)
(the AI agent trust standard), vendor security reviews — ask for data across
18 areas, split across three source layers: **scanned** (derivable from
code), **declared** (human-supplied business facts, see
[Declarations](declarations.md)), and **ingested** (external artifacts — eval
results, incident logs — Stoa reserves structured slots for these but
doesn't generate them).

The 18 areas are grouped under AIUC-1's six standard categories (Data &
Privacy, Security, Safety, Reliability, Accountability, Society), plus a
seventh Stoa-only group — insurance-specific exposure (business exposure,
economic authority, claims evidence) — that AIUC-1 doesn't cover, because
AIUC-1 is a trust standard, not an insurance standard. This grouping is a
display header, not an AIUC-1 certification claim; certification requires
their accredited-auditor process.

`stoa export --assurance` walks all 18 areas and emits a packet where every
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
- `--format json`: the raw packet, `assurance-packet/1.1`.
- `--out PATH`: write to a file; omitted → stdout.

```bash
stoa scan .
stoa export --assurance stoa-registry.json --format md --out assurance.md
```

## The 18 areas

| # | Group | Area | Layer(s) |
|---|---|---|---|
| 1 | Index | AI inventory | scanned + declared |
| 2 | Index | Historical evidence | ingested |
| 3 | A — Data & Privacy | Data access | scanned + declared |
| 4 | B — Security | Permissions | scanned |
| 5 | B — Security | Dependencies | scanned |
| 6 | B — Security | Technical controls | scanned |
| 7 | B — Security | Security testing | ingested |
| 8 | C — Safety | Autonomy | scanned (inferred) + declared (intent) |
| 9 | C — Safety | Safety evaluation | declared + ingested |
| 10 | D — Reliability | Reliability scores | scanned |
| 11 | E — Accountability | Accountability | declared + ingested |
| 12 | E — Accountability | Monitoring | ingested (+ CTRL004 scanned) |
| 13 | E — Accountability | Contracts | declared + ingested |
| 14 | E — Accountability | Vendor due diligence | ingested |
| 15 | F — Society | Societal impact | declared (attestation only — never scored) |
| 16 | G — Insurance-specific | Business exposure | declared |
| 17 | G — Insurance-specific | Economic authority | declared + scanned (enforcement check) |
| 18 | G — Insurance-specific | Claims evidence | ingested (reserved `observed` provenance — see below) |

Groups A–F mirror AIUC-1's own six categories, split further where AIUC-1
itself draws a distinction Stoa's data already supports — e.g. AIUC-1
separates third-party adversarial testing (Security) from third-party
harmful-output testing (Safety), so those are two areas (7 and 9), not one.
Group G has no AIUC-1 equivalent: it's the loss-exposure data an insurance
submission needs that a general agent-trust standard was never built to ask
for.

Most per-agent areas are self-explanatory tables (one row set per scanned
agent); area 15 (Societal impact) and area 2 (Historical evidence) are
repository-level, as are most of Group G.

Area 18 (Claims evidence) is deliberately all `not_provided` today: Stoa is a
static scanner and has no runtime traces to report. The `observed`
edge-provenance value (already reserved in [the architecture graph](graph.md)
and `SCHEMA.md`) is where a future runtime-trace overlay would surface here.
Area 15 (Societal impact) is also deliberately never scored — see
[dimensions.md](dimensions.md) for why Stoa treats AIUC-1's Society category
as attestation-only.

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

## Index

### Area 1 — AI inventory (scanned + declared)
...

## G — Insurance-Specific Exposure (beyond AIUC-1)

### Area 16 — Business exposure (declared)

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

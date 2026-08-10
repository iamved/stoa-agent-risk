# Regulatory crosswalk

Stoa's findings are precise but framework-neutral. The **crosswalk** anchors
each rule to the two frameworks a reader is most likely to already speak:
the **OWASP LLM Top 10 (2025)** (an engineer-facing risk class) and the
**EU AI Act** (a compliance obligation). It is a labeling layer — it never
touches scoring.

> Presentation only: dimension scores, exposure buckets, and the proxy cap are
> byte-for-byte identical with or without the crosswalk. A pre-change golden
> snapshot enforces this in CI.

## One job per framework

Every rule carries **one** primary OWASP class and **one** primary EU AI Act
article — not a wall of tags. The mapping lives in a versioned file
(`stoa-crosswalk-1`) and is honest about its own gaps:

- A rule with no genuine OWASP class (a secret, a reliability rule) keeps the
  OWASP slot **blank** rather than forcing a weak tag — its EU AI Act anchor
  still applies.
- A rule Stoa has no detector for stays **visible** as a coverage gap; it is
  never silently dropped.
- NIST AI RMF is not mapped per-rule — it rolls up once, at report level, as
  MAP / MEASURE / MANAGE.

## Where it shows up

| Surface | What the crosswalk adds |
|---|---|
| Report | A per-dimension row stamped with its OWASP class + EU AI Act article and a plain-English reading; an OWASP LLM Top 10 coverage line with gaps kept visible; a report-level NIST paragraph |
| `stoa-registry.json` | A `crosswalk` object on every finding, a per-dimension roll-up on `dimension_summary`, and a top-level `crosswalk` version block (schema 1.5) |
| SARIF | `owasp:<LLMxx>` and `euaiact:<article>` tags on each result and rule, alongside the existing `stoa-dim:` tags — so GitHub Code Scanning can filter by risk class or article |

See the [JSON schema](/docs/schema) for the exact field shapes.

## Says / never-says

Every gloss obeys Stoa's vocabulary discipline: it reports **exposure
observed** and **controls observed**, never "compliant", "protected",
"covered", or "secure". A crosswalk tag is an anchor for a conversation with
an underwriter or an auditor — not a claim that a control works.

## Override it

Point Stoa at your own mapping (to match an internal control catalogue, say)
without touching the scanner:

```toml
# stoa.toml
[crosswalk]
path = ".stoa/crosswalk.toml"
```

The file is versioned like the taxonomy; any rule you omit renders as an
explicit `unmapped` state rather than disappearing.

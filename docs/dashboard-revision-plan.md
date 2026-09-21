# Dashboard revision plan

Trust fixes, Overview rebuild, and a language pass over the dashboard. This is
a presentation, reconciliation and labeling change. Rule logic, dimension
scores, severities and the loss model are not touched.

Branch `dashboard-revision`, from `fe51e38`. One commit per phase, tests
passing at each.

## Where things live

| Thing | Path |
| --- | --- |
| Generator (envelope the page reads) | `src/stoa/dashboard/envelope.py`, `inject.py` |
| Page (React, compiled to one HTML file) | `ui/src/` : `screens/`, `components/`, `data/` |
| View models (every number on screen) | `ui/src/data/selectors.ts`, `overview.ts`, `controls.ts`, `inventory.ts` |
| Demo fixture | `examples/meridian-pay/`, built into `ui/fixtures/*.envelope.json` by `ui/fixtures/build.py` |
| Tests | `tests/test_dashboard_*.py`, `ui/tests/*.test.ts`, `ui/e2e/*.spec.ts` |

There are no image snapshots. "Snapshot tests" here means the committed
fixtures (`tests/test_dashboard_fixtures.py` fails when they go stale) and the
browser specs that assert on rendered text.

## Files by phase

**Phase 1.** New `src/stoa/dashboard/identity.py` (agent identity
resolution) wired into `envelope.py`; `src/stoa/declarations.py` (one new
optional key, see below); `examples/meridian-pay/stoa-declared.toml`;
`ui/src/data/types.ts`, `selectors.ts` (unique agents, merged findings),
new `ui/src/data/agents.ts`, new `ui/src/data/exposure.ts`; `Shell.tsx`
(scope strip, sidebar badge), `Badge.tsx` (exposure tooltip), `Findings.tsx`,
`FindingDrawer.tsx`, `PrintSummary.tsx`, `controls.ts`/`Controls.tsx` (states).

**Phase 2.** `ui/src/data/overview.ts`, `ui/src/screens/Overview.tsx`.

**Phase 3.** `Shell.tsx`, `Icons.tsx`, `Inventory.tsx`, `inventory.ts`,
`AgentDrawer.tsx`, `Findings.tsx`, `Controls.tsx`, `controls.ts`, `Loss.tsx`,
`LossCurve.tsx`, `Evidence.tsx`, plus a new `ui/src/data/labels.ts` for
display labels.

## Decisions where the brief and the data disagree

### The unique agent count is 5, not 6

The brief expects 6. Its own matching rules give 7: normalized names pair
account actions, front, knowledge and escalation (code with AWS), and leave
`support_agent`, `meridian-support-chat` and `meridian-support-ivr` apart,
because `support` does not equal `support_chat`.

The demo's Terraform says otherwise. Both Databricks endpoints serve
`prod.agents.meridian_support`, and the file comments that "the IVR endpoint
serves the same agent". So the demo has **5 agents seen as 11 records**. No
count is hardcoded; this is what resolution returns once that link is
declared.

Names cannot prove that link, so it is declared. The brief asks for "an
explicit link in the declaration file if one exists". None exists today
(`stoa.yaml` is `stoa-declared.toml` in this repo). I add one optional key,
`same_as = ["<agent id>", ...]`, to a declared agent. It is carried into
`declared.same_as` and read only by the dashboard. It feeds no rule and no
score. In the demo it sits on the already-declared code agent, so no
`DECL006` ("not declared") finding appears or disappears. The UI labels a
declared link as "Linked in your declaration file".

Name matching is conservative, because a false merge hides an agent: it only
pairs a code record with an infrastructure record, never two of the same
kind; it ignores generic keys (`agent`, `graph`, `main`, `app`, `bot`); and a
key that matches more than one record on either side pairs nothing.

### Merging findings changes the headline counts

The same rule on two records of one agent becomes one finding with two
evidence locations. Counts follow what is shown, otherwise the table would
not tie to its total. The registry, the CLI, SARIF and the CI gate still
count scanner records, so the Findings screen states both:
"21 findings from 25 scanner records".

"New since last scan" is computed on merged findings. A merged finding is new
only when all of its evidence is new. `DECL001` on account actions has one
old location and one new one, so it is an existing finding that gained a
location, and the high-severity change is +1, not the diff's +2.

Expected differences in the regenerated demo (acceptance item 11), verified
and restated at the end of this file:

| Figure | Before | After | Why |
| --- | --- | --- | --- |
| Agents | 11 | 5, with 11 discovered records | identity resolution |
| Agents that can move money | 3 | 2 | AWS and code records of account actions are one agent |
| Findings | 25 | 21 | `DECL001` 3 to 2, `DECL006` 7 to 4 |
| High severity | 4 | 3 | the merged `DECL001` |
| Medium | 9 | 6 | the merged `DECL006` |
| New high since last scan | +2 | +1 | one of the two is a new location on an existing finding |

Dimension scores, severities and loss figures are unchanged. A unique agent's
exposure in a dimension is the highest level among its records, which is how
the scanner already rolls agents up into a dimension.

### "Scan date" is a commit date

Stoa reads no wall clock, so identical inputs give an identical file. The date
it has is the scanned commit's. The scope strip says "Commit of 15 Sep 2026".
Without git it says nothing about a date.

### Exposure, and the three zero states

The tooltip describes `src/stoa/dimensions.py` as written: exposure is scored
per agent from findings weighted by severity and confidence, plus the agent's
capabilities, minus credit for safeguards detected; a dimension shows the
highest level any one agent reaches. That is why many low-severity findings
spread across agents can still read Low. The scale has four levels
(Elevated, Moderate, Low, None observed); the brief lists three.

For a dimension with zero findings and no level above Low:

- "Limited evidence": the taxonomy marks the dimension `proxy`, meaning a
  static scan sees only configuration signals for it. This comes from
  `data/dimensions.toml`, not a list in the UI, so it tracks the taxonomy. In
  the default taxonomy that is Conduct variability and Dependency drift, the
  two the brief names.
- "No findings": any other dimension with no findings. The taxonomy marks
  three dimensions `partial` (Output fidelity, Injection & tamper surface,
  Control coverage gap), not just Output fidelity. Calling all three "Limited
  evidence" would overstate the gap, so they read "No findings" and keep their
  existing "partly assessed" hint in the agent drawer.
- "Not assessed": the scan carried no dimension assessment at all
  (`--no-dimensions`). The registry does not record which rules ran, so a
  per-dimension "no applicable rules ran" cannot be told apart from "rules
  ran, nothing fired". Data that would unblock it: a list of executed rule ids
  in the registry.

A zero-finding dimension that is Moderate or Elevated (capabilities alone can
do that) keeps its level.

## Requirements blocked by missing data

| Requirement | Gap | Handling |
| --- | --- | --- |
| 2.4 "reopened" finding counts | the diff carries new and resolved only | omitted |
| 2.4 commit and author on a change | present only when the scan ran in git; the fixture is scanned without it | shown when present |
| 2.4 "wider scan scope rather than a system change" | the diff does not record scope | omitted |
| 2.3, 3.7 portfolio loss figure | the model runs per agent; a 1 in 100 year does not add across agents | largest single agent, named; no "All deployments" option |
| 3.4 Spending authority | only declared limits exist | shown from `declared.economic_authority`, blank otherwise |
| 3.6 applicability per safeguard | derivable for human approval only | other rows keep "of N agents" |
| 1.4 "Verified" | no runtime or attestation source | never rendered |

## Things the brief asks for that I am not doing, and why

- Nothing. Items that cannot be met are in the table above.

## Working notes

- Em dashes: none in UI copy. Checked by a test over `ui/src`.
- "guard" as a bare word: replaced in UI copy. The registry field
  `tools[].guards` keeps its name; it is data, not copy.

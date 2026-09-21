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

## What changed and what was skipped

Written after the work, against the regenerated meridian-pay demo.

### Differences in the regenerated demo (acceptance item 11)

Dimension scores, severities, the register, the assurance packet and the
loss model's output are byte-identical to the previous build. The only
registry difference is the new `declared.same_as` key on one agent, which
`tests/test_dashboard_identity.py` shows moves no finding and no score. What
differs is how records are counted:

| Figure | Before | After | Why |
| --- | --- | --- | --- |
| Agents | 11 | 5, with 11 discovered records | identity resolution |
| Agents with payment capability | 3 | 2 | account actions in code and on AWS is one agent |
| Tools | 19 | 13 | a tool seen in an agent's code and again in its Terraform is one tool |
| Findings | 25 | 21, "from 25 scanner records" | `DECL001` 3 to 2, `DECL006` 7 to 4 |
| High severity | 4 | 3 | the merged `DECL001` |
| Medium | 9 | 6 | the merged `DECL006` |
| New high since last scan | +2 | +1, plus "1 known finding now has a second evidence location" | one of the diff's two new records is a second location on a finding the baseline already had |
| Agents at elevated exposure | 3 records | 2 of 5 agents | same |
| Kill switch detected | on every record with no `CTRL007` finding, including Terraform records the rule never runs on | on 0 of 5 agents | detected only for an agent with an assessed code record on which the rule stayed silent |
| Bad year on the Overview | $4.9M (a 20,000-year run) | $5M | now the same 100,000-year run as the Financial Exposure screen |

The last row was a bug this revision introduced and then caught: the Overview
ran a shorter simulation than the detail screen, so the two disagreed by
about 2%. `tests/consistency.test.ts` now asserts they are the same number.

### Findings from the investigation the brief asked for

**The kink in the loss curve is in the model, so it is left alone.** Between
1 in 20 and 1 in 25 the loss is exactly $2,000,000. That is the model's cap
on Erroneous Transactions losses: declared max per action ($500) x monthly
action volume (200,000) x `transCapShare` (0.02). That category is frequent
(0.32 events a year), so many simulated years land exactly on the cap and the
quantile curve goes flat, then resumes. The curve is drawn as a single path
through the model's own quantiles; there are no two segments to join. No
change to the model or to the plotting.

**The loss model's data file renames a dimension.** `lossOutlook.data.json`
spells it "Injection and tamper surface". The UI now shows the taxonomy's
name there instead. The data file is untouched.

**Case cards had a left gold border accent,** which the hard constraints
forbid. Removed.

### Requirements not met, and what would unblock them

| Requirement | Status | What would unblock it |
| --- | --- | --- |
| 1.1 six unique agents | 5, by the demo's own Terraform (see above) | nothing; 5 is the right count |
| 1.3 "Not assessed" per dimension | only for a scan with no dimension assessment at all | a list of executed rule ids in the registry |
| 2.4 reopened finding counts | omitted | the diff tracking findings that were resolved and came back |
| 2.4 commit and author on a change | shown when the scan ran in git; the fixture is scanned without it | nothing; works on a real repository |
| 2.4 "wider scan scope, not a system change" | omitted | the diff recording scan scope (paths, file counts) for both sides |
| 2.3 and 3.7 portfolio loss, "All deployments" | skipped; the largest single agent is shown and named | a portfolio simulation that models agents together. Adding up per-agent 1 in 100 years is not valid, and that would be a change to the model |
| 3.4 Spending authority | from declared limits only, blank otherwise | nothing; the scan cannot know a business limit |
| 3.6 applicability per safeguard | human approval only; the rest say "of N agents" | a rule per safeguard for when it is expected |
| 1.4 "Verified" state | never rendered | a runtime or attestation source |

### Calls that went beyond the letter of the brief

- A new optional `same_as` key in `stoa-declared.toml`. The brief asks for
  "an explicit link in the declaration file if one exists"; none did. It
  feeds no rule and no score.
- The agent filter on Findings always means the unique agent, whichever of
  its records a link names. Otherwise the same agent's two ids gave two
  different lists.
- "Next action" takes the instruction sentence of a rule's remediation, not
  its first sentence. Multi-sentence remediations explain first and instruct
  last ("This agent was declared... Either add the missing approval control,
  or correct the declaration."). The words are always the scanner's.
- Scanner prose (rule messages, remediation, crosswalk sentences) carries em
  dashes into the page, and the same text feeds the CLI, SARIF and the legacy
  report, with 15 test files asserting on it. It is normalized where it is
  displayed (`prose()` in `ui/src/data/labels.ts`) rather than rewritten at the
  source. Text the dashboard authors itself was fixed at the source. A browser
  test reads every screen's visible text and fails on an em dash.
- The insurance checklist's "I have reviewed these fields" is remembered for
  the session only. The page cannot write to the repository, and the
  signature is what makes a confirmation binding. It exists so that step 2
  can honestly become complete and hand the primary button to step 3.
- The printed board report was brought onto the same unique agents, counts and
  wording. It is the one export, and it had kept the old record counts.

### Tests added

- `tests/test_dashboard_identity.py`: explicit link, name match, unmatched
  record, and the false-merge guards (same kind, ambiguous, generic names).
- `ui/tests/consistency.test.ts`: severities sum to the total, records tie to
  the registry summary, and every Overview figure equals its detail screen,
  on all four fixtures. Plus the loss figure across screens.
- `ui/tests/copy.test.ts`: no em dash, no bare "guard", all eight dimension
  names unchanged.
- Browser: the Overview's exact section list and links to all five screens;
  one primary button on the insurance page and no step checked early; the
  drivers block; no em dash, bare "guard", or zero-finding "Low" on any
  rendered screen.

## Things the brief asks for that I am not doing, and why

- Nothing is declined. Items that could not be met from the data are in
  "Requirements not met" above, each with what would unblock it.

## Working notes

- Em dashes: none in UI copy. Checked by a test over `ui/src`.
- "guard" as a bare word: replaced in UI copy. The registry field
  `tools[].guards` keeps its name; it is data, not copy.

# Declarations — `stoa-declared.toml`

Code can't tell you who owns an agent, what it's for, or how much money it's
allowed to move. `stoa-declared.toml` captures those human-supplied facts as
structured, git-reviewed metadata — and the scanner cross-checks them against
what it actually observes (see [Autonomy inference](autonomy.md) and the
[contradiction detector](#contradiction-detector) below).

TOML, not YAML: `stoa.toml` and `.stoa/approvals.toml` are already TOML via
the standard library, so this needed zero new dependencies.

## File shape

```toml
version = 1

[business]
industries = ["fintech"]
regulated_activities = ["payments"]
max_customer_dependency = "high"   # low|medium|high|critical
societal_risk_flags = []           # critical_infrastructure|biosecurity_adjacent|mass_influence
                                    # attestation only (AIUC-1 Society) — Stoa never scores this

[agents."66d8239dad0b"]            # keyed by the scanned agent id (the
name = "billing_agent"             # stable 12-hex hash), not a human slug —
owner = "jane@acme.com"            # `stoa init declarations` stubs these in
purpose = "Reconcile Stripe payouts against invoices"
users = "internal"                 # internal|customers|public
geography = ["us", "eu"]
production_status = "production"   # dev|staging|production|deprecated
autonomy_intent = "human_approved" # recommend_only|human_approved|bounded_autonomous|unrestricted_autonomous
data_classes = ["financial", "personal"]  # personal|financial|health|confidential|ip|authentication

[agents."66d8239dad0b".economic_authority]
max_per_action = {amount = 500, currency = "USD"}
daily_aggregate = {amount = 5000, currency = "USD"}
worst_case_customer_loss = {amount = 50000, currency = "USD"}

[governance]
release_approval = "Documented in RELEASING.md"
incident_response = "runbooks/ir.md"
harmful_output_policy = "docs/safety/risk-taxonomy.md"   # AIUC-1 Safety

[governance.risk_acceptance]
owner = "cto@acme.com"
date = "2026-07-01"

[[evidence.testing]]
kind = "prompt_injection"
ref = "evals/pi-suite/results.json"
date = "2026-07-10"

[[evidence.safety_testing]]
kind = "harmful_output"
ref = "evals/safety-suite/results.json"
date = "2026-07-10"

[[evidence.vendor]]
kind = "vendor_review"
ref = "vendor/openai-review-2026.pdf"
date = "2026-06-01"
```

`evidence` accepts any category — Stoa recognizes `testing`, `safety_testing`,
`monitoring`, `contracts`, `historical`, `vendor` (each a list of
`{kind, ref, date?}` pointers) and surfaces them in the matching
[assurance packet](assurance-export.md) area; unrecognized categories are
preserved but won't be picked up by a named area. Stoa never reads or
validates the referenced artifact; it only records that a pointer exists.

## Getting started

```bash
stoa scan .                 # produces stoa-registry.json with real agent ids
stoa init declarations      # stubs stoa-declared.toml from those ids
```

The stub has every field commented out — nothing is pre-filled, so a partial
declaration is always a deliberate, visible choice, not an accidental
omission.

## Validation

Malformed TOML, or a field that's the wrong shape entirely (e.g. `[agents]`
not a table), fails the scan immediately. Everything else — an invalid enum
value, an unknown key, a malformed amount, a stale agent id — is a warning,
not an error, so a partial or slightly-off declaration still loads:

```
stoa: warning: stoa-declared.toml: agents."abc123".autonomy_intent='yolo'
is not one of ('recommend_only', 'human_approved', 'bounded_autonomous',
'unrestricted_autonomous') — ignored
```

Pass `--strict` to `stoa scan` to turn these warnings into a hard failure —
the same flag that already means "stop tolerating looseness" for findings.

## Contradiction detector

The differentiating capability: every declared fact is cross-checked against
what the scan actually observed. A self-attested questionnaire can't do
this — Stoa can, because both sides come from the same run.

| Rule | Fires when | Severity |
|---|---|---|
| [DECL001](rules/DECL001.md) | declared `recommend_only`/`human_approved`, inferred `bounded_autonomous`/`unrestricted_autonomous` | critical |
| [DECL002](rules/DECL002.md) | `economic_authority` declared, no bounding signal on the money-moving path | high |
| [DECL003](rules/DECL003.md) | money/contract permission, no `economic_authority` declared | high |
| [DECL004](rules/DECL004.md) | scanner evidence of a data class not in declared `data_classes` | high |
| [DECL005](rules/DECL005.md) | `production_status = "production"`, but CTRL004 (no observability) fired | medium |
| [DECL006](rules/DECL006.md) | a scanned agent has no declaration entry at all | medium |
| [DECL007](rules/DECL007.md) | a declared agent id no longer matches any scanned agent | low |

Every `DECL*` finding carries **both** sides of the contradiction: the usual
`path`/`line` (the code evidence) and a new `declared_ref: {path, key}` (the
exact `stoa-declared.toml` key it contradicts) — one click from each in
`stoa-report.html`'s dedicated **Contradictions** section, and in
`stoa scan`'s JSON output.

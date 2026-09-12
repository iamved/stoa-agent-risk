# Marlowe — a Dialogflow CX / Vertex AI Agent Builder fixture, deployed through a module

A fictional utility whose customer agents were built in the **Dialogflow CX
console** and are deployed with Terraform through **one local module called
twice**. Every risk here is planted on purpose, and the fixture has two
subjects at once:

1. **Resolved Terraform.** Nothing in the module is literal. Names, roles,
   and whether the controls exist at all come from module inputs, `locals`,
   a `variable` default overridden by `terraform.tfvars`, `count = var.x ? 1 : 0`,
   `for_each = toset(...)`, and `concat(...)`. Before this fixture, every one
   of those was an unresolved reference and the two agents were indistinguishable.
2. **The Google connector.** A CX agent is the agent; its webhook is the tool,
   followed to the Cloud Function, its service account, and that account's IAM
   roles; security settings and logging are the controls; a knowledge
   connector and a Discovery Engine chat engine are the RAG layer.

Three agents, for contrast:

| Agent | Built in | The IaC layer says |
|---|---|---|
| `module.billing_assistant` | Dialogflow CX | security settings with PII redaction, 30-day retention and insights export; interaction logging; a knowledge connector; webhook roles `bigquery.jobUser` + `bigquery.dataViewer` (read-only) |
| `module.field_service` | Dialogflow CX | **no** security settings, **no** logging; webhook roles `roles/editor` (primitive, project-wide), `pubsub.publisher`, `bigquery.dataEditor` |
| `knowledge_assistant` | Vertex AI Agent Builder | a chat engine that creates its own agent over the `billing-policies` data store; no webhook, no reach beyond the data store |

## What's planted where

| File | Plants |
|---|---|
| `infra/main.tf` | `locals`; two `module "…" { source = "./modules/cx-agent" }` calls whose inputs *are* the contrast; a Discovery Engine data store and chat engine |
| `infra/variables.tf`, `infra/terraform.tfvars` | `project_id` defaults to `marlowe-dev`; tfvars overrides it to `marlowe-prod` — the value Stoa attributes IAM to |
| `modules/cx-agent/main.tf` | the CX agent; `security_settings` chosen by a ternary on `var.redaction`; the security-settings resource behind `count`; the webhook pointing at the function's URI; a knowledge flow behind `count` |
| `modules/cx-agent/webhook.tf` | the Cloud Function, its service account, and `google_project_iam_member` with `for_each = toset(var.webhook_roles)` — the reach |
| `stoa-declared.toml` | all three declared accurately, module instances by their instance symbol |

## What the scan shows

```
files scanned: 6        # 5 .tf + terraform.tfvars
agents found:  3        # 0 from code (there is none)

module.billing_assistant   reach: database_read · tool_calling · vector_search
                           controls credited: validation · observability
                           mandate-overreach 0
module.field_service       reach: cloud_resource_access · database_read · database_write
                                  · messaging · tool_calling   (roles/editor — primitive role, broad reach)
                           controls credited: none
                           mandate-overreach 54
knowledge_assistant        reach: vector_search over billing-policies
```

Each module instance is its own agent with symbol
`module.<call>.google_dialogflow_cx_agent.this`, path inside the module, and
an `IAC_MODULE_CALL` evidence line pointing at the call site in `infra/main.tf`.
The module directory itself is *not* scanned as a bare, uninstantiated agent.

## Acceptance criteria this fixture drives

1. Two module calls → two agents with distinct ids; the module directory emits
   no third agent of its own.
2. The tfvars value (`marlowe-prod`), not the variable default, appears in the
   IAM evidence.
3. `count = var.redaction ? 1 : 0` and the ternary on `security_settings`
   resolve per instance: the control is credited to billing and absent on
   field service.
4. `for_each = toset(concat(...))` expands to one IAM member per role.
5. A chat engine with `agent_creation_config` is an agent; one with
   `dialogflow_agent_to_link` is attributed to the linked CX agent instead.

## Honest limits

- Resolution is module-local: `var.*` with no default and no tfvars, module
  *outputs* referenced from the parent (`module.x.agent_id`), remote state, and
  data sources other than `aws_iam_policy_document` stay unresolved. For a
  fully resolved view, feed Stoa a plan: `stoa scan . --tf-plan plan.json`.
- Only `toset`, `tolist`, `concat`, and `${var|local|each|count}` interpolation
  are evaluated. Any other function (`templatefile`, `format`, `lookup`, …)
  leaves the value unresolved.
- Reach is attributed through `google_*_iam_member/binding` blocks in the same
  module whose member names the webhook's service account. Roles granted
  elsewhere are invisible; unknown roles are reported as not in the dictionary.

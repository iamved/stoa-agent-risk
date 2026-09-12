# Infrastructure as code

Some agents are never written — they are **configured**. On a managed
platform such as Databricks Model Serving or Amazon Bedrock, the platform
runs the loop; the "agent" is a resource block in a Terraform file that says
which model to run, what it may reach, and which controls sit in front of it.
A code scanner walks straight past it, because there is no `AgentExecutor(`,
no `requests.post`, nothing.

The IaC collector reads that resource block instead. It runs inside the
ordinary `stoa scan` — `.tf` is simply a scanned language now — and emits the
agent as a candidate that flows through the same registry, report, dimension
scoring, declarations, and drift as an agent found in code.

> **Scope of this version:** Terraform (`.tf`, `.tfvars`, or a
> `terraform show -json` plan); Databricks Model Serving, Amazon Bedrock
> Agents, Google Dialogflow CX / Vertex AI Agent Builder. Everything else Stoa
> promises still holds — static, local, no `terraform` binary or provider
> plugins at scan time, deterministic output, additive schema, "observed /
> not observed" language.

## Why the IaC layer is strong evidence

The cloud made the operator write down, explicitly, what the code scanner
can only infer:

- **reach** — `databricks_grants` and IAM policies state exactly which
  tables, buckets, and services an identity may read or change;
- **controls** — an `ai_gateway` block or a `guardrail_configuration` states
  whether guardrails, rate limits, and logging are on;
- **tools** — a Bedrock action group *is* a tool binding, pointing at the
  Lambda that executes it;
- **deployment** — a serving endpoint or a Bedrock agent *is* a deployed
  agent, so its existence is not ambiguous;
- **egress** — environment variables and the foundation-model id name the
  model vendor.

Where code gives Stoa a heuristic, infrastructure gives it a declaration.

## Module scope

Terraform treats every `.tf` file in a directory as one configuration, and
real deployments split an agent across files: the agent in `agents.tf`, its
roles in `iam.tf`, the guardrail in `guardrails.tf`. Stoa reads the **module**
— all `.tf` files in a directory together — and follows references between
them. An agent keeps the path of the file that defines it (that is what its
stable id is built from); evidence that came from another file says so:
`… (in infra/iam.tf)`.

## Resolved, not guessed

Enterprise Terraform rarely writes a value down where it is used: names come
from variables, roles from `locals`, and whole agents from a module called
twice. Stoa resolves what the module itself states, and leaves everything
else as an unresolved reference:

| Terraform construct | Stoa behaviour |
|---|---|
| `variable "x" { default = … }` | the default is the value |
| `terraform.tfvars`, `*.auto.tfvars` | override the default (they are scanned files, so a secret in a tfvars is found too) |
| `locals { … }` | resolved against variables and other locals |
| `"${var.x}-svc"`, `"${local.y}"` | interpolated when every part resolves; otherwise left as written |
| `count = var.on ? 1 : 0`, `x = cond ? a : b` | picked once the condition resolves to a boolean |
| `for_each = toset(…)`, `count = n` | expanded to one block per instance; agents get the instance in their symbol (`type.name["key"]`, `type.name[1]`) |
| `toset`, `tolist`, `concat` | evaluated; any other function leaves the value unresolved |
| `data "aws_iam_policy_document"` | its statements are the policy, no JSON needed |
| `module "x" { source = "./modules/agent" … }` | the directory is instantiated with the call's inputs over its own defaults; each call is its own agent, symbol `module.x.<type>.<name>`, path inside the module, an `IAC_MODULE_CALL` evidence line at the call site. A directory used as a module source emits no bare, uninstantiated agents |
| `var.x` with no default, `module.x.output`, remote state, other data sources | **unresolved** — never guessed |

### Or hand Stoa the plan

```
terraform plan -out=tfplan && terraform show -json tfplan > plan.json
stoa scan . --tf-plan plan.json
```

A plan carries every value fully resolved — variables, modules, `for_each`,
functions — and Stoa reads resource links from the configuration's
expression references, so a role ARN that is unknown until apply still links
the agent to its policy. State output (`terraform show -json` on a state)
works the same way. When a plan is supplied it **replaces** file-based agent
discovery so nothing is counted twice; `.tf` files are still scanned for
secrets. A plan has no `file:line`, so evidence anchors at the plan file
(`IAC_PLAN_SOURCE`), and agents take the plan's path.

## What it reads

The recognition dictionary is the IaC analog of the framework patterns used
for code — keyed on resource type instead of a constructor call.

**Databricks**

| Terraform resource | Stoa concept |
|---|---|
| `databricks_model_serving` | **the agent** — a deployed serving endpoint; `served_entities.entity_name` is the Unity Catalog model it runs |
| ↳ its `ai_gateway` block | **controls** — `guardrails` → `validation`, `rate_limits` → `rate_limit`, `inference_table_config` / `usage_tracking_config` → `observability` |
| ↳ `environment_vars` / `external_model` | **egress** — the model provider (`openai`, `anthropic`, …) |
| `databricks_grants` | **reach** — `SELECT` → `database_read`; `MODIFY` / `ALL_PRIVILEGES` → `database_write`; catalog-wide `ALL_PRIVILEGES` is called out as broad reach |
| `databricks_service_principal` | **identity** — the principal grants are attributed through (by name stem) |
| `databricks_vector_search_index` | **RAG data source** (recognized; not yet attributed to an endpoint) |

**Amazon Bedrock**

| Terraform resource | Stoa concept |
|---|---|
| `aws_bedrockagent_agent` | **the agent** — `agent_name`, `foundation_model` (vendor → provider: `anthropic`, `cohere`, `mistral`, always `bedrock`), `agent_resource_role_arn` (where its own reach starts) |
| ↳ `guardrail_configuration` | **control** — `validation`; the referenced `aws_bedrock_guardrail` is named with the policies it carries (content, sensitive information, topic, word, grounding) |
| `aws_bedrock_model_invocation_logging_configuration` | **control** — `observability`, account-wide, credited to every Bedrock agent in the module |
| `aws_bedrockagent_agent_action_group` | **tools** — `tool_calling`; a Lambda executor is followed to its role; `RETURN_CONTROL` is noted as tools running in application code; `AMAZON.CodeInterpreter` → `code_execution` |
| `aws_bedrockagent_agent_knowledge_base_association` | **RAG data source** — `vector_search` |
| `aws_iam_role_policy`, `aws_iam_policy` + `aws_iam_role_policy_attachment` | **reach** — Allow-statement actions on the agent's role and on each tool Lambda's role, mapped to capabilities (below). Three policy forms parse: `jsonencode({...})`, heredoc / literal JSON, and AWS managed policy ARNs |

**Google — Dialogflow CX / Vertex AI Agent Builder**

| Terraform resource | Stoa concept |
|---|---|
| `google_dialogflow_cx_agent` | **the agent** — a conversational agent built in the CX console; provider `google`, integration `gcp` |
| ↳ `security_settings` → `google_dialogflow_cx_security_settings` | **control** — redaction strategy and scope → `validation`; retention window recorded; insights export → `observability` |
| ↳ `enable_stackdriver_logging`, `advanced_settings.logging_settings` | **control** — `observability` |
| `google_dialogflow_cx_generative_settings` | **control** — banned phrases → `validation`; the generative model is recorded |
| `google_dialogflow_cx_webhook` | **tools** — `tool_calling`; a URI referencing a Cloud Function or Cloud Run service is followed to the **service account** it runs as, then to every `google_*_iam_member` / `_binding` naming that account (roles → capabilities, below); a literal external URI → `external_http` |
| `google_dialogflow_cx_tool` | **tools** — OpenAPI → `tool_calling` + `external_http`; function spec → `tool_calling` (runs in application code); data store spec → `vector_search` |
| `google_dialogflow_cx_flow` / `_page` `knowledge_connector_settings` | **RAG** — `vector_search`, data stores named |
| `google_discovery_engine_chat_engine` | **the agent** when it creates its own (`agent_creation_config`), platform `vertex_ai_agent_builder`; **RAG attribution** to the linked CX agent when it uses `dialogflow_agent_to_link` |
| `google_discovery_engine_data_store` | **RAG data source** |

| IAM roles | Capability |
|---|---|
| `roles/bigquery.dataViewer` / `jobUser` / `user`, `datastore.viewer`, `cloudsql.client`, `spanner.databaseReader` | `database_read` |
| `roles/bigquery.dataEditor` / `dataOwner` / `admin`, `datastore.user`, `cloudsql.editor`, `spanner.databaseUser` | `database_read` + `database_write` |
| `roles/storage.objectViewer` · `objectCreator` · `objectAdmin` / `objectUser` / `admin` | `filesystem_read` · `filesystem_write` · both |
| `roles/pubsub.publisher` / `editor` · `pubsub.subscriber` | `messaging` · `queue_access` |
| `roles/run.invoker`, `cloudfunctions.invoker`, `workflows.invoker` | `tool_calling` |
| `roles/owner`, `roles/editor`, `projectIamAdmin`, `serviceAccountTokenCreator`, `compute.admin` | `cloud_resource_access` (primitive roles called out as broad reach) |
| any other role | *nothing* — reported as not in the dictionary |

IAM actions map to capabilities conservatively — the service says *what kind*
of thing the tools may do, not the effective permission set:

| IAM actions | Capability |
|---|---|
| `dynamodb` / `rds` / `rds-data` / `redshift` / `athena` … read verbs | `database_read` |
| … write verbs (`Put*`, `Update*`, `Delete*`, `Execute*`, `*`) | `database_read` + `database_write` |
| `s3:Get*` / `List*` · `s3:Put*` / `Delete*` / `*` | `filesystem_read` · `filesystem_write` |
| `ses:Send*` · `sns:Publish` · `sqs:Send*` | `email_send` · `messaging` · `queue_access` |
| `lambda:Invoke*`, `states:Start*` | `tool_calling` |
| `ssm:SendCommand` · `codecommit:*` | `shell_execution` · `source_control` |
| `*`, `iam:*`, `ec2:*`, `cloudformation:*` (non-read) | `cloud_resource_access` |
| `bedrock:InvokeModel`, `logs:*`, `iam:PassRole`, `secretsmanager:Get*`, `*:Describe*` | *nothing* — plumbing |

`Deny` statements grant nothing; `Condition` blocks are not evaluated; a
policy that arrives as a reference (`data.aws_iam_policy_document.x.json`,
`var.policy`) is reported as **unresolved**, never guessed.

Parsing is a small zero-dependency HCL block extractor: nested and repeated
blocks, lists, references, heredocs, and the object syntax inside
`jsonencode(...)` are understood; a value the module does not resolve
(`var.model`, remote state) is left **unresolved, never guessed**.

## What it emits

Each agent becomes a candidate with:

- `source: iac`, `platform: databricks`, `bedrock`, `dialogflow_cx` or `vertex_ai_agent_builder`,
  `discovery_tier: recognized` (inventoried from the resource definition, not
  yet deep-scanned) — see the [JSON schema](/docs/schema), schema 1.6;
- `symbol` = `<resource_type>.<name>` (the resource type keeps ids
  collision-free), `name` = the human-facing name, a stable id of the usual
  `sha256(path:symbol)` shape, `language: terraform`, `confidence: high`;
- evidence at `file:line`, each attribution path spelled out:
  `AGENT_IAC_SERVING_ENDPOINT` / `AGENT_IAC_BEDROCK_AGENT` /
  `AGENT_IAC_DIALOGFLOW_AGENT` / `AGENT_IAC_CHAT_ENGINE`, `IAC_GRANT`,
  `IAC_IAM_POLICY` (actions, resources, and the role and Lambda they came
  through, with `— wildcard actions, broad reach` where the policy said `*`),
  `IAC_TOOL_BINDING`, `IAC_KNOWLEDGE_BASE`, `IAC_CONTROL_GUARDRAIL` /
  `IAC_CONTROL_RATE_LIMIT` / `IAC_CONTROL_OBSERVABILITY`, `IAC_MODEL_EGRESS`,
  `IAC_FOUNDATION_MODEL`, `IAC_MODULE_CALL`, `IAC_PLAN_SOURCE`;
- integrations `databricks`, `aws` (plus `ses` when the tools may send
  email), or `gcp` (plus `bigquery`), shared with any code agent that uses
  the same SDKs.

Controls stated by infrastructure are credited in `dimension_assessment`
through the **same** `control_credit` math as code-observed controls —
attributed **per agent**, through its own gateway or guardrail, never by
pattern-matching the shared file (which would credit one agent's rate limit
to another).

Secrets are scanned too: a literal API key in a `.tf` is caught and redacted
exactly as in code.

## Three worked examples

The [Tidewater fixture](https://github.com/iamved/stoa-agent-risk/tree/main/examples/tidewater)
is a fictional payments company with two Databricks-hosted agents, planted
for contrast:

```
files scanned: 3        # + infra/main.tf
agents found:  4        # 2 from code, 2 from infrastructure

support_agent  (iac)  reach: database_read (one SELECT grant)
                      controls credited: validation · rate_limit · observability
refund_agent   (iac)  reach: database_read + database_write
                      (ALL_PRIVILEGES on prod, MODIFY on refunds)
                      controls credited: none        egress: openai
```

The [Kestrel fixture](https://github.com/iamved/stoa-agent-risk/tree/main/examples/kestrel)
is a freight company with two Bedrock agents spread across five `.tf` files
and no model call anywhere in its Python:

```
files scanned: 7        # 5 .tf + 2 Lambda handlers
agents found:  2        # both from infrastructure, 0 from code

claims_assistant  reach: database_read · tool_calling · vector_search
                  controls credited: validation (guardrail) · observability (logging)
                  mandate-overreach 0
dispatch_agent    reach: database_write · email_send · messaging · filesystem_write
                         · code_execution · …    (dynamodb:* on *, SES, SNS, AmazonS3FullAccess,
                         code interpreter — all through its tool Lambda's role)
                  controls credited: observability only
                  mandate-overreach 90
```

The [Marlowe fixture](https://github.com/iamved/stoa-agent-risk/tree/main/examples/marlowe)
is a utility whose Dialogflow CX agents are deployed through **one local
module called twice**; the whole contrast lives in the module inputs,
`locals`, a tfvars override, `count = var.x ? 1 : 0` and
`for_each = toset(concat(…))`:

```
files scanned: 6        # 5 .tf + terraform.tfvars
agents found:  3        # two module instances + a Vertex AI Agent Builder chat engine

module.billing_assistant  reach: database_read · tool_calling · vector_search
                          controls credited: validation (redaction, retention) · observability
                          mandate-overreach 0
module.field_service      reach: cloud_resource_access · database_write · messaging · …
                                 (roles/editor on project marlowe-prod — primitive role, broad reach)
                          controls credited: none
                          mandate-overreach 54
knowledge_assistant       reach: vector_search over billing-policies
```

In all three, the infrastructure alone separates the well-fenced agent from the
poorly-fenced one — and because they are ordinary agents, **drift** sees them
too: widening a grant from `SELECT` to `ALL_PRIVILEGES`, or a Lambda policy
from two read actions to `dynamodb:*`, is `database_write` gained, a
high-impact capability, and `stoa diff` reports it as **high** drift.

## Configuration

```toml
[iac]
enabled = true     # default; off => .tf files are still scanned for secrets but emit no agents
```

`.tf` is included by default via `include_extensions`; see
[Configuration](/docs/configuration).

## Honest limits of this version

- **Terraform only** — no `.tf.json`, no Databricks Asset Bundles
  (`databricks.yml`), no CloudFormation or CDK output yet. A plan JSON covers
  any of these once Terraform has produced it.
- **Three platforms** — Azure OpenAI / AI Foundry, Amazon Lex, and Bedrock
  Flows are not yet in the dictionary. GUI builders with no Terraform
  provider (Copilot Studio, Agentforce, ServiceNow) cannot be seen this way.
- **Resolution is module-local.** Variables with no default and no tfvars,
  module outputs read by the parent, remote state, and functions other than
  `toset` / `tolist` / `concat` stay unresolved. The plan input removes all
  of these limits at once.
- **Reach is attributed through the module.** A Databricks grant reaches an
  endpoint through its service principal's name stem; a Bedrock policy
  through a role, a CX webhook through its executor's service account, each
  defined in the same module (or module instance). Anything created
  elsewhere is reported as unresolved. IAM evaluation is deliberately
  shallow: no `Condition`, no resource-ARN narrowing, no effective-permission
  computation, and GCP roles outside the dictionary grant nothing.
- **A missing control is visible but does not yet raise exposure.**
  `controls_observed: []` is honest, but the control-coverage dimension is
  driven by absence *findings* that the code rules emit and the IaC layer
  does not yet.
- **Autonomy is uninformative on IaC agents.** `autonomy_level` is inferred
  from code taint that a resource block does not carry, so IaC agents read
  `recommend_only` until they are joined to the code behind them. Read reach
  and `controls_observed` on IaC agents — not autonomy.

## What comes next

In order of value: an **`IAC` rule family** so that a missing guardrail or
security setting, a catalog-wide grant, a wildcard IAM action, or a primitive
GCP role *moves* exposure (with crosswalk entries); the **IaC → code join**
(`entity_name` to the registering model on Databricks; action-group Lambda or
webhook function to its handler), which hands the taint scanner the code and
upgrades the tier to `full`; **Amazon Lex** and **Bedrock Flows**; **Azure
OpenAI / AI Foundry** rows; and **Asset Bundles** as a second input.

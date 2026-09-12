# Infrastructure as code

Some agents are never written — they are **configured**. On a managed
platform such as Databricks Model Serving, the platform runs the loop; the
"agent" is a resource block in a Terraform file that says which model to
serve, what it may reach, and which controls sit in front of it. A code
scanner walks straight past it, because there is no `AgentExecutor(`, no
`requests.post`, nothing.

The IaC collector reads that resource block instead. It runs inside the
ordinary `stoa scan` — `.tf` is simply a scanned language now — and emits the
endpoint as an agent candidate that flows through the same registry, report,
dimension scoring, declarations, and drift as an agent found in code.

> **Scope of this version:** Terraform (`.tf`) and Databricks Model Serving.
> Everything else Stoa promises still holds — static, local, no `terraform`
> binary or provider plugins at scan time, deterministic output, additive
> schema, "observed / not observed" language.

## Why the IaC layer is strong evidence

The cloud made the operator write down, explicitly, what the code scanner
can only infer:

- **reach** — `databricks_grants` state exactly which catalogs, schemas, and
  tables an identity may read or modify;
- **controls** — an `ai_gateway` block states whether guardrails, rate limits,
  and inference tables are on;
- **deployment** — a serving endpoint *is* a deployed agent, so its existence
  is not ambiguous;
- **egress** — the environment variables and external-model configuration
  name the model provider the endpoint calls out to.

Where code gives Stoa a heuristic, infrastructure gives it a declaration.

## What it reads

The recognition dictionary is the IaC analog of the framework patterns used
for code — keyed on resource type instead of a constructor call:

| Terraform resource | Stoa concept |
|---|---|
| `databricks_model_serving` | **the agent** — a deployed serving endpoint; `served_entities.entity_name` is the Unity Catalog model it runs |
| ↳ its `ai_gateway` block | **controls** — `guardrails` → `validation`, `rate_limits` → `rate_limit`, `inference_table_config` / `usage_tracking_config` → `observability` |
| ↳ `environment_vars` / `external_model` | **egress** — the model provider (`openai`, `anthropic`, …) |
| `databricks_grants` | **reach** — `SELECT` → `database_read`; `MODIFY` / `ALL_PRIVILEGES` → `database_write`; catalog-wide `ALL_PRIVILEGES` is called out as broad reach |
| `databricks_service_principal` | **identity** — the principal grants are attributed through |
| `databricks_vector_search_index` | **RAG data source** (recognized; not yet attributed to an endpoint) |

Parsing is a small zero-dependency HCL block extractor: nested and repeated
blocks, lists, and references are understood; a value the file does not
resolve (`var.model`, remote state) is left **unresolved, never guessed**.

## What it emits

Each endpoint becomes an agent candidate with:

- `source: iac`, `platform: databricks`, `discovery_tier: recognized`
  (inventoried from the resource definition, not yet deep-scanned) — see the
  [JSON schema](/docs/schema), schema 1.6;
- `symbol` = `databricks_model_serving.<name>` (the resource type keeps ids
  collision-free), `name` = the endpoint's human-facing name, a stable id of
  the usual `sha256(path:symbol)` shape, `language: terraform`, and
  `confidence: high`;
- evidence at the resource block's `file:line`: `AGENT_IAC_SERVING_ENDPOINT`,
  `IAC_GRANT` (privileges, scope, and the principal they came through),
  `IAC_CONTROL_GUARDRAIL` / `IAC_CONTROL_RATE_LIMIT` /
  `IAC_CONTROL_OBSERVABILITY`, `IAC_MODEL_EGRESS`;
- the `databricks` integration, shared with any code agent that imports the
  Databricks SDK.

Controls stated by the gateway are credited in `dimension_assessment` through
the **same** `control_credit` math as code-observed controls — attributed **per
endpoint**, through its own `ai_gateway`, never by pattern-matching the shared
file (which would credit one endpoint's rate limit to another).

Secrets are scanned too: a literal API key in a `.tf` is caught and redacted
exactly as in code.

## A worked example

The [Tidewater fixture](https://github.com/iamved/stoa-agent-risk/tree/main/examples/tidewater)
is a fictional payments company with two Databricks-hosted agents, planted
for contrast. Before the collector, the scan read the two `.py` files and
the IaC layer was invisible. Now:

```
files scanned: 3        # + infra/main.tf
agents found:  4        # 2 from code, 2 from infrastructure

support_agent  (iac)  reach: database_read (one SELECT grant)
                      controls credited: validation · rate_limit · observability
refund_agent   (iac)  reach: database_read + database_write
                      (ALL_PRIVILEGES on prod, MODIFY on refunds)
                      controls credited: none        egress: openai
```

The infrastructure alone separates the well-fenced endpoint from the
poorly-fenced one — and because the endpoints are ordinary agents, **drift**
sees them too: widening the support grant from `SELECT` to `ALL_PRIVILEGES`
is `database_write` gained, a high-impact capability, and `stoa diff` reports
it as **high** drift.

## Configuration

```toml
[iac]
enabled = true     # default; off => .tf files are still scanned for secrets but emit no agents
```

`.tf` is included by default via `include_extensions`; see
[Configuration](/docs/configuration).

## Honest limits of this version

- **Terraform only** — no `.tf.json`, no Databricks Asset Bundles
  (`databricks.yml`) yet.
- **Databricks only** — Bedrock, Vertex, and Azure OpenAI resources are not
  yet in the dictionary.
- **Reach is attributed heuristically** — a grant reaches an endpoint through
  its service principal's name stem (`support_sp` → `support_agent`); the
  attribution is recorded in the `IAC_GRANT` evidence, not hidden.
- **A missing control is visible but does not yet raise exposure.**
  `controls_observed: []` is honest, but the control-coverage dimension is
  driven by absence *findings* that the code rules emit and the IaC layer
  does not yet.
- **Autonomy is uninformative on IaC agents.** `autonomy_level` is inferred
  from code taint that a resource block does not carry, so endpoints read
  `recommend_only` until they are joined to the code that registers their
  model. Read reach and `controls_observed` on IaC agents — not autonomy.

## What comes next

In order of value: an **`IAC` rule family** so that a missing gateway or a
catalog-wide grant *moves* exposure (with crosswalk entries); the
**`entity_name` → code join**, which hands each endpoint's registering code to
the taint scanner and upgrades its tier to `full`; **Asset Bundles** as a
second input; and **Bedrock / Vertex / Azure OpenAI** rows in the dictionary.

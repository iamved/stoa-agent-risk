# Tidewater — a Databricks-hosted agent fixture

A fictional payments company whose two customer-facing agents run on
**Databricks**: a support agent that answers questions, and a refund agent
that decides and issues refunds. Like Meridian and Sparkwing, **every risk
here is planted on purpose** — but this fixture's real subject is the layer
the other fixtures don't have: the **infrastructure that deploys the agents**
(`infra/main.tf`, `databricks.yml`), where nothing is Python.

Two agents, for contrast:

| Agent | Role | The IaC layer says |
|---|---|---|
| `support_agent` | the well-controlled baseline (recommend-only, read-only) | an AI Gateway with a PII guardrail, safety filter, rate limit, and inference tables; one narrow `SELECT` grant; RAG over policy docs |
| `refund_agent` | the poorly-controlled case (moves money) | **no** AI Gateway; `ALL_PRIVILEGES` on the whole `prod` catalog; `MODIFY` on refunds; declared `human_approved`, which the code contradicts |

## What's planted where

| File | Plants |
|---|---|
| `infra/main.tf` | two `databricks_model_serving` endpoints (the deployed agents); `ai_gateway` controls on one and none on the other; `databricks_grants` giving support one `SELECT` and refund catalog-wide `ALL_PRIVILEGES` + `MODIFY`; a vector-search index (RAG source); service principals (identity) |
| `databricks.yml` | the same two deployments as a Databricks Asset Bundle — the platform's native IaC, a second input format |
| `agents/support_agent.py` | a LangChain tool-calling agent that registers the UC model `prod.agents.support_agent` (the `entity_name` the endpoint serves) — the join key between IaC and code |
| `agents/refund_agent.py` | an OpenAI tool-calling loop whose **tool-call arguments** drive a Stripe refund and a `spark.sql` `UPDATE` with no approval step (AI002, unreviewed high-impact action); registers `prod.agents.refund_agent` |
| `stoa-declared.toml` | `refund_agent` declared `human_approved` — the planted **DECL001** contradiction; `support_agent` declared accurately |

## Before and after the IaC collector

**Before (v0.6.1):** `.tf` files were not on the scanner's extension list at all.

```
files scanned: 2        # agents/*.py only — infra/main.tf and databricks.yml invisible
agents found:  2        # both from code; neither serving endpoint known to exist
```

**After (the IaC collector):** Terraform is a scanned language and every
`databricks_model_serving` resource is an agent — with `source: iac`,
`platform: databricks`, high confidence (a deployed endpoint is not
ambiguous), and evidence at the resource block's `file:line`.

```
files scanned: 3        # + infra/main.tf
agents found:  4        # 2 from code, 2 from infrastructure

support_agent  (iac)  reach: database_read (one SELECT grant)
                      controls credited: validation · rate_limit · observability  (from ai_gateway)
refund_agent   (iac)  reach: database_read + database_write (ALL_PRIVILEGES on prod, MODIFY on refunds)
                      controls credited: none        egress: openai  (OPENAI_API_KEY)
```

Controls are attributed **per endpoint** through the endpoint's own
`ai_gateway` block — never by regex over the shared file, which would have
credited one endpoint's rate limit to the other. Grants reach an endpoint
through its service principal's name stem (`support_sp` → `support_agent`), and
that heuristic is recorded in the `IAC_GRANT` evidence, not hidden. A value
the file cannot resolve (`var.*`) is left unresolved, never guessed.

Each endpoint's `symbol` is `databricks_model_serving.<name>` (the resource
type keeps ids collision-free), its `name` is the endpoint name, and it carries
the `databricks` integration — as does the code that imports the Databricks SDK.
One caveat to read correctly: an IaC agent's **autonomy** is inferred from code
taint that a resource block does not carry, so both endpoints read
`recommend_only` until the `entity_name` → code join lands. On IaC agents, read
reach and `controls_observed`; do not read autonomy as reassurance.

Not yet in this version (follow-ups, in order of value):
- **the `entity_name` → code join** — link each endpoint to the notebook that
  registers its UC model and taint-scan it, upgrading `discovery_tier` from
  `recognized` to `full`;
- **an `IAC` rule family** so that a *missing* control moves dimension
  exposure, not only credits a present one — today refund's absent gateway
  shows as `controls_observed: []` but does not by itself raise
  control-coverage-gap, because that dimension is driven by absence *findings*
  the code rules emit and the IaC layer does not yet;
- **`databricks.yml` (Asset Bundles)** as a second input format;
- **Bedrock / Vertex / Azure OpenAI** rows in the recognition dictionary.

The refund agent's *code* still hides every planted risk from the shipped
scanner, for four stacked reasons unrelated to IaC — documented below and
fixable independently.

## Four discovered detection gaps

| # | Gap | Where | Effect on this fixture | Proven fix |
|---|---|---|---|---|
| A | `spark.sql(…)` (and `conn.execute`, Snowpark `session.sql`) is not a recognized **SQL sink** — only `cursor.execute`, `.raw`, `text`, `.query` are | `ai_taint._SQL` | model output → `spark.sql` UPDATE has nowhere to land; AI002 can't fire | add `\.sql\s*\(` and `\.execute\s*\(` |
| B | the model's **tool calls** (`msg.tool_calls[…].function.arguments`) are not a **model-output taint source** — only `.content` / `.output_text` are | `ai_taint._MODEL_OUTPUT` | the whole function-calling idiom (model picks a tool + args → code runs them) never enters the taint graph | add `\.tool_calls\b`, `\.function\.arguments\b`, Anthropic `\.content\[\d+\]\.input\b` |
| C | the **approval-gate** heuristic matches the whole file, **comments and docstrings included** (`\b(?:approv\|confirm\|…)\w*`) | `rules.APPROVAL_CONSTRUCT` via `autonomy.py` | writing "no approval step observed" in a docstring makes the scanner conclude approval *was* observed → `human_approved`, suppressing DECL001 | strip comment and string-literal nodes (the AST has them) before matching |
| D | a tool binding must be a lowercase literal `tools=[…]`; `tools=TOOLS` and `TOOLS = […]` aren't recognized — in **two** regexes that must agree | `rules.SUPPORTING_PATTERNS["tools"]` and `rules.TOOL_BINDING` | no tool-binding evidence → autonomy `indeterminate` → DECL001 can't fire | widen both to accept any case and an identifier value (excluding `None`/`null`) |

Fixes A and B change **nothing** on Meridian, Sparkwing, support-desk, or
Threshold (findings and autonomy diffed before/after). With all four applied,
`refund_agent` lands at `unrestricted_autonomous` and fires **AI002 + DECL001**;
`support_agent` stays `recommend_only` with no findings.

## Acceptance criteria

**For the IaC collector** (the feature this fixture targets) — a scan must:
- find both serving endpoints from `infra/main.tf` (and `databricks.yml`), as agents with `source: iac`, `platform: databricks`, evidence at the resource's `file:line`;
- read `support_agent`'s reach as one `SELECT` on `prod.customers.transactions` and credit its `ai_gateway` guardrail, rate limit, and inference tables as **controls observed**;
- read `refund_agent`'s `ALL_PRIVILEGES` on `prod` as **mandate overreach**, its `MODIFY` on `prod.payments.refunds` as write reach, and the absent `ai_gateway` as a **control coverage gap**;
- join each endpoint's `entity_name` to the code that registers that UC model, and hand that code to the taint scanner.

**For the detector fixes** — on `agents/refund_agent.py` alone, AI002 and
DECL001 fire and autonomy is `unrestricted_autonomous`; `support_agent.py` is
unchanged; every other example's findings and autonomy are byte-for-byte
unchanged.

## Run it yourself

```bash
stoa scan examples/tidewater          # 4 agents: 2 from code, 2 from infra/main.tf
```

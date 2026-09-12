# Kestrel — an Amazon Bedrock agent fixture

A fictional freight company whose two customer-facing agents run on
**Amazon Bedrock**: a claims assistant that explains where a damage claim
stands, and a dispatch agent that re-routes live shipments and messages
customers and drivers. Like Tidewater, **every risk here is planted on
purpose**, and the subject is the layer a code scanner cannot see: the agents
are *configured* in Terraform, not written in Python. There is no model call
anywhere in this repository's code.

Two agents, for contrast:

| Agent | Role | The IaC layer says |
|---|---|---|
| `claims_assistant` | the well-controlled baseline (read-only) | a guardrail with PII masking, prompt-attack filter and a "no payout promises" topic block; one lookup tool whose Lambda may `GetItem`/`Query` one table; a knowledge base; invocation logging on |
| `dispatch_agent` | the poorly-controlled case (acts in the world) | **no** guardrail; three tools in a Lambda whose role has `dynamodb:*` on every table, SES send, SNS publish, **and** `AmazonS3FullAccess`; the code interpreter switched on |

## What's planted where

Bedrock spreads one agent across several resources, and real repositories
spread those across several files. Stoa reads the **module** (every `.tf` in
the directory) and follows the chain **agent → action group → Lambda → role
→ policy**:

| File | Plants |
|---|---|
| `infra/agents.tf` | two `aws_bedrockagent_agent` resources (the deployed agents); action groups (the tools: Lambda-backed, and `AMAZON.CodeInterpreter`); a knowledge-base association; a `guardrail_configuration` on one agent and none on the other |
| `infra/iam.tf` | the reach. Narrow read policy for the claims Lambda; for the dispatch Lambda a heredoc-JSON policy with `dynamodb:*` on `*`, `ses:SendEmail`, `sns:Publish`, plus a managed `AmazonS3FullAccess` attachment — three policy forms (`jsonencode`, heredoc JSON, managed ARN) |
| `infra/guardrails.tf` | `aws_bedrock_guardrail` (content, PII, topic policies) and account-wide `aws_bedrock_model_invocation_logging_configuration` — controls stated explicitly |
| `infra/data.tf` | the DynamoDB tables and the OpenSearch-backed knowledge base |
| `infra/lambda.tf` | the tool executors, each pointing at its role |
| `functions/*.py` | the Lambda handlers. **Not agents**: no model call. The dispatch handler does an unconditional `update_item`, an email to any address and an SNS publish with whatever the model passed in — invisible to code-side agent detection because the model sits on the other side of the Bedrock boundary |
| `stoa-declared.toml` | both deployments declared accurately, by the same stable id a code agent would get |

## What the scan shows

```
files scanned: 7        # 5 .tf + 2 .py
agents found:  2        # both from infrastructure, 0 from code

claims_assistant  (iac, bedrock)  reach: database_read · tool_calling · vector_search
                                  controls credited: validation (guardrail) · observability (logging)
                                  mandate-overreach 0

dispatch_agent    (iac, bedrock)  reach: database_read · database_write · email_send · messaging
                                         · filesystem_read · filesystem_write · code_execution · tool_calling
                                  controls credited: observability only
                                  mandate-overreach 90
```

Every capability on the dispatch agent carries the evidence it came from —
`IAC_IAM_POLICY` at the `file:line` of the policy, naming the role and the
Lambda it was attributed through, with `— wildcard actions, broad reach`
where the policy said `*`.

## Acceptance criteria this fixture drives

1. Both Bedrock agents are found from `agents.tf` alone; nothing in `functions/`
   is mistaken for an agent.
2. Cross-file resolution: the guardrail, the logging configuration, and every
   IAM policy live in other files and are still attributed.
3. All three policy forms parse; a `data.aws_iam_policy_document` reference is
   reported as **unresolved**, never guessed.
4. Widening the claims Lambda's policy from two read actions to `dynamodb:*` is
   `database_write` gained, and `stoa diff` reports it as **high** drift.

## Honest limits

- Reach is attributed through roles named *in this module*. A role or policy
  created elsewhere (another module, a data source, the console) is reported
  as unresolved.
- `Deny` statements are ignored, `Condition` blocks are not evaluated, and
  resource ARNs are recorded but not used to narrow a capability. IAM
  evaluation is deliberately shallow: enough to say *what kind* of thing the
  tools may do, not to compute effective permissions.
- Autonomy on IaC agents is uninformative (see the Tidewater note); read reach
  and `controls_observed` instead.

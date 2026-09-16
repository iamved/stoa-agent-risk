# Meridian Pay — the refund agent, built three ways

A fictional payments fintech whose support agent issues refunds, waives fees,
updates contact details, reissues cards and changes merchant payout accounts.
The same four agents (front, account-actions, knowledge, escalation) and the
same seven tools are built as **LangGraph code**, **Amazon Bedrock Agents in
Terraform**, and **Databricks Mosaic AI Agent Framework**. Every risk is
planted on purpose, and it is the same set of risks in all three:

| Planted design flaw | Where |
|---|---|
| `issue_refund` retried on failure with no idempotency key — the duplicate-refund near miss | `code/tools/account_tools.py` |
| `change_payout_account` exposed with no gate; policy and prompt say human-only | all three stacks |
| $500 / $150 limits written in the system prompt only | all three stacks |
| one shared service identity for every tool | `code/tools/core_banking.py`, `aws/iam.tf`, `databricks/infra/main.tf` |
| one ticket index for every customer, no tenant filter | `code/rag/retriever.py`, knowledge base, vector index |
| guardrail on the front agent only (AWS); AI Gateway on chat but not IVR (Databricks) | `aws/agents.tf`, `databricks/infra/main.tf` |
| model unpinned in code; pinned by ARN / MLflow version on the platforms | everywhere |
| declared `human_approved` for account actions in `stoa-declared.toml` | contradicted in every stack |

Scan with `stoa scan .` and read the account-actions agent: seven named tools
with their reach, `unrestricted_autonomous`, DECL001 against the declaration,
and AI008 on `issue_refund`.

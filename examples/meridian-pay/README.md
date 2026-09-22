# Meridian Pay — the refund agent, built two ways, and a new support chatbot

A fictional payments fintech whose agents issue refunds, waive fees, update
contact details, reissue cards and change merchant payout accounts. The same
four agents (front, account-actions, knowledge, escalation) and the same
seven tools are built as **LangGraph code** and as **Amazon Bedrock Agents in
Terraform**. In September 2026 a fifth agent arrived: a customer-facing
**support chatbot** in `code/agents/support_agent.py` that binds the account
tools straight to the model, with no identity step and no approval gate.
Every risk is planted on purpose:

| Planted design flaw | Where |
|---|---|
| `issue_refund` retried on failure with no idempotency key — the duplicate-refund near miss | `code/tools/account_tools.py` |
| `change_payout_account` exposed with no gate; policy and prompt say human-only | both stacks, and the chatbot |
| $500 / $150 limits written in the system prompt only | both stacks, and the chatbot |
| one shared service identity for every tool | `code/tools/core_banking.py`, `aws/iam.tf` |
| one ticket index for every customer, no tenant filter | `code/rag/retriever.py`, knowledge base |
| guardrail on the front agent only | `aws/agents.tf` |
| model unpinned in code; pinned by ARN on the platform | everywhere |
| declared `human_approved` for account actions and the chatbot in `stoa-declared.toml` | contradicted by the code |
| the chatbot resolves requests end to end with no identity check | `code/agents/support_agent.py` |

Scan with `stoa scan .` and read the account-actions agent: six named tools
with their reach, `unrestricted_autonomous`, DECL001 against the declaration,
and AI008 on `issue_refund`. The dashboard's history for this example
(`ui/fixtures/build.py`) shows the two months before: account-actions capped
amounts in code and had no tools on AWS yet, and the chatbot did not exist.

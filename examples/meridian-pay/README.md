# Meridian Pay

A fictional payments fintech with five AI agents across three places:

| Agent | Where | What it does |
|---|---|---|
| meridian-front | code (LangGraph) | customer conversation, identity check, routing |
| account-actions | code (LangGraph) | refunds, fee waivers, contact updates, card reissue, payout changes |
| meridian-support | code (LangGraph) | the new support chatbot, added September 2026: resolves requests end to end |
| meridian-knowledge | Amazon Bedrock agent (`aws/`) | answers from the ticket and policy knowledge base |
| meridian-escalation | Databricks model serving (`databricks/`) | drafts case notes for a person |

Every risk is planted on purpose:

| Planted design flaw | Where |
|---|---|
| `issue_refund` retried on failure with no idempotency key, the duplicate-refund near miss | `code/tools/account_tools.py` |
| `change_payout_account` exposed with no gate; policy and prompt say human-only | account-actions and the chatbot |
| $500 / $150 limits written in the system prompt only | account-actions and the chatbot |
| the chatbot resolves requests end to end with no identity check | `code/agents/support_agent.py` |
| one shared service identity for every tool | `code/tools/core_banking.py` |
| one ticket index for every customer, no tenant filter | `code/rag/retriever.py`, the Bedrock knowledge base |
| the knowledge base role reads every table and bucket | `aws/iam.tf` |
| the escalation endpoint's principal can modify the whole prod catalog | `databricks/infra/main.tf` |
| model unpinned in code; pinned by ARN and version on the platforms | everywhere |
| declared `human_approved` for account-actions and the chatbot | contradicted by the code |

Scan with `stoa scan .`. The dashboard's history for this example
(`ui/fixtures/build.py`) shows the two months before: account-actions
capped amounts in code, and the chatbot did not exist.

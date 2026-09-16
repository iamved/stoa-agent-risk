# Tool inventory

An agent's reach is mostly in its tools, and its tools mostly live in another
file. A LangGraph agent that binds `issue_refund` from `tools/account_tools.py`
used to show `tool_calling` and nothing else: the function that posts the
refund was never read as part of the agent. From 0.7.4, tools are
**first-class objects** in the registry, attributed to the agents that bind
them, and their reach is the agent's reach.

## What Stoa collects

A **definition pass** runs over every scanned file and recognizes:

| Idiom | Kind |
|---|---|
| `@tool`, `@function_tool`, `StructuredTool.from_function(func=…)`, `Tool(func=…)` | `langchain_tool` / `openai_function_tool` |
| `@mcp.tool()`, `@server.tool()`; TS `server.tool("name", …)` | `mcp_tool` |
| raw JSON function schemas `{"type": "function", "function": {"name": …}}`, with the `if name == "…"` dispatcher branch that implements them | `json_schema` |
| TS `const x = tool({ parameters: z.object({…}), execute })`, `new DynamicStructuredTool({…})` | `ts_tool` |
| `UCFunctionToolkit(function_names=[…])` | `uc_function` (name only) |
| Bedrock `aws_bedrockagent_agent_action_group` `function_schema` | `bedrock_action_group` (reach from the Lambda's role) |

For each tool: its **parameters**, what its body **reaches** (the same
capability and integration vocabulary agents use, following one hop into
same-file helpers), numeric **guards** on its parameters (`amount > 500`),
what wraps it in a **retry** (`tenacity`, `backoff`, `RetryPolicy`,
`max_retries`), and whether an **idempotency key** or dedupe check is
visible on the path.

A **binding pass** runs per agent file: the names passed to `bind_tools`,
`ToolNode`, `tools=`, `create_react_agent`, TS `tools:`; list variables are
expanded; names resolve to definitions in the same file or one import away.
An MCP server binds every tool it defines.

## What changes downstream

- **`capabilities` and `integrations`** on the agent are the union of its own
  and its tools'. The account-actions agent in
  [Meridian Pay](https://github.com/iamved/stoa-agent-risk/tree/main/examples/meridian-pay)
  gains `payment_access` from six tools defined two directories away.
- **Autonomy** sees tools: a bound tool that reaches a high-impact sink is a
  model-driven side effect, even with no visible taint flow in the agent's
  own file. Meridian's account-actions agent reads `unrestricted_autonomous`
  in all three stacks, and because it is declared `human_approved`,
  **DECL001** fires in all three.
- **The graph and both exports** inherit the wider reach.
- **The registry** carries a `tools` array per agent (schema 1.7, omitted
  when empty). Read it as the first two columns of a payment-access map:
  tool, reach, where defined, guards, retry, idempotency.

## AI008 — non-idempotent money action under retry

The duplicate-refund near miss: a processor call times out, the framework
retries, two refunds post, each under the per-call limit. AI008 fires when a
tool that moves money or performs a write is wrapped in a retry and no
idempotency key or dedupe check is observed on its path:

```
AI008  high  code/tools/account_tools.py:17
`issue_refund` posts a money action and is retried on failure
(stop_after_attempt via _post_refund); no idempotency key or dedupe check was
observed. A timeout after the upstream commits will post it again, and each
attempt is checked against the per-call limit on its own.
```

Dimensions: unreviewed-high-impact-action, control-coverage-gap. Crosswalk:
OWASP LLM06 Excessive Agency, EU AI Act Art. 9. Remediation: an idempotency
key derived from a stable identifier, no retries on money tools, limits
checked per dispute rather than per call.

## Honest limits

- Tools registered dynamically, built in loops, or loaded from configuration
  stay unresolved and are not listed.
- Unity Catalog functions and JSON schemas without a visible dispatcher are
  **name only** (`resolved: false`): money classification comes from the
  name, reach is unknown.
- Guards are recorded but not yet a finding: "limit stated in the prompt,
  not enforced in the tool" is the next rule on this thread.
- Retry detection follows one hop into same-file helpers. A retry configured
  on an HTTP client shared across modules is not seen.

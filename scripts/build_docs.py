#!/usr/bin/env python3
"""Generate Stoa's docs site (sidebar nav + content) into site/docs/."""
import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS_OUT = REPO / "site" / "docs"
FONTS = json.load(open(Path(__file__).parent / "fonts" / "fonts_b64.json"))

# --- navigation ------------------------------------------------------------
NAV = [
    ("Getting started", [
        ("Overview", ""),
        ("Install & first scan", "getting-started"),
    ]),
    ("Concepts", [
        ("Dimension exposure", "dimensions"),
        ("Capability drift", "diff"),
    ]),
    ("Examples", [
        ("Meridian — a multi-agent app", "example"),
    ]),
    ("Rules", [
        ("Rules overview", "rules"),
        ("AI001 · Prompt exposure", "rules/AI001"),
        ("AI002 · Output → exec", "rules/AI002"),
        ("AI003 · Unobserved approval", "rules/AI003"),
        ("AI004 · Sensitive interpolation", "rules/AI004"),
        ("AI005 · Unpinned model", "rules/AI005"),
        ("AI006 · Network exfiltration", "rules/AI006"),
        ("AI007 · Sampling config", "rules/AI007"),
        ("CTRL004 · Observability", "rules/CTRL004"),
    ]),
    ("Reference", [
        ("CLI", "cli"),
        ("Configuration", "configuration"),
        ("JSON schema", "schema"),
    ]),
    ("More", [
        ("Case study", "/case-study"),
        ("Live scan report", "/demo-report"),
    ]),
]

# --- link rewriting for markdown-internal links ----------------------------
def rewrite_link(href: str) -> str:
    if href.startswith(("http://", "https://", "#", "/")):
        return href
    h = href
    if h in ("SCHEMA.md", "../SCHEMA.md"):
        return "/docs/schema"
    if h in ("README.md", "../README.md"):
        return "/docs"
    if h.startswith("docs/rules/") or h == "docs/rules/":
        return "/docs/rules"
    if h.startswith("docs/dimensions"):
        return "/docs/dimensions"
    if h.startswith("docs/diff"):
        return "/docs/diff"
    m = re.match(r"(AI\d{3}|CTRL\d{3})\.md$", h)
    if m:
        return f"/docs/rules/{m.group(1)}"
    if h.endswith(".md"):
        return "/docs/" + h[:-3]
    return href


# --- tiny markdown -> HTML -------------------------------------------------
def inline(text: str) -> str:
    # code spans first (protect from other formatting)
    spans = []
    def stash(m):
        spans.append(m.group(1))
        return f"\x00{len(spans)-1}\x00"
    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"<em>\1</em>", text)
    def link(m):
        return f'<a href="{rewrite_link(m.group(2))}">{m.group(1)}</a>'
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    def unstash(m):
        return f"<code>{html.escape(spans[int(m.group(1))], quote=False)}</code>"
    return re.sub(r"\x00(\d+)\x00", unstash, text)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-")


def md_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = md.split("\n")
    out, toc = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        # fenced code
        if line.startswith("```"):
            lang = line[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            code = html.escape("\n".join(buf), quote=False)
            out.append(f'<pre class="code" data-lang="{lang}"><code>{code}</code></pre>')
            continue
        # heading
        m = re.match(r"(#{1,4})\s+(.*)", line)
        if m:
            level = len(m.group(1)); content = inline(m.group(2))
            sid = slugify(m.group(2))
            if level in (2, 3):
                toc.append((level, m.group(2), sid))
            out.append(f'<h{level} id="{sid}">{content}</h{level}>')
            i += 1; continue
        # table
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[i+1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in header)
            trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            continue
        # blockquote -> callout
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip()); i += 1
            out.append(f'<div class="callout">{inline(" ".join(buf))}</div>')
            continue
        # list
        if re.match(r"\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                items.append(inline(re.sub(r"\s*[-*]\s+", "", lines[i], count=1))); i += 1
            out.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue
        if line.strip() == "---":
            out.append("<hr>"); i += 1; continue
        if line.strip() == "":
            i += 1; continue
        # paragraph (gather until blank)
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,4}\s|```|\s*[-*]\s|>)", lines[i]) and "|" not in lines[i]:
            buf.append(lines[i]); i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")
    return "\n".join(out), toc


# --- shell -----------------------------------------------------------------
def sidebar(active: str) -> str:
    parts = ['<nav class="sidebar" id="sidebar">']
    for section, items in NAV:
        parts.append(f'<div class="nav-section">{html.escape(section)}</div>')
        for label, slug in items:
            if slug.startswith("/"):  # absolute link (case study, report)
                parts.append(f'<a class="nav-link" href="{slug}">{html.escape(label)}</a>')
                continue
            href = "/" if slug == "" else f"/docs/{slug}"
            cls = "nav-link active" if slug == active else "nav-link"
            parts.append(f'<a class="{cls}" href="{href}">{html.escape(label)}</a>')
    parts.append("</nav>")
    return "".join(parts)


def toc_html(toc: list) -> str:
    if len(toc) < 2:
        return ""
    items = "".join(
        f'<a class="toc-l{lvl}" href="#{sid}">{html.escape(txt)}</a>'
        for lvl, txt, sid in toc
    )
    return f'<aside class="toc"><div class="toc-title">On this page</div>{items}</aside>'


def page(title: str, active: str, body_html: str, toc: list, description: str) -> str:
    return SHELL.format(
        title=html.escape(title), description=html.escape(description),
        marcellus=FONTS["Marcellus-400"], mono400=FONTS["IBM Plex Mono-400"],
        mono500=FONTS["IBM Plex Mono-500"], sidebar=sidebar(active),
        content=body_html, toc=toc_html(toc),
    )


SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{description}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>&#127963;</text></svg>">
<title>{title} — Stoa docs</title>
<style>
@font-face{{font-family:Marcellus;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,{marcellus}) format("woff2")}}
@font-face{{font-family:"Plex Mono";font-weight:400;font-display:swap;src:url(data:font/woff2;base64,{mono400}) format("woff2")}}
@font-face{{font-family:"Plex Mono";font-weight:500;font-display:swap;src:url(data:font/woff2;base64,{mono500}) format("woff2")}}
:root{{--bg:#F2F3EF;--raise:#FAFBF8;--ink:#22282A;--mute:#5B6662;--line:#DBE0DA;--accent:#2F7A6C;--accent-soft:#2F7A6C1a;--code-bg:#14191B;--code-ink:#D6DDD8;color-scheme:light}}
@media(prefers-color-scheme:dark){{:root{{--bg:#131719;--raise:#1A2023;--ink:#E0E6E1;--mute:#91A099;--line:#29322F;--accent:#64B3A1;--accent-soft:#64B3A126;--code-bg:#0E1214;--code-ink:#D6DDD8;color-scheme:dark}}}}
:root[data-theme=light]{{--bg:#F2F3EF;--raise:#FAFBF8;--ink:#22282A;--mute:#5B6662;--line:#DBE0DA;--accent:#2F7A6C;--accent-soft:#2F7A6C1a;--code-bg:#14191B;--code-ink:#D6DDD8;color-scheme:light}}
:root[data-theme=dark]{{--bg:#131719;--raise:#1A2023;--ink:#E0E6E1;--mute:#91A099;--line:#29322F;--accent:#64B3A1;--accent-soft:#64B3A126;--code-bg:#0E1214;--code-ink:#D6DDD8;color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
.topbar{{position:sticky;top:0;z-index:20;height:56px;display:flex;align-items:center;gap:16px;padding:0 20px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}}
.brand{{font-family:Marcellus,Georgia,serif;font-size:20px;font-weight:400;display:flex;align-items:center;gap:8px}}
.brand .tag{{font-family:"Plex Mono",monospace;font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);border:1px solid var(--line);border-radius:6px;padding:2px 6px}}
.topbar .spacer{{flex:1}}
.topbar .tlink{{font-size:13.5px;color:var(--mute)}}
.topbar .tlink:hover{{color:var(--ink);text-decoration:none}}
.theme-btn{{background:none;border:1px solid var(--line);border-radius:8px;color:var(--mute);cursor:pointer;font-size:14px;padding:5px 9px;line-height:1}}
.menu-btn{{display:none;background:none;border:1px solid var(--line);border-radius:8px;color:var(--ink);cursor:pointer;padding:5px 9px}}
.layout{{display:grid;grid-template-columns:250px minmax(0,1fr) 200px;gap:0;max-width:1320px;margin:0 auto}}
.sidebar{{position:sticky;top:56px;align-self:start;height:calc(100vh - 56px);overflow-y:auto;padding:22px 14px 40px;border-right:1px solid var(--line)}}
.nav-section{{font-family:"Plex Mono",monospace;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:18px 10px 6px}}
.nav-section:first-child{{margin-top:0}}
.nav-link{{display:block;padding:5px 10px;border-radius:7px;color:var(--mute);font-size:13.5px}}
.nav-link:hover{{background:var(--accent-soft);color:var(--ink);text-decoration:none}}
.nav-link.active{{background:var(--accent-soft);color:var(--accent);font-weight:600}}
main{{padding:34px 44px 80px;min-width:0;max-width:800px}}
.toc{{position:sticky;top:56px;align-self:start;height:calc(100vh - 56px);overflow-y:auto;padding:34px 16px;font-size:12.5px}}
.toc-title{{font-family:"Plex Mono",monospace;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin-bottom:8px}}
.toc a{{display:block;color:var(--mute);padding:3px 0}}
.toc a:hover{{color:var(--ink);text-decoration:none}}
.toc a.toc-l3{{padding-left:12px;font-size:12px}}
main h1{{font-family:Marcellus,Georgia,serif;font-weight:400;font-size:34px;line-height:1.15;margin:0 0 8px}}
main h2{{font-size:22px;margin:38px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
main h3{{font-size:17px;margin:26px 0 8px}}
main p{{margin:0 0 14px}}
main ul{{margin:0 0 14px;padding-left:22px}}
main li{{margin:4px 0}}
code{{font-family:"Plex Mono",monospace;font-size:.86em;background:var(--accent-soft);border-radius:5px;padding:1px 5px;word-break:break-word}}
pre.code{{background:var(--code-bg);color:var(--code-ink);border-radius:10px;padding:14px 16px;overflow-x:auto;font-family:"Plex Mono",monospace;font-size:12.5px;line-height:1.6;margin:0 0 16px;border:1px solid rgba(255,255,255,.06)}}
pre.code code{{background:none;padding:0;color:inherit;font-size:inherit}}
.table-wrap{{overflow-x:auto;margin:0 0 16px;border:1px solid var(--line);border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:color-mix(in srgb,var(--raise) 70%,transparent);font-size:12px;color:var(--mute)}}
tr:last-child td{{border-bottom:none}}
.callout{{background:var(--accent-soft);border-left:3px solid var(--accent);border-radius:8px;padding:12px 16px;margin:0 0 16px;font-size:14px}}
hr{{border:none;border-top:1px solid var(--line);margin:26px 0}}
.pagenav{{display:flex;justify-content:space-between;gap:12px;margin-top:44px;padding-top:20px;border-top:1px solid var(--line)}}
.pagenav a{{font-size:13.5px}}
@media(max-width:1080px){{.layout{{grid-template-columns:250px minmax(0,1fr)}}.toc{{display:none}}}}
@media(max-width:800px){{.layout{{grid-template-columns:1fr}}.menu-btn{{display:block}}.sidebar{{display:none;position:fixed;top:56px;left:0;right:0;bottom:0;height:auto;width:100%;background:var(--bg);z-index:15}}.sidebar.open{{display:block}}main{{padding:24px 20px 60px}}}}
</style>
</head>
<body>
<header class="topbar">
  <button class="menu-btn" onclick="document.getElementById('sidebar').classList.toggle('open')" aria-label="Menu">☰</button>
  <a class="brand" href="/">🏛️ Stoa <span class="tag">docs</span></a>
  <span class="spacer"></span>
  <a class="tlink" href="/">Home</a>
  <a class="tlink" href="https://pypi.org/project/stoa-agent-risk/">PyPI</a>
  <button class="theme-btn" onclick="toggleTheme()" aria-label="Toggle theme">◐</button>
</header>
<div class="layout">
{sidebar}
<main>
{content}
</main>
{toc}
</div>
<script>
function toggleTheme(){{var r=document.documentElement;var cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');var next=cur==='dark'?'light':'dark';r.setAttribute('data-theme',next);try{{localStorage.setItem('stoa-theme',next)}}catch(e){{}}}}
(function(){{try{{var t=localStorage.getItem('stoa-theme');if(t)document.documentElement.setAttribute('data-theme',t)}}catch(e){{}}}})();
</script>
</body>
</html>
"""


# --- inline content for pages without a source file ------------------------
GETTING_STARTED = """# Install & first scan

Stoa is a local-first static scanner for repositories that contain AI agents.
It runs entirely on your machine — no source is uploaded, no telemetry.

## Install

```bash
pipx install stoa-agent-risk
stoa --version
```

Python 3.10+. No accounts, no API keys.

## First scan

```bash
cd my-repository
stoa scan .
open stoa-report.html
```

A scan is **report-only by default** (always exits 0) and writes two files: a
self-contained HTML report (with the Dimension Exposure Matrix at the top) and
`stoa-registry.json` for machines and coding assistants.

## Gate a pull request

```bash
stoa init github
```

This scaffolds a GitHub Actions workflow that scans each PR, diffs agent reach
against the base branch, and fails only on a newly introduced high-confidence
critical finding (AI002 exec class, or a hardcoded credential).

## Use it with a coding agent

```bash
stoa scan . --json stoa-registry.json
```

The registry is deterministic and already redacted, so Claude Code, Cursor, or
Copilot can read it and remediate findings without ever seeing a raw credential.
"""

CLI = """# CLI

```bash
stoa scan [PATH]            # scan a repository (report-only by default)
stoa diff BASE HEAD         # diff agent reach between two registries
stoa approve ...            # record an intentional drift approval
stoa init github            # scaffold the CI workflow
```

## `stoa scan`

```
--html PATH / --json PATH        report + registry output paths
--sarif PATH                     SARIF 2.1.0 with stoa-dim:* tags
--base GIT_REF                   diff-aware gating (added lines only)
--fail-on {none,high,critical}   gate on all findings at/above a severity
--fail-on-new {none,high,critical}
--strict                         fail on high-confidence criticals
--no-ast                         disable the AST layer + flow-based AI rules
--no-dimensions                  skip the dimension assessment + matrix
--taxonomy PATH                  custom dimension taxonomy
--diff-against GIT_REF           scan, then diff reach against a ref
--fail-on-drift {none,low,medium,high}
--fail-on-dimension-increase DIM=LEVEL
--github-annotations / --summary-file PATH
--include / --exclude / --no-git / --verbose / --quiet
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | scan completed, gate passed |
| 1 | findings (or drift) exceeded the configured gate |
| 2 | invalid arguments or configuration |
| 3 | scanner execution error |

## `stoa diff` and `stoa approve`

See [Capability drift](/docs/diff).
"""

CONFIGURATION = """# Configuration

`stoa.toml` in the repository root. All values shown are defaults.

```toml
fail_on = "none"          # gate on all findings at/above this severity
fail_on_new = "critical"  # gate on newly introduced findings (with --base)
max_file_bytes = 1000000
follow_symlinks = false
respect_gitignore = true

ignore_paths = ["tests/snapshots/**"]

[severity]                # per-rule severity overrides
NET001 = "info"

[rules]                   # per-rule enable/disable
CTRL003 = false

[gate]                    # opt extra rules into the gate (beyond AI002 exec)
additional_rules = ["AI001"]

[rules.AI006]             # org-approved network egress destinations
allowed_hosts = ["api.internal.corp", "hooks.slack.com"]

[rules.AI004]             # extra PII identifiers to match
pii_terms = ["employee_id", "account_number"]

[dimensions]              # replace the default dimension taxonomy
taxonomy = ".stoa/dimensions.toml"
```

## Suppression

Inline, rule-scoped, with a reason:

```python
query = f"SELECT * FROM {table}"  # stoa: ignore[SEC003] trusted enum
```

Also `# stoa: ignore-file[CTRL001]`, `.stoaignore` path patterns, and per-rule
toggles above. Suppressed findings are always counted and shown — never hidden.

## `.stoaignore`

Gitignore-style path exclusions. Tests and fixtures are **not** ignored by
default (secret scanning is still useful there) but are downweighted for agent
detection.
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- Meridian worked example (Stoa-themed agent mesh) ----------------------
import math as _math

_AGENTS = [
    ("payments", "LangChain", "Refunds & payouts", "Stripe · Postgres", "crit", "Elevated"),
    ("fraud", "CrewAI", "RAG case triage", "Pinecone · SIEM", "crit", "Elevated"),
    ("compliance", "LangGraph", "Regulatory filings", "Audit log · HITL", "good", "Controlled"),
    ("devops", "Agno", "Infra operations", "Shell · AWS", "crit", "Elevated"),
    ("research", "OpenAI Agents SDK", "Market research", "Tavily · HF models", "warn", "Moderate"),
    ("marketing", "AutoGen", "Campaign send", "SendGrid", "warn", "Moderate"),
    ("support", "Vercel AI SDK", "First-line chat", "Zendesk · Slack", "warn", "Moderate"),
    ("triage", "PydanticAI", "Intent routing", "—", "low", "Baseline"),
]
_DIMS = [
    ("Scope violation", "strong"), ("Data exfiltration", "strong"),
    ("Unauthorized action", "strong"), ("Output integrity", "partial"),
    ("Adversarial manipulation", "partial"), ("Behavioral instability", "proxy"),
    ("Model drift", "proxy"), ("Operational control", "partial"),
]


def _mesh_positions(n, rx=41, ry=39):
    return [(50 + rx * _math.cos(-_math.pi / 2 + i * 2 * _math.pi / n),
             50 + ry * _math.sin(-_math.pi / 2 + i * 2 * _math.pi / n)) for i in range(n)]


def meridian_body() -> str:
    pos = _mesh_positions(len(_AGENTS))
    conn = "".join(f'<line x1="50" y1="50" x2="{x:.1f}" y2="{y:.1f}"/>' for x, y in pos)
    nodes = "".join(
        f'<div class="mnode m-{st}" style="left:{x:.1f}%;top:{y:.1f}%">'
        f'<span class="mdot"></span><span class="mn">{n}</span>'
        f'<span class="mf">{fw}</span></div>'
        for (n, fw, _h, _r, st, _l), (x, y) in zip(_AGENTS, pos)
    )
    roster = "".join(
        f'<tr><td><code>{n}</code></td><td>{fw}</td><td>{h}</td><td>{r}</td>'
        f'<td><span class="mchip mc-{st}">{lbl}</span></td></tr>'
        for (n, fw, h, r, st, lbl) in _AGENTS
    )
    dims = "".join(
        f'<span class="mdim d-{t}">{name}<span>{t}</span></span>' for name, t in _DIMS
    )
    mobile = "".join(
        f'<div class="mrow"><span class="mdot m-{st}"></span><code>{n}</code> · {fw}</div>'
        for (n, fw, _h, _r, st, _l) in _AGENTS
    )
    return f"""
<h1>Example: a multi-agent app</h1>
<p><strong>Meridian</strong> is a demonstration multi-agent backend for a neobank — eight
specialist agents behind one supervisor, across eight frameworks and two languages. It is
Stoa's reference application: every risk is planted on purpose, and one agent
(<code>compliance</code>) is deliberately well-controlled so a scan shows contrast, not just red.
The full source is in <a href="https://github.com/iamved/stoa-agent-risk/tree/main/examples/meridian-ops">examples/meridian-ops</a>.</p>

<div class="mesh">
  <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{conn}</svg>
  <div class="mcore"><span class="ml">Supervisor</span><span class="mcn">orchestrator</span>
    <span class="mf">LangGraph · routes by intent</span></div>
  {nodes}
</div>
<div class="mesh-mobile">{mobile}</div>
<div class="mlegend">
  <span><i class="m-crit"></i>Elevated</span><span><i class="m-warn"></i>Moderate</span>
  <span><i class="m-good"></i>Controlled</span><span><i class="m-low"></i>Baseline</span>
</div>

<h2>The agent mesh</h2>
<p>Each agent owns a slice of the bank's operations. Control status below is from a real Stoa
scan of the codebase.</p>
<div class="table-wrap"><table><thead><tr><th>Agent</th><th>Framework</th><th>Handles</th>
<th>Reaches</th><th>Control status</th></tr></thead><tbody>{roster}</tbody></table></div>

<h2>What a scan reports</h2>
<p>Stoa inventories the agents, maps capabilities and integrations, and scores each across eight
risk dimensions — five assessed directly, three proxy signals flagged for runtime follow-up.</p>
<div class="mdims">{dims}</div>
<div class="callout">Run it yourself: <code>stoa scan examples/meridian-ops</code>, or open the
<a href="/demo-report">live scan report</a>. The comprehensive
<a href="https://github.com/iamved/stoa-agent-risk/blob/main/examples/meridian-ops/run-e2e.sh">run-e2e.sh</a>
driver asserts 53 checks across the whole tool surface.</p>

<style>
.mesh{{position:relative;width:100%;max-width:720px;margin:20px auto 6px;aspect-ratio:1.6/1}}
.mesh svg{{position:absolute;inset:0;width:100%;height:100%;overflow:visible}}
.mesh line{{stroke:var(--line);stroke-width:1}}
.mcore{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;
  background:var(--raise);border:1px solid var(--accent);border-radius:11px;padding:10px 14px;
  box-shadow:0 0 0 5px var(--accent-soft);z-index:2}}
.mcore .ml{{display:block;font-family:"Plex Mono",monospace;font-size:9.5px;letter-spacing:.15em;
  text-transform:uppercase;color:var(--accent)}}
.mcore .mcn{{display:block;font-family:Marcellus,Georgia,serif;font-size:16px}}
.mnode{{position:absolute;transform:translate(-50%,-50%);background:var(--raise);
  border:1px solid var(--line);border-radius:9px;padding:7px 10px;min-width:96px;text-align:center;z-index:2}}
.mdot{{width:8px;height:8px;border-radius:50%;display:inline-block;margin-bottom:2px}}
.mnode .mn{{display:block;font-family:"Plex Mono",monospace;font-size:12.5px;color:var(--ink)}}
.mf{{display:block;color:var(--mute);font-size:10px}}
.m-crit .mdot,.mdot.m-crit,.mlegend i.m-crit{{background:#c2554a}}
.m-warn .mdot,.mdot.m-warn,.mlegend i.m-warn{{background:#c2872f}}
.m-good .mdot,.mdot.m-good,.mlegend i.m-good{{background:#3f9d74}}
.m-low .mdot,.mdot.m-low,.mlegend i.m-low{{background:#5a86a8}}
.mlegend{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;font-family:"Plex Mono",monospace;
  font-size:11px;color:var(--mute);margin-bottom:8px}}
.mlegend i{{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:middle}}
.mchip{{font-family:"Plex Mono",monospace;font-size:11px;padding:2px 8px;border-radius:20px;
  border:1px solid currentColor}}
.mc-crit{{color:#b3402f}} .mc-warn{{color:#a06a12}} .mc-good{{color:#2f7a53}} .mc-low{{color:#3f688a}}
:root[data-theme=dark] .mc-crit{{color:#e0705e}} :root[data-theme=dark] .mc-warn{{color:#e0a23b}}
:root[data-theme=dark] .mc-good{{color:#57b98a}} :root[data-theme=dark] .mc-low{{color:#5fa8c9}}
@media(prefers-color-scheme:dark){{.mc-crit{{color:#e0705e}}.mc-warn{{color:#e0a23b}}.mc-good{{color:#57b98a}}.mc-low{{color:#5fa8c9}}}}
.mdims{{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 16px}}
.mdim{{font-family:"Plex Mono",monospace;font-size:11.5px;padding:4px 9px;border-radius:8px;
  border:1px solid var(--line);display:inline-flex;gap:7px;align-items:center}}
.mdim span{{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}}
.mdim.d-proxy{{opacity:.7}}
.mesh-mobile{{display:none}}
.mrow{{display:flex;align-items:center;gap:9px;padding:8px 11px;border:1px solid var(--line);
  border-radius:8px;margin-bottom:7px;font-size:13px}}
@media(max-width:700px){{.mesh{{display:none}}.mesh-mobile{{display:block;margin:16px 0}}}}
</style>
"""


# --- landing (card grid) ---------------------------------------------------
CARDS = [
    ("🚀", "Install & first scan", "From pipx install to your first HTML report in three commands.", "/docs/getting-started"),
    ("🧭", "Dimension exposure", "Eight risk dimensions — five direct, three proxy — with deterministic scoring.", "/docs/dimensions"),
    ("📈", "Capability drift", "stoa diff: did any agent's reach change? Approve intentional changes in-repo.", "/docs/diff"),
    ("🛡️", "Rules", "Nine core rules plus eight AI rules mapped to the OWASP LLM Top 10.", "/docs/rules"),
    ("🏦", "Meridian example", "A full multi-agent app, scanned end to end — the reference to follow.", "/docs/example"),
    ("🧬", "JSON schema", "The registry schema (1.1), additive-first, with reserved fields.", "/docs/schema"),
]


def landing_body() -> str:
    intro = (
        '<span class="hero-eyebrow">Stoa · Agent Risk Scanner</span>'
        '<h1 class="hero-h1">Every agent inventoried.<br>Every claim evidenced.</h1>'
        '<p class="hero-lede">A <strong>local-first static scanner</strong> that finds likely '
        'AI agents in Python, JavaScript, and TypeScript, maps what they can reach, scores them '
        'across eight risk dimensions, and blocks newly introduced high-confidence critical '
        'risks — <strong>without uploading a line of code</strong>.</p>'
        '<pre class="code hero-term"><code>'
        '<span class="p">$</span> pipx install stoa-agent-risk\n'
        '<span class="p">$</span> stoa scan .  <span class="d">&amp;&amp;</span>  open stoa-report.html</code></pre>'
        '<div class="chips">'
        '<span>Local-first</span><span>Zero telemetry</span><span>No accounts</span>'
        '<span>Python 3.10+</span><span>MIT</span></div>'
        '<div class="cards">'
    )
    for icon, title, desc, href in CARDS:
        intro += (
            f'<a class="card" href="{href}"><div class="card-ico">{icon}</div>'
            f'<div class="card-title">{html.escape(title)}</div>'
            f'<div class="card-desc">{html.escape(desc)}</div></a>'
        )
    intro += "</div>"
    intro += (
        '<style>'
        '.hero-eyebrow{font-family:"Plex Mono",monospace;font-size:12px;letter-spacing:.2em;'
        'text-transform:uppercase;color:var(--accent)}'
        '.hero-h1{font-family:Marcellus,Georgia,serif;font-weight:400;font-size:clamp(30px,4.4vw,44px);'
        'line-height:1.12;margin:12px 0 14px;border:none;padding:0}'
        '.hero-lede{font-size:16.5px;color:var(--mute);max-width:60ch;margin:0 0 18px}'
        '.hero-lede strong{color:var(--ink);font-weight:600}'
        '.hero-term{max-width:560px}.hero-term .p{color:#6fbfad}.hero-term .d{color:#7c8a84}'
        '.chips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 26px}'
        '.chips span{font-family:"Plex Mono",monospace;font-size:11.5px;color:var(--mute);'
        'border:1px solid var(--line);border-radius:999px;padding:3px 11px;background:var(--raise)}'
        '.chips span::before{content:"· ";color:var(--accent)}'
        '.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}'
        '@media(max-width:620px){.cards{grid-template-columns:1fr}}'
        '.card{display:block;background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:18px 20px}'
        '.card:hover{border-color:var(--accent);text-decoration:none}'
        '.card-ico{font-size:22px;margin-bottom:8px}'
        '.card-title{font-family:Marcellus,Georgia,serif;font-size:19px;color:var(--ink);margin-bottom:4px}'
        '.card-desc{color:var(--mute);font-size:13.5px}</style>'
    )
    return intro


# --- build all pages -------------------------------------------------------
PAGES = [
    ("", "Overview", landing_body, None, "Stoa documentation — local-first AI agent inventory and risk scanner."),
    ("getting-started", "Install & first scan", GETTING_STARTED, None, "Install Stoa and run your first scan."),
    ("dimensions", "Dimension exposure", read(REPO / "docs/dimensions.md"), None, "Stoa's eight-dimension risk taxonomy and scoring."),
    ("diff", "Capability drift", read(REPO / "docs/diff.md"), None, "stoa diff: detect and approve agent capability drift."),
    ("rules", "Rules overview", read(REPO / "docs/rules/README.md"), None, "Stoa's core and AI security rules."),
    ("cli", "CLI", CLI, None, "Stoa CLI reference."),
    ("configuration", "Configuration", CONFIGURATION, None, "stoa.toml, suppression, and .stoaignore."),
    ("schema", "JSON schema", read(REPO / "SCHEMA.md"), None, "The stoa-registry.json schema."),
    ("example", "Example: Meridian", meridian_body, None, "A worked multi-agent app (Meridian) scanned end to end by Stoa."),
]
for rule in ("AI001", "AI002", "AI003", "AI004", "AI005", "AI006", "AI007", "CTRL004"):
    PAGES.append((f"rules/{rule}", rule, read(REPO / f"docs/rules/{rule}.md"), None, f"Stoa rule {rule}."))


def _href(slug: str) -> str:
    return "/" if slug == "" else f"/docs/{slug}"


def main():
    # flat nav for prev/next, excluding absolute-link items (case study, report)
    flat = [(slug, label) for _, items in NAV for label, slug in items
            if not slug.startswith("/")]
    site_root = REPO / "site"
    for slug, title, content, _toc, desc in PAGES:
        if callable(content):
            body, toc = content(), []
        else:
            body, toc = md_to_html(content)
        pos = next((i for i, (s, _l) in enumerate(flat) if s == slug), None)
        if pos is not None:
            nav = '<div class="pagenav">'
            nav += (f'<a href="{_href(flat[pos-1][0])}">← {html.escape(flat[pos-1][1])}</a>'
                    if pos > 0 else "<span></span>")
            nav += (f'<a href="{_href(flat[pos+1][0])}">{html.escape(flat[pos+1][1])} →</a>'
                    if pos < len(flat) - 1 else "<span></span>")
            nav += "</div>"
            body += nav
        rendered = page(title, slug, body, toc, desc)
        if slug == "":
            # the unified landing at the site root, plus /docs for compatibility
            (site_root / "index.html").write_text(rendered, encoding="utf-8")
            DOCS_OUT.mkdir(parents=True, exist_ok=True)
            (DOCS_OUT / "index.html").write_text(rendered, encoding="utf-8")
        else:
            out_dir = DOCS_OUT / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.html").write_text(rendered, encoding="utf-8")
    print(f"generated {len(PAGES)} pages; landing at site root + {DOCS_OUT}")


if __name__ == "__main__":
    main()

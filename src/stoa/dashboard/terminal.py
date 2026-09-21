"""The scan at a glance, in the terminal.

Reads the same ``stoa-dashboard/1.0`` envelope the dashboard page reads, so
the two views always describe the same scan. It reports in the scanner's own
vocabulary (severities, per-dimension exposure, drift severity) and never
re-derives a number the dashboard computes for itself. Plain text, no colour,
no wall clock: identical inputs give identical output, safe to pipe or diff.
"""

from __future__ import annotations

from ..models import SEVERITIES

TOP_FINDINGS = 5
_EXPOSURE_ORDER = {"elevated": 0, "moderate": 1, "low": 2}


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _active_findings(registry: dict) -> list[dict]:
    """Unsuppressed findings, once each: agents in one file share its findings."""
    seen: set[str] = set()
    out: list[dict] = []
    agents = registry.get("agents") or []
    for finding in [f for a in agents for f in a.get("findings") or []] + (registry.get("repository_findings") or []):
        if finding.get("suppressed") or finding.get("fingerprint") in seen:
            continue
        seen.add(finding.get("fingerprint"))
        out.append(finding)
    return out


def _severity_line(counts: dict) -> str:
    parts = [f"{counts[s]} {s}" for s in reversed(SEVERITIES) if counts.get(s)]
    return ", ".join(parts) if parts else "none"


def _next_steps(envelope: dict) -> list[str]:
    """What the customer has not supplied yet, most useful first."""
    registry = envelope["registry"]
    agents = registry.get("agents") or []
    if not agents:
        return ["No agents were found. If you expected some, check include_extensions and "
                "ignore_paths in stoa.toml, and .stoaignore, then scan again."]
    steps = []
    if not any(a.get("declared") for a in agents):
        steps.append("Declare what each agent is meant to do, so Stoa can flag where the code "
                     "disagrees: stoa init declarations")
    if envelope.get("diff") is None:
        steps.append("Compare against a baseline to see what changed: "
                     "stoa scan . --diff-against origin/main")
    assessment = envelope.get("assessment") or {}
    if assessment.get("identity_source") == "sample":
        steps.append("Add your business context for the loss outlook and the insurance "
                     "assessment: stoa init underwriting")
    elif envelope.get("intake") is None:
        steps.append("Add an [intake] table to your underwriting config, so the loss outlook "
                     "uses your revenue, sector and records instead of placeholders.")
    return steps


def render_overview(envelope: dict, dashboard_path: str | None = None, *,
                    header: bool = True, next_steps: bool = True) -> str:
    """``header=False`` leaves out the counts `stoa scan` has already printed;
    ``next_steps=False`` suits CI logs, where the advice would repeat on every run."""
    registry = envelope["registry"]
    repository = registry.get("repository") or {}
    agents = registry.get("agents") or []
    summary = registry.get("summary") or {}
    lines: list[str] = []

    if header:
        ref = repository.get("git_ref")
        lines.append(f"{repository.get('name') or 'repository'}" + (f" @ {ref}" if ref else "")
                     + f"  ({_plural(summary.get('files_scanned', 0), 'file')} scanned)")
        # Unique agents, as the dashboard counts them; the records are what the scanner found.
        unique = envelope.get("unique_agents")
        if unique is not None and len(unique) != len(agents):
            lines.append(f"  Agents    {len(unique)}, from {_plural(len(agents), 'discovered record')}")
        else:
            high_confidence = sum(1 for a in agents if a.get("confidence") == "high")
            lines.append(f"  Agents    {len(agents)} ({high_confidence} high confidence)")
        lines.append(f"  Findings  {_severity_line(summary.get('findings') or {})}"
                     + (f"  ({summary['suppressed_findings']} suppressed)" if summary.get("suppressed_findings") else ""))

    diff = envelope.get("diff")
    if diff:
        s = diff.get("summary") or {}
        base = ((envelope.get("baseline") or {}).get("git_ref")) or "the baseline"
        changes = [_plural(s.get(f"agents_{k}", 0), f"agent {k}", f"agents {k}")
                   for k in ("added", "removed", "changed") if s.get(f"agents_{k}")]
        drift = ", ".join(changes) if changes else "no agents changed"
        unapproved = s.get("unapproved_max_drift_severity")
        if unapproved and unapproved != "none":
            drift += f"; unapproved drift up to {unapproved}"
        lines.append(f"  Drift     vs {base}: {drift}")

    dimensions = [d for d in (registry.get("dimension_summary") or {}).get("dimensions", [])
                  if d.get("max_exposure") in ("elevated", "moderate")]
    if dimensions:
        dimensions.sort(key=lambda d: (_EXPOSURE_ORDER[d["max_exposure"]], d.get("name", d["id"])))
        width = max(len(d.get("name", d["id"])) for d in dimensions)
        lines += ["", "Exposure above low"]
        for d in dimensions:
            affected = d.get("agents_elevated", 0) if d["max_exposure"] == "elevated" else d.get("agents_moderate", 0)
            lines.append(f"  {d.get('name', d['id']):<{width}}  {d['max_exposure']:<8}  {_plural(affected, 'agent')}")

    findings = _active_findings(registry)
    if findings:
        rank = {s: i for i, s in enumerate(reversed(SEVERITIES))}
        findings.sort(key=lambda f: (rank.get(f.get("severity"), 99), f.get("path", ""), f.get("line", 0), f.get("rule_id", "")))
        # One per rule first, like the dashboard's list, so a rule that fires
        # in every file does not crowd out the rest.
        shown, seen_rules = [], set()
        for f in findings:
            if f.get("rule_id") not in seen_rules and len(shown) < TOP_FINDINGS:
                seen_rules.add(f.get("rule_id"))
                shown.append(f)
        shown += [f for f in findings if f not in shown][:TOP_FINDINGS - len(shown)]
        shown.sort(key=findings.index)
        lines += ["", "Top findings" + (f" ({len(shown)} of {len(findings)})" if len(findings) > len(shown) else "")]
        for f in shown:
            lines.append(f"  {f.get('severity', ''):<8}  {f.get('rule_id', ''):<7}  {f.get('path', '')}:{f.get('line', 0)}")
            lines.append(f"            {f.get('title', '')}")

    steps = _next_steps(envelope) if next_steps else []
    if steps:
        lines += ["", "Next"]
        lines += [f"  - {step}" for step in steps]

    if dashboard_path:
        lines += ["", f"Dashboard: {dashboard_path}"]
    while lines and lines[0] == "":
        lines.pop(0)
    return "\n".join(lines) + "\n" if lines else ""

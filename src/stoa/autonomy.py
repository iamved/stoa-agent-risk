"""Autonomy inference (schema's reserved ``autonomy_level`` field, Assurance
layer Phase 2): classify each agent candidate on a four-level ladder from
signals the scanner already computes, plus one new proximity signal.

Deliberately reuses existing detectors instead of a second taint pass:

- An **AI002** finding with a side-effecting ``variant`` (``exec``, ``sql``,
  ``deserialize``, ``request``) means model output reaches a sink.
- An **AI003** finding means a high-impact capability was tool-bound with no
  approval construct observed — so its *absence*, combined with an
  ``APPROVAL_CONSTRUCT`` match, means approval *was* observed.
- **New**: a same-file "bounding" signal — a hardcoded numeric cap check or a
  rate-limiter construct (reusing ``CTRL003``'s pattern). Same-file, not
  line-adjacent — deliberately coarse, and documented as such.

Never guesses: when the signals don't cleanly resolve, the level is
``indeterminate`` with a stated reason. A false autonomy classification is
worse than an admitted gap — it's the trust-destroying failure mode the
whole assurance layer exists to avoid.
"""

from __future__ import annotations

import re

from .ai_rules import _line_of
from .models import AgentCandidate
from .rules import APPROVAL_CONSTRUCT, CONTROL_PATTERNS, HIGH_IMPACT_CAPABILITIES, TOOL_BINDING

AUTONOMY_LEVELS = (
    "recommend_only", "human_approved", "bounded_autonomous",
    "unrestricted_autonomous", "indeterminate",
)

_SIDE_EFFECTING_AI002_VARIANTS = {"exec", "sql", "deserialize", "request"}

BOUNDING_SIGNAL = re.compile(
    r"if\s+[\w.\[\]]+\s*[<>]=?\s*(?:MAX_\w+|\d+(?:\.\d+)?)\b|"  # if amount > MAX_X / > 500
    r"\bmin\s*\(\s*[\w.]+\s*,\s*(?:MAX_\w+|\d+(?:\.\d+)?)\s*\)"  # min(amount, MAX_X)
)


def _signal(kind: str, path: str, line: int) -> dict:
    return {"signal": kind, "path": path, "line": line}


def infer_autonomy(agent: AgentCandidate, content: str) -> dict:
    """Returns ``{"level", "signals", "reason"}``. ``reason`` is populated
    only when ``level == "indeterminate"``."""
    findings_by_rule: dict[str, list] = {}
    for f in agent.findings:
        if f.suppressed:
            continue
        findings_by_rule.setdefault(f.rule_id, []).append(f)

    ai002_sinks = [
        f for f in findings_by_rule.get("AI002", [])
        if (f.variant or "") in _SIDE_EFFECTING_AI002_VARIANTS
    ]
    ai003 = findings_by_rule.get("AI003", [])

    if not ai002_sinks:
        return {"level": "recommend_only", "signals": [], "reason": None}

    signals = [_signal(f.rule_id, f.path, f.line) for f in ai002_sinks]

    # AI003 fired => the scanner already concluded no approval construct was
    # observed for a high-impact capability. Only trust an approval match
    # when AI003 did *not* fire for this agent.
    approval_present = bool(APPROVAL_CONSTRUCT.search(content)) and not ai003
    if approval_present:
        return {
            "level": "human_approved",
            "signals": signals + [_signal("approval_construct", agent.path, ai002_sinks[0].line)],
            "reason": None,
        }

    bounding_match = BOUNDING_SIGNAL.search(content) or CONTROL_PATTERNS["CTRL003"].search(content)
    has_bounding = bounding_match is not None
    if has_bounding:
        return {
            "level": "bounded_autonomous",
            "signals": signals + [_signal("bounding", agent.path, _line_of(content, bounding_match.start()))],
            "reason": None,
        }

    high_impact = HIGH_IMPACT_CAPABILITIES.intersection(agent.capabilities)
    has_tool = bool(TOOL_BINDING.search(content))
    if ai003 or (has_tool and high_impact):
        extra = [_signal(f.rule_id, f.path, f.line) for f in ai003] or [
            _signal("high_impact_capability", agent.path, ai002_sinks[0].line)
        ]
        return {"level": "unrestricted_autonomous", "signals": signals + extra, "reason": None}

    return {
        "level": "indeterminate",
        "signals": signals,
        "reason": (
            "A side-effecting model-output sink was observed (AI002), but no "
            "high-impact capability, tool binding, approval construct, or "
            "bounding signal was found to place it confidently on the "
            "autonomy ladder."
        ),
    }

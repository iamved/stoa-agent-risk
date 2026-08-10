"""Declarative adapter loader.

Reads a template YAML (adapters/*.map.yaml) and resolves each field against a
submission document. Fields whose JSONPath begins with `$.systems[*]` are
expanded once per system. Every posture answer keeps its evidence quadruple
so the renderer can show value + evidence ref + confidence badge.

No carrier/business logic lives in code — only in the YAML maps. Adding a new
template means adding a new YAML file, nothing here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from jsonpath_ng.ext import parse as jsonpath_parse

from .models import Gap

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"

# confidence -> tristate display label
TRISTATE = {
    "confirmed": "Confirmed",
    "attested": "Confirmed (attested)",
    "not_confirmed": "Not confirmed",
    "contradicted": "Not confirmed",
    "unknown": "Unknown",
}


@dataclass
class ResolvedField:
    field_id: str
    section: str
    label: str
    render: str
    required: bool
    # resolved presentation
    display: str                       # human-facing string
    raw_value: Any = None              # underlying value
    evidence: list[str] = field(default_factory=list)
    confidence: Optional[str] = None   # None for non-evidenced fields
    scan_hash: Optional[str] = None
    resolved: bool = True
    warning: bool = False              # contradicted -> banner

    @property
    def system_scoped(self) -> bool:
        return self._system_id is not None

    _system_id: Optional[str] = None
    _system_name: Optional[str] = None


@dataclass
class Template:
    name: str
    title: str
    fields: list[dict[str, Any]]


def load_template(name: str) -> Template:
    path = ADAPTERS_DIR / f"{name}.map.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No adapter map for template '{name}' at {path}. "
            f"Add a YAML file to register a new template."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Template(name=data["template"], title=data["title"], fields=data["fields"])


def available_templates() -> list[str]:
    return sorted(p.stem.replace(".map", "") for p in ADAPTERS_DIR.glob("*.map.yaml"))


def _looks_evidenced(v: Any) -> bool:
    return isinstance(v, dict) and "confidence" in v and (
        "value" in v or "evidence" in v
    )


def _fmt_scalar(v: Any, render: str) -> str:
    if v is None:
        return "—"
    if render == "currency" and isinstance(v, (int, float)):
        return f"${v:,.0f}"
    if render == "checkbox":
        return "Yes" if v else "No"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "—"
    if isinstance(v, dict):
        # e.g. projections.next_2y {users, outputs, revenue_usd}
        return "; ".join(f"{k}: {val}" for k, val in v.items())
    return str(v)


def _present(spec: dict[str, Any], value: Any) -> tuple[str, Any, list[str], Optional[str], Optional[str], bool, bool]:
    """Return (display, raw, evidence, confidence, scan_hash, resolved, warning)."""
    render = spec["render"]

    if _looks_evidenced(value):
        conf = value.get("confidence", "unknown")
        raw = value.get("value")
        evidence = value.get("evidence", []) or []
        scan_hash = value.get("scan_hash")
        warning = conf == "contradicted"
        if render == "tristate":
            display = TRISTATE.get(conf, "Unknown")
        else:
            display = _fmt_scalar(raw, render)
            if conf == "unknown" and (raw is None or raw == [] or raw == ""):
                display = "Unknown"
        # An evidenced field is considered "resolved" for completeness if it
        # carries a definite posture (anything but unknown). Unknown == a gap
        # to close, mirroring "absence of evidence is unknown, never a no".
        resolved = conf != "unknown"
        return display, raw, evidence, conf, scan_hash, resolved, warning

    # plain (non-evidenced) value
    resolved = value is not None and value != [] and value != ""
    display = _fmt_scalar(value, render)
    return display, value, [], None, None, resolved, False


def resolve(template: Template, submission: dict[str, Any]) -> list[ResolvedField]:
    """Resolve every template field against the submission document."""
    systems = submission.get("systems", []) or []
    out: list[ResolvedField] = []

    for spec in template.fields:
        src = spec["source"]
        if src.startswith("$.systems[*]"):
            sub_path = "$" + src[len("$.systems[*]"):]
            expr = jsonpath_parse(sub_path)
            for sys in systems:
                matches = [m.value for m in expr.find(sys)]
                value = matches[0] if matches else None
                display, raw, ev, conf, sh, resolved, warn = _present(spec, value)
                out.append(
                    ResolvedField(
                        field_id=spec["field_id"],
                        section=spec["section"],
                        label=spec["label"],
                        render=spec["render"],
                        required=spec.get("required", False),
                        display=display,
                        raw_value=raw,
                        evidence=ev,
                        confidence=conf,
                        scan_hash=sh,
                        resolved=resolved,
                        warning=warn,
                        _system_id=sys.get("agent_id"),
                        _system_name=sys.get("display_name"),
                    )
                )
        else:
            expr = jsonpath_parse(src)
            matches = [m.value for m in expr.find(submission)]
            value = matches[0] if len(matches) == 1 else (matches if matches else None)
            display, raw, ev, conf, sh, resolved, warn = _present(spec, value)
            out.append(
                ResolvedField(
                    field_id=spec["field_id"],
                    section=spec["section"],
                    label=spec["label"],
                    render=spec["render"],
                    required=spec.get("required", False),
                    display=display,
                    raw_value=raw,
                    evidence=ev,
                    confidence=conf,
                    scan_hash=sh,
                    resolved=resolved,
                    warning=warn,
                )
            )
    return out


def completeness_gaps(template: Template, submission: dict[str, Any]) -> list[Gap]:
    """Every required field that does not resolve becomes a gap."""
    gaps: list[Gap] = []
    for rf in resolve(template, submission):
        if rf.required and not rf.resolved:
            fid = rf.field_id
            if rf.system_scoped:
                fid = f"{rf.field_id}[{rf._system_id}]"
            owner = "scan" if rf.confidence is not None else "human"
            gaps.append(
                Gap(
                    template=template.name,
                    field_id=fid,
                    description=f"Required field not resolved: {rf.label}",
                    owner=owner,
                )
            )
    return gaps

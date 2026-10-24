"""``stoa policy recommend``: a policy file from the registry and declarations.

Deterministic. Each emitted policy says why in ``recommended_because``
(rule ids, dimension tiers, declaration fields) and takes its numbers from
the declaration when there is one (``economic_authority.max_per_action``,
``daily_aggregate``) and from the pack's documented default otherwise. The
``gaps`` list names what the SDK cannot enforce yet or what is already
covered by a control observed in code, so the reader knows what to wire
elsewhere and what is optional.

Mapping:

- always: the ``baseline`` pack, scoped to every agent;
- payment capability or a money-moving tool: ``payments``, scoped to that
  agent and its money tools, thresholds from the declaration; when the
  declaration says ``human_approved`` the approval policy drops its
  threshold to zero (every movement);
- shell, code execution or filesystem write: ``exec``;
- declared ``data_classes`` with personal, financial or health, or any
  external integration: ``data``;
- an MCP client or server: ``tools-mcp``;
- regulated financial services in ``[business]``: ``fintech-regulated``
  replaces ``payments`` and ``data`` defaults.
"""

from __future__ import annotations

import copy

from .packs import load_pack
from .schema import POLICY_SCHEMA, PolicyDocument, PolicySpec

_EXEC_CAPS = {"shell_execution", "code_execution", "filesystem_write"}
_DATA_CLASSES = {"personal", "financial", "health"}
_SDK_ENFORCEABLE_ACTIONS = {"block", "escalate", "log", "allow", "mask"}


def _agent_name(agent: dict) -> str:
    return (agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name") or agent["id"]


def _amount(value) -> float | None:
    if isinstance(value, dict) and isinstance(value.get("amount"), (int, float)):
        return float(value["amount"])
    return None


def _clone(spec: PolicySpec, **changes) -> PolicySpec:
    out = copy.deepcopy(spec)
    for key, value in changes.items():
        setattr(out, key, value)
    return out


def recommend(registry: dict, *, mode: str = "observe") -> tuple[PolicyDocument, list[dict]]:
    """Returns ``(document, gaps)``."""
    agents = registry.get("agents") or []
    business = registry.get("business") or {}
    regulated_fintech = "financial_services" in (business.get("industries") or []) and bool(business.get("regulated_activities"))
    doc = PolicyDocument(version=POLICY_SCHEMA, mode=mode)
    gaps: list[dict] = []
    baseline = load_pack("baseline")
    payments = load_pack("fintech-regulated" if regulated_fintech else "payments")
    data = load_pack("data")
    exec_pack = load_pack("exec")
    mcp = load_pack("tools-mcp")

    for spec in baseline.policies:
        doc.policies.append(_clone(spec, recommended_because=["every agent"]))

    for agent in sorted(agents, key=lambda a: a["id"]):
        name = _agent_name(agent)
        agent_id = agent["id"]
        declared = agent.get("declared") or {}
        rules = {f.get("rule_id") for f in agent.get("findings") or []}
        caps = set(agent.get("capabilities") or [])
        tools = [t for t in agent.get("tools") or [] if isinstance(t, dict)]
        money_tools = [t["name"] for t in tools if t.get("money_action")]
        controls = {c for d in (agent.get("dimension_assessment") or {}).get("dimensions") or [] for c in d.get("controls_observed") or []}
        tiers = {d["id"]: d.get("exposure") for d in (agent.get("dimension_assessment") or {}).get("dimensions") or []}
        suffix = agent_id[:6].upper()

        moves_money = "payment_access" in caps or bool(money_tools)
        if moves_money:
            econ = declared.get("economic_authority") or {}
            per_action = _amount(econ.get("max_per_action"))
            daily = _amount(econ.get("daily_aggregate"))
            human = declared.get("autonomy_intent") in ("human_approved", "recommend_only")
            because = sorted(r for r in rules if r in ("AI003", "AI008", "DECL001", "DECL002", "DECL003", "RT001", "RT002", "RT007"))
            because = ["capability payment_access" if "payment_access" in caps else f"money tools {', '.join(money_tools)}", *because]
            if tiers.get("unreviewed-high-impact-action") in ("moderate", "elevated"):
                because.append(f"unreviewed-high-impact-action {tiers['unreviewed-high-impact-action']}")
            for spec in payments.policies:
                p = _clone(spec, id=f"{spec.id}-{suffix}", scope={"agent": name, **({"tool": money_tools[0]} if len(money_tools) == 1 else {})}, recommended_because=list(because))
                cond = copy.deepcopy(p.condition)
                if "POL-PAY-001" in spec.id or "POL-FIN-001" in spec.id:
                    threshold = 0.0 if human else (per_action if per_action is not None else 200.0)
                    if human:
                        p.condition = {"all": [{"expr": "side_effect == 'payment'"}, {"approval_missing": True}]}
                        p.title = "Approval on every money movement"
                        p.recommended_because.append(f"declared autonomy_intent {declared.get('autonomy_intent')}")
                    else:
                        p.condition = {"all": [{"amount_gt": threshold}, {"approval_missing": True}]}
                        p.recommended_because.append(f"threshold from economic_authority.max_per_action {per_action:g}" if per_action is not None else "threshold: pack default 200")
                elif "POL-PAY-002" in spec.id or "POL-FIN-002" in spec.id:
                    value = daily if daily is not None else cond["window_sum_gt"]["value"]
                    p.condition = {"window_sum_gt": {"field": "amount", "window": "24h", "value": value}}
                    p.recommended_because.append(f"aggregate from economic_authority.daily_aggregate {daily:g}" if daily is not None else f"aggregate: pack default {value:g}")
                elif "POL-PAY-003" in spec.id:
                    if per_action is None:
                        gaps.append({"agent": name, "policy": spec.id, "kind": "no_declared_limit", "message": "No economic_authority.max_per_action declared; the per-action limit uses the pack default of 500. Declare one in stoa-declared.toml."})
                    p.condition = {"amount_gt": per_action if per_action is not None else 500.0}
                    p.recommended_because.append(f"limit from economic_authority.max_per_action {per_action:g}" if per_action is not None else "limit: pack default 500")
                elif "POL-PAY-004" in spec.id:
                    p.recommended_because.append("AI008" if "AI008" in rules else "repeated money action on one order")
                    if "AI008" not in rules:
                        p.action = "log"
                doc.policies.append(p)
            if "approval" in controls:
                gaps.append({"agent": name, "policy": None, "kind": "control_observed", "message": "An approval control was detected in code; the approval policy records whether it fires and is optional as enforcement."})
        if caps & _EXEC_CAPS:
            for spec in exec_pack.policies:
                doc.policies.append(_clone(spec, id=f"{spec.id}-{suffix}", scope={"agent": name}, recommended_because=[f"capability {c}" for c in sorted(caps & _EXEC_CAPS)] + sorted(r for r in rules if r in ("CTRL006", "AI002"))))
        data_classes = set(declared.get("data_classes") or [])
        external = [i for i in agent.get("integrations") or [] if i not in ("aws", "gcp", "azure")]
        if data_classes & _DATA_CLASSES or external or "AI006" in rules:
            because = [f"declared data_classes {', '.join(sorted(data_classes & _DATA_CLASSES))}" if data_classes & _DATA_CLASSES else "", f"integrations {', '.join(sorted(external))}" if external else "", *sorted(r for r in rules if r in ("AI004", "AI006", "AI001"))]
            for spec in data.policies:
                if "POL-DATA-002" in spec.id and not external:
                    continue
                p = _clone(spec, id=f"{spec.id}-{suffix}", scope={"agent": name}, recommended_because=[b for b in because if b])
                if "POL-DATA-002" in spec.id:
                    p.condition = {"all": [{"expr": "side_effect == 'external_send'"}, {"field_not_in": {"field": "to_domain", "values": sorted(external)}}]}
                doc.policies.append(p)
            if any("output" == p.trigger for p in data.policies):
                gaps.append({"agent": name, "policy": "POL-DATA-001", "kind": "needs_output_hook", "message": "Output policies run only where the agent's final text passes through stoa_rt.output(); wire it, or the mask policy records nothing."})
        if "mcp_client" in caps or "mcp_server" in caps or "mcp" in (agent.get("frameworks") or []):
            for spec in mcp.policies:
                doc.policies.append(_clone(spec, id=f"{spec.id}-{suffix}", scope={"agent": name}, recommended_because=["MCP client or server detected"]))

    if regulated_fintech:
        doc.mode = mode
        gaps.append({"agent": None, "policy": None, "kind": "pack_choice", "message": "Regulated financial services declared in [business]: the fintech-regulated pack replaced the payments defaults (approval on every movement, tighter aggregate)."})
    doc.policies = _dedupe(doc.policies)
    return doc, gaps


def _dedupe(policies: list) -> list:
    seen: dict[str, PolicySpec] = {}
    for p in policies:
        if p.id in seen:
            continue
        seen[p.id] = p
    return list(seen.values())


def render_gaps(gaps: list[dict]) -> str:
    if not gaps:
        return "No gaps: every recommended policy is enforceable by the SDK.\n"
    lines = ["Gaps and notes:"]
    for g in gaps:
        who = f"{g['agent']}: " if g.get("agent") else ""
        lines.append(f"  - {who}{g['message']}")
    return "\n".join(lines) + "\n"

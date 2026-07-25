"""The assurance packet (`stoa export --assurance`, Assurance layer Phase 5).

Walks the 14 assurance areas and, for every row, emits exactly one status:
``scanned`` (rule id + file:line), ``declared`` (stoa-declared.toml key path
+ date if known), ``ingested`` (an `evidence.*` pointer), or
**``not_provided``** — explicit, never a silently missing key. An assurance
reviewer needs to see the gaps as much as the coverage.

Pure function over an already-built registry document (the same dict shape
written to stoa-registry.json / returned by report_json.build_document) —
mirrors graph_model.build_graph's shape: a single source of truth, no
separate re-parse of stoa-declared.toml at export time, since Phase 1-4
already merged declared+scanned+ingested data into the registry.

Deterministic: no wall-clock content anywhere except the header block, so
identical inputs produce a byte-identical packet body.
"""

from __future__ import annotations

PACKET_SCHEMA = "assurance-packet/1.0"

AREAS = (
    (1, "business_exposure", "Business exposure", "declared"),
    (2, "ai_inventory", "AI inventory", "scanned + declared"),
    (3, "autonomy", "Autonomy", "scanned (inferred) + declared (intent)"),
    (4, "permissions", "Permissions", "scanned"),
    (5, "economic_authority", "Economic authority", "declared + scanned (enforcement check)"),
    (6, "data_access", "Data access", "scanned + declared"),
    (7, "dependencies", "Dependencies", "scanned"),
    (8, "technical_controls", "Technical controls", "scanned"),
    (9, "testing", "Testing", "ingested"),
    (10, "monitoring", "Monitoring", "ingested (+ CTRL004 scanned)"),
    (11, "governance", "Governance", "declared + ingested"),
    (12, "contracts", "Contracts", "declared + ingested"),
    (13, "historical_evidence", "Historical evidence", "ingested"),
    (14, "claims_evidence", "Claims evidence", "ingested (reserved 'observed' provenance)"),
)

_MONEY_OR_CONTRACT_TAGS = {"move_funds", "approve_transactions", "sign_contracts"}


def _row(field: str, status: str, evidence: dict | None = None) -> dict:
    return {"field": field, "status": status, "evidence": evidence}


def _declared_row(field: str, declared: dict, key_prefix: str) -> dict:
    value = declared.get(field)
    if not value:
        return _row(field, "not_provided")
    return _row(field, "declared", {"path": "stoa-declared.toml", "key": f"{key_prefix}.{field}"})


def _agent_key_prefix(agent_id: str) -> str:
    return f'agents."{agent_id}"'


def _scanned_row(field: str, present: bool, path: str, line: int, rule_id: str | None = None) -> dict:
    if not present:
        return _row(field, "not_provided")
    evidence: dict = {"path": path, "line": line}
    if rule_id:
        evidence["rule_id"] = rule_id
    return _row(field, "scanned", evidence)


def _ingested_rows(evidence_block: dict, category: str) -> list[dict]:
    entries = (evidence_block or {}).get(category) or []
    if not entries:
        return [_row(category, "not_provided")]
    return [_row(category, "ingested", {"kind": e["kind"], "ref": e["ref"], "date": e.get("date")}) for e in entries]


def _agent_anchor(agent: dict) -> tuple[str, int]:
    evidence = agent.get("evidence") or []
    if evidence:
        return agent["path"], evidence[0]["line"]
    return agent["path"], 1


def _business_exposure(registry: dict) -> dict:
    business = registry.get("business") or {}
    rows = [
        _declared_row(f, business, "business") for f in
        ("industries", "regulated_activities", "max_customer_dependency")
    ]
    # Not captured by the declarations schema today -- explicit gaps, not omissions.
    rows += [_row(f, "not_provided") for f in ("revenue", "customers", "contract_sizes")]
    return {"rows": rows}


def _ai_inventory(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        declared = agent.get("declared") or {}
        path, line = _agent_anchor(agent)
        fields = {
            "model": _scanned_row("model", bool(agent.get("providers")), path, line)
            if agent.get("providers") else _row("model", "not_provided"),
            "agent": _row("agent", "scanned", {"path": path, "line": line}),
            "version": _row("version", "not_provided"),
            "owner": _declared_row("owner", declared, _agent_key_prefix(agent["id"])),
            "purpose": _declared_row("purpose", declared, _agent_key_prefix(agent["id"])),
            "users": _declared_row("users", declared, _agent_key_prefix(agent["id"])),
            "geography": _declared_row("geography", declared, _agent_key_prefix(agent["id"])),
            "production_status": _declared_row("production_status", declared, _agent_key_prefix(agent["id"])),
        }
        agents_out.append({"agent_id": agent["id"], "name": agent["name"], "fields": fields})
    return {"agents": agents_out}


def _autonomy(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        declared = agent.get("declared") or {}
        autonomy = agent.get("autonomy_level") or {}
        signals = autonomy.get("signals") or []
        scanned = _row(
            "inferred_level", "scanned",
            {"value": autonomy.get("level"), "signals": signals},
        ) if autonomy else _row("inferred_level", "not_provided")
        agents_out.append({
            "agent_id": agent["id"], "name": agent["name"],
            "fields": {
                "inferred_level": scanned,
                "declared_intent": _declared_row("autonomy_intent", declared, _agent_key_prefix(agent["id"])),
            },
        })
    return {"agents": agents_out}


def _permissions(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        path, line = _agent_anchor(agent)
        tags = agent.get("permission_tags") or []
        caps = agent.get("capabilities") or []
        all_perms = sorted(set(tags) | set(caps))
        agents_out.append({
            "agent_id": agent["id"], "name": agent["name"],
            "fields": {
                "permissions": _row("permissions", "scanned", {"path": path, "line": line, "value": all_perms})
                if all_perms else _row("permissions", "not_provided"),
            },
        })
    return {"agents": agents_out}


def _economic_authority(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        declared = agent.get("declared") or {}
        econ = declared.get("economic_authority")
        has_money = bool(_MONEY_OR_CONTRACT_TAGS & set(agent.get("permission_tags") or []))
        if econ:
            row = _row(
                "economic_authority", "declared",
                {"path": "stoa-declared.toml", "key": f'{_agent_key_prefix(agent["id"])}.economic_authority'},
            )
        elif has_money:
            row = _row("economic_authority", "not_provided")
        else:
            continue  # not a money-moving agent; this area doesn't apply
        agents_out.append({"agent_id": agent["id"], "name": agent["name"], "fields": {"economic_authority": row}})
    return {"agents": agents_out}


def _data_access(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        declared = agent.get("declared") or {}
        findings = agent.get("findings") or []
        has_secret = any(f["rule_id"] in ("SEC001", "SEC002") for f in findings)
        agents_out.append({
            "agent_id": agent["id"], "name": agent["name"],
            "fields": {
                "declared_data_classes": _declared_row("data_classes", declared, _agent_key_prefix(agent["id"])),
                "scanned_authentication_evidence": _row(
                    "scanned_authentication_evidence", "scanned",
                    {"path": next(f["path"] for f in findings if f["rule_id"] in ("SEC001", "SEC002")),
                     "line": next(f["line"] for f in findings if f["rule_id"] in ("SEC001", "SEC002"))},
                ) if has_secret else _row("scanned_authentication_evidence", "not_provided"),
            },
        })
    return {"agents": agents_out}


def _dependencies(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        path, line = _agent_anchor(agent)
        deps = {
            "foundation_models": sorted(agent.get("providers") or []),
            "external_tools_and_apis": sorted(agent.get("integrations") or []),
        }
        fields = {
            name: (_row(name, "scanned", {"path": path, "line": line, "value": value})
                   if value else _row(name, "not_provided"))
            for name, value in deps.items()
        }
        agents_out.append({"agent_id": agent["id"], "name": agent["name"], "fields": fields})
    return {"agents": agents_out}


_CONTROL_RULE_KEY = {
    "CTRL001": "authentication", "CTRL002": "input_validation", "CTRL003": "rate_limits",
    "CTRL004": "observability", "CTRL005": "loop_rate_limiting", "CTRL006": "sandboxing",
    "CTRL007": "kill_switch",
}


def _technical_controls(registry: dict) -> dict:
    agents_out = []
    for agent in registry.get("agents", []):
        findings = agent.get("findings") or []
        gaps = {f["rule_id"] for f in findings if f["rule_id"] in _CONTROL_RULE_KEY}
        fields = {}
        for rule_id, key in _CONTROL_RULE_KEY.items():
            if rule_id in gaps:
                gap = next(f for f in findings if f["rule_id"] == rule_id)
                fields[key] = _row(key, "not_provided", {"gap_rule_id": rule_id, "path": gap["path"], "line": gap["line"]})
            else:
                fields[key] = _row(key, "scanned", {"note": "no gap finding for this control"})
        agents_out.append({"agent_id": agent["id"], "name": agent["name"], "fields": fields})
    return {"agents": agents_out}


def _monitoring(registry: dict) -> dict:
    evidence_block = registry.get("evidence") or {}
    rows = _ingested_rows(evidence_block, "monitoring")
    agents_out = []
    for agent in registry.get("agents", []):
        findings = agent.get("findings") or []
        ctrl004 = next((f for f in findings if f["rule_id"] == "CTRL004"), None)
        row = (
            _row("observability", "not_provided", {"gap_rule_id": "CTRL004", "path": ctrl004["path"], "line": ctrl004["line"]})
            if ctrl004 else _row("observability", "scanned")
        )
        agents_out.append({"agent_id": agent["id"], "name": agent["name"], "fields": {"observability": row}})
    return {"rows": rows, "agents": agents_out}


def _testing(registry: dict) -> dict:
    return {"rows": _ingested_rows(registry.get("evidence") or {}, "testing")}


def _governance(registry: dict) -> dict:
    governance = registry.get("governance") or {}
    rows = [
        _row(f, "declared", {"path": "stoa-declared.toml", "key": f"governance.{f}"})
        if governance.get(f) else _row(f, "not_provided")
        for f in ("release_approval", "incident_response", "risk_acceptance")
    ]
    return {"rows": rows}


def _contracts(registry: dict) -> dict:
    return {"rows": _ingested_rows(registry.get("evidence") or {}, "contracts")}


def _historical_evidence(registry: dict) -> dict:
    return {"rows": _ingested_rows(registry.get("evidence") or {}, "historical")}


def _claims_evidence(registry: dict) -> dict:
    # "observed" provenance is reserved (see graph_model / SCHEMA.md) for a
    # future runtime-trace overlay -- never emitted by the current scanner.
    return {"rows": [_row("traces_and_runtime_evidence", "not_provided",
                           {"note": "reserved for a future runtime-trace overlay ('observed' provenance)"})]}


_AREA_BUILDERS = {
    "business_exposure": _business_exposure,
    "ai_inventory": _ai_inventory,
    "autonomy": _autonomy,
    "permissions": _permissions,
    "economic_authority": _economic_authority,
    "data_access": _data_access,
    "dependencies": _dependencies,
    "technical_controls": _technical_controls,
    "testing": _testing,
    "monitoring": _monitoring,
    "governance": _governance,
    "contracts": _contracts,
    "historical_evidence": _historical_evidence,
    "claims_evidence": _claims_evidence,
}


def _contradictions(registry: dict) -> list[dict]:
    all_findings = (
        [f for a in registry.get("agents", []) for f in a.get("findings") or []]
        + (registry.get("repository_findings") or [])
    )
    decl = [f for f in all_findings if f["rule_id"].startswith("DECL") and not f.get("suppressed")]
    return sorted(
        [
            {
                "rule_id": f["rule_id"], "severity": f["severity"], "title": f["title"],
                "path": f["path"], "line": f["line"], "declared_ref": f.get("declared_ref"),
                "message": f.get("message"),
            }
            for f in decl
        ],
        key=lambda f: (f["rule_id"], f["path"], f["line"]),
    )


def build_assurance_packet(registry: dict, *, git_sha: str | None = None, scan_timestamp: str | None = None) -> dict:
    """Build the assurance packet from a registry document. Pure function,
    no I/O, deterministic apart from the header block (the only place
    ``git_sha``/``scan_timestamp`` — both caller-supplied, never wall-clock
    read internally — may appear)."""
    contradictions = _contradictions(registry)
    findings_summary = (registry.get("summary") or {}).get("findings") or {}
    areas = {}
    for _, key, name, layers in AREAS:
        areas[key] = {"area_name": name, "layers": layers, **_AREA_BUILDERS[key](registry)}

    return {
        "schema": PACKET_SCHEMA,
        "header": {
            "repository": (registry.get("repository") or {}).get("name"),
            "git_sha": git_sha,
            "scan_timestamp": scan_timestamp,
            "stoa_version": (registry.get("tool") or {}).get("version"),
            "registry_schema_version": registry.get("schema_version"),
            "agent_count": len(registry.get("agents") or []),
            "findings_by_severity": findings_summary,
            "contradiction_count": len(contradictions),
        },
        "contradictions": contradictions,
        "areas": areas,
    }


_STATUS_GLYPH = {"scanned": "🔍", "declared": "📝", "ingested": "📎", "not_provided": "⬜"}


def _evidence_cell(evidence: dict | None) -> str:
    if not evidence:
        return "—"
    if "path" in evidence and "line" in evidence:
        cell = f"`{evidence['path']}:{evidence['line']}`"
        if evidence.get("rule_id"):
            cell = f"{evidence['rule_id']} " + cell
        return cell
    if "key" in evidence:
        return f"`{evidence['key']}`"
    if "ref" in evidence:
        return f"{evidence.get('kind', '')} → `{evidence['ref']}`"
    if "gap_rule_id" in evidence:
        return f"gap: {evidence['gap_rule_id']} `{evidence['path']}:{evidence['line']}`"
    return "—"


def _fields_table(fields: dict) -> list[str]:
    lines = ["| Field | Status | Evidence |", "|---|---|---|"]
    for name, row in fields.items():
        glyph = _STATUS_GLYPH.get(row["status"], "")
        lines.append(f"| {row['field']} | {glyph} {row['status']} | {_evidence_cell(row['evidence'])} |")
    return lines


def render_assurance_markdown(packet: dict) -> str:
    """Human/reviewer-readable Markdown, table-based — mirrors
    registry_diff.render_changelog's style (plain GFM tables, `##`/`###`
    headers, no external CSS)."""
    h = packet["header"]
    lines = [
        f"## Stoa · Assurance Packet — {h['repository'] or '(unknown repository)'}",
        "",
        f"`{h['git_sha'] or 'no git SHA'}` · scanned {h['scan_timestamp'] or '(no timestamp given)'} · "
        f"Stoa `{h['stoa_version']}` · registry schema `{h['registry_schema_version']}` · "
        f"{h['agent_count']} agent(s) · {h['contradiction_count']} contradiction(s)",
        "",
    ]

    severities = h.get("findings_by_severity") or {}
    if severities:
        counts = ", ".join(f"{n} {sev}" for sev, n in severities.items() if n)
        lines += [f"Findings: {counts or 'none'}", ""]

    contradictions = packet["contradictions"]
    lines.append(f"### ⚠️ Contradictions ({len(contradictions)})")
    lines.append("")
    if not contradictions:
        lines.append("None found.")
    else:
        lines += ["| Rule | Severity | Title | Code | Declared |", "|---|---|---|---|---|"]
        for c in contradictions:
            declared_cell = f"`{c['declared_ref']['key']}`" if c.get("declared_ref") else "—"
            lines.append(
                f"| {c['rule_id']} | {c['severity']} | {c['title']} | "
                f"`{c['path']}:{c['line']}` | {declared_cell} |"
            )
    lines.append("")

    for area_num, key, name, layers in AREAS:
        area = packet["areas"][key]
        lines.append(f"### Area {area_num} — {name} ({layers})")
        lines.append("")
        if "rows" in area:
            lines += _fields_table({r["field"]: r for r in area["rows"]})
            lines.append("")
        if "agents" in area:
            if not area["agents"]:
                lines.append("_No agents apply to this area._")
                lines.append("")
            for a in area["agents"]:
                lines.append(f"**{a['name']}** (`{a['agent_id']}`)")
                lines.append("")
                lines += _fields_table(a["fields"])
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"

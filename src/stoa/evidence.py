"""Evidence levels: how a fact about an agent was established.

Every finding and every capability carries ``evidence_level``, one of:

- ``declared``   written by a person in ``stoa-declared.toml`` (DECL rules
                 compare it with the code);
- ``static``     read from application code by the scanner;
- ``reachable``  read from infrastructure (IAM, grants, Terraform): what the
                 deployment lets the agent reach, whether or not the code
                 uses it;
- ``observed``   seen in runtime traces (RT rules, the runtime overlay);
- ``tested``     exercised by a policy test (``stoa policy test``).

A post-pass over the registry document, additive, deterministic. The
passport and the dashboard's evidence filter read these fields.
"""

from __future__ import annotations

LEVELS = ("declared", "static", "reachable", "observed", "tested")


def finding_level(finding: dict, agent: dict | None) -> str:
    rule = str(finding.get("rule_id", ""))
    if rule.startswith("RT"):
        return "observed"
    if rule.startswith("DECL"):
        return "declared"
    if agent is not None and agent.get("source") == "iac":
        return "reachable"
    return "static"


def annotate_evidence_levels(document: dict) -> None:
    """Stamp ``evidence_level`` on findings and ``capability_evidence`` on agents, in place."""
    for agent in document.get("agents") or []:
        for finding in agent.get("findings") or []:
            finding["evidence_level"] = finding_level(finding, agent)
        base = "reachable" if agent.get("source") == "iac" else "static"
        evidence = {cap: base for cap in agent.get("capabilities") or []}
        observed = (agent.get("runtime_evidence") or {}).get("observed_capabilities") or []
        for cap in observed:
            evidence[cap] = "observed"
        agent["capability_evidence"] = dict(sorted(evidence.items()))
    for finding in document.get("repository_findings") or []:
        finding["evidence_level"] = finding_level(finding, None)


def evidence_mix(agent: dict) -> dict[str, int]:
    """How many facts about the agent sit at each level: findings plus capabilities."""
    mix = {level: 0 for level in LEVELS}
    for finding in agent.get("findings") or []:
        level = finding.get("evidence_level") or finding_level(finding, agent)
        mix[level] = mix.get(level, 0) + 1
    for level in (agent.get("capability_evidence") or {}).values():
        mix[level] = mix.get(level, 0) + 1
    if agent.get("declared"):
        mix["declared"] += 1
    if (agent.get("policy_test") or {}).get("scenarios"):
        mix["tested"] += int(agent["policy_test"]["scenarios"])
    return mix

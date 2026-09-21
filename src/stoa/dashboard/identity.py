"""Which scanned records are the same agent.

The scanner reports one record per place it finds an agent: a graph in
application code, a Bedrock agent in Terraform, a serving endpoint. One
deployed agent is often two or three of those, so counting records overstates
how many agents there are. This groups records into unique agents for the
dashboard. It changes no record, rule, score or finding.

Matching, in order:

1. **Declared.** ``same_as`` on a declared agent names the other record ids.
   Only a person can know that two endpoints serve one agent.
2. **Name.** A code record and an infrastructure record whose normalized
   names agree. Deliberately narrow, because a false merge hides an agent:
   it never pairs two records of the same kind, ignores generic names, and
   pairs nothing when a name is ambiguous on either side.

Everything else stays its own agent. Deterministic: same registry, same result.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Trailing words that say "this is an agent" rather than which one.
_SUFFIXES = {"agent", "agents", "graph", "bot", "assistant"}
# Names too generic to identify anything.
_GENERIC = {"", "agent", "graph", "main", "app", "index", "bot", "assistant", "handler", "server", "api"}

_PLATFORM_LABEL = {"bedrock": "AWS", "sagemaker": "AWS", "databricks": "Databricks",
                   "vertex": "Google Cloud", "azure": "Azure"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def normalize(name: str, project: str | None = None) -> str:
    """``meridian-account-actions`` and ``account_actions_agent·graph`` both
    become ``account_actions``: lowercase, ``-`` and ``_`` alike, the project
    prefix and the agent-ish suffixes dropped."""
    tokens = _tokens(name)
    if project and len(tokens) > 1 and tokens[0] == project:
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens = tokens[:-1]
    return "_".join(tokens)


def _project_prefix(registry: dict, agents: list[dict]) -> str | None:
    """The leading word shared by the repository and its infrastructure names."""
    repo = _tokens((registry.get("repository") or {}).get("name") or "")
    if repo:
        return repo[0]
    firsts = {(_tokens(a.get("name") or "") or [""])[0] for a in agents if a.get("source") == "iac"}
    return firsts.pop() if len(firsts) == 1 and len(agents) > 1 else None


def _kind(agent: dict) -> str:
    return "infrastructure" if agent.get("source") == "iac" else "code"


def _keys(agent: dict, project: str | None) -> set[str]:
    """Every normalized name this record could go by."""
    names = [
        (agent.get("declared") or {}).get("name") or "",
        agent.get("name") or "",
        (agent.get("display_name") or "").split("·")[0],
        (agent.get("symbol") or "").rsplit(".", 1)[-1],
    ]
    if _kind(agent) == "code":
        names.append(PurePosixPath(agent.get("path") or "").stem)
    return {key for key in (normalize(n, project) for n in names) if key not in _GENERIC}


def _record(agent: dict) -> dict:
    kind = _kind(agent)
    platform = agent.get("platform")
    return {
        "agent_id": agent["id"],
        "kind": kind,
        "platform": platform,
        "label": (f"Deployed on {_PLATFORM_LABEL.get(platform, platform)}" if platform else "Defined in infrastructure")
                 if kind == "infrastructure" else "Defined in code",
        "path": agent.get("path"),
        "symbol": agent.get("symbol"),
    }


def _display_name(records: list[dict]) -> str:
    """A declared name if there is one, else the infrastructure name (it is
    the one people deploy and page), else the code name."""
    for agent in records:
        declared = (agent.get("declared") or {}).get("name")
        if declared:
            return declared
    ordered = sorted(records, key=lambda a: (_kind(a) != "infrastructure", a.get("path") or "", a["id"]))
    first = ordered[0]
    return first.get("display_name") or first.get("name") or first["id"]


def resolve_agents(registry: dict) -> list[dict]:
    agents = list(registry.get("agents") or [])
    by_id = {a["id"]: a for a in agents}
    parent = {a["id"]: a["id"] for a in agents}
    reason: dict[frozenset, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str, why: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
        reason.setdefault(frozenset((a, b)), why)

    # 1. Declared links. Ids that are not in this scan are ignored.
    for agent in agents:
        for other in (agent.get("declared") or {}).get("same_as") or []:
            if other in by_id and other != agent["id"]:
                union(agent["id"], other, "declared")

    # 2. Names: one code record with one infrastructure record per key.
    project = _project_prefix(registry, agents)
    by_key: dict[str, dict[str, list[str]]] = {}
    for agent in agents:
        for key in _keys(agent, project):
            by_key.setdefault(key, {"code": [], "infrastructure": []})[_kind(agent)].append(agent["id"])
    for key in sorted(by_key):
        sides = by_key[key]
        if len(sides["code"]) == 1 and len(sides["infrastructure"]) == 1:
            union(sides["code"][0], sides["infrastructure"][0], "name")

    groups: dict[str, list[dict]] = {}
    for agent in agents:
        groups.setdefault(find(agent["id"]), []).append(agent)

    out = []
    for root in sorted(groups, key=lambda r: (_display_name(groups[r]).lower(), r)):
        records = sorted(groups[root], key=lambda a: (_kind(a) != "code", a.get("path") or "", a["id"]))
        ids = {a["id"] for a in records}
        links = {why for pair, why in reason.items() if pair <= ids}
        out.append({
            "id": root,
            "name": _display_name(records),
            "records": [_record(a) for a in records],
            # How the records were joined: "declared" wins, since a person said so.
            "linked_by": "declared" if "declared" in links else "name" if links else None,
        })
    return out

"""The SDK's link to the last scan: ``stoa-registry.json``.

Found by searching upward from the working directory (or given to
``configure(registry_path=...)``). From it the SDK takes, per agent, the
declared tool names and the declared per-action limit, so flags such as
``undeclared_tool`` and ``over_declared_limit`` can be computed at write
time without the analysis step. Loading is fail-open: no registry means no
registry-backed flags and one ``no_registry`` flag on the first span.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_NAME = "stoa-registry.json"


@dataclass
class AgentFacts:
    agent_id: str
    name: str
    tools: frozenset = frozenset()
    money_tools: frozenset = frozenset()
    max_per_action: dict | None = None  # {"amount": float, "currency": str}


@dataclass
class RegistryFacts:
    path: str | None = None
    registry_hash: str | None = None
    agents: dict = field(default_factory=dict)  # agent_id -> AgentFacts
    by_name: dict = field(default_factory=dict)  # name/symbol -> agent_id

    @property
    def found(self) -> bool:
        return self.path is not None

    def for_agent(self, agent_id: str | None) -> AgentFacts | None:
        if not agent_id:
            return None
        return self.agents.get(agent_id) or self.agents.get(self.by_name.get(agent_id, ""))


def find_registry(start: str | Path | None = None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / REGISTRY_NAME
        if candidate.is_file():
            return candidate
    return None


def load_registry_facts(path: str | Path | None = None) -> RegistryFacts:
    """Never raises: a missing or unreadable registry gives empty facts."""
    try:
        resolved = Path(path) if path else find_registry()
        if resolved is None or not resolved.is_file():
            return RegistryFacts()
        raw = resolved.read_bytes()
        document = json.loads(raw)
        facts = RegistryFacts(path=str(resolved), registry_hash=hashlib.sha256(raw).hexdigest()[:16])
        for agent in document.get("agents") or []:
            tools = [t for t in agent.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            econ = (agent.get("declared") or {}).get("economic_authority") or {}
            per_action = econ.get("max_per_action")
            limit = (
                {"amount": float(per_action["amount"]), "currency": str(per_action.get("currency") or "USD")}
                if isinstance(per_action, dict) and isinstance(per_action.get("amount"), (int, float))
                else None
            )
            entry = AgentFacts(
                agent_id=agent["id"],
                name=(agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name") or agent["id"],
                tools=frozenset(t["name"] for t in tools),
                money_tools=frozenset(t["name"] for t in tools if t.get("money_action")),
                max_per_action=limit,
            )
            facts.agents[agent["id"]] = entry
            for alias in (entry.name, agent.get("name"), agent.get("symbol"), agent.get("display_name")):
                if alias:
                    facts.by_name.setdefault(alias, agent["id"])
        return facts
    except Exception:  # noqa: BLE001 - fail-open
        return RegistryFacts()

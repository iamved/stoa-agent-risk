"""Per-event risk flags, computed by the SDK as each span is recorded.

A flag is a short name in ``attrs.flags`` that a reader can act on without
re-deriving it: ``stoa runtime analyze`` counts them, ``drift`` compares
them, and alerting (later) triggers on them. Everything here is computed
from a bounded in-memory window per agent (the last ``window_size`` spans
or seven days, whichever is smaller) plus the registry facts loaded at
``configure`` time. No I/O, no network, no exceptions out.

Flags and when they fire:

- ``no_registry``         first span of the process when no
                          ``stoa-registry.json`` was found
- ``undeclared_tool``     an ``action``/``tool_call`` names a tool the
                          registry does not list for this agent
- ``over_declared_limit`` the span's ``amount`` exceeds the agent's declared
                          ``max_per_action`` in the same currency
- ``approval_bypassed``   a payment, delete or external_send action with no
                          approval span earlier in the same trace
- ``new_counterparty``    first time a value is seen in a field the guard
                          tagged as ``counterparty_field`` (by hash)
- ``burst``               more than ``burst_threshold`` actions on the same
                          tool within 60 seconds
- ``repeat_failure``      three consecutive errors on the same tool
- ``model_changed``       an ``llm_call`` model differs from the previous
                          session's model for this agent
- ``integration_changed`` an action's integration not seen in the previous
                          session for this agent
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from .registry import RegistryFacts

FLAG_NAMES = (
    "no_registry", "undeclared_tool", "over_declared_limit", "approval_bypassed",
    "new_counterparty", "burst", "repeat_failure", "model_changed", "integration_changed",
)
_BYPASS_SIDE_EFFECTS = ("payment", "delete", "external_send")
_SEVEN_DAYS = timedelta(days=7)


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class _AgentWindow:
    __slots__ = (
        "recent", "approved_traces", "counterparties", "tool_times", "tool_failures",
        "session_models", "session_integrations", "last_session_models",
        "last_session_integrations", "current_session",
    )

    def __init__(self) -> None:
        self.recent: deque = deque()
        self.approved_traces: set[str] = set()
        self.counterparties: set[str] = set()
        self.tool_times: dict[str, deque] = {}
        self.tool_failures: dict[str, int] = {}
        self.session_models: set[str] = set()
        self.session_integrations: set[str] = set()
        self.last_session_models: set[str] | None = None
        self.last_session_integrations: set[str] | None = None
        self.current_session: str | None = None


class FlagEngine:
    def __init__(self, facts: RegistryFacts | None = None, *, window_size: int = 1000, burst_threshold: int = 20) -> None:
        self.facts = facts or RegistryFacts()
        self.window_size = window_size
        self.burst_threshold = burst_threshold
        self._agents: dict[str, _AgentWindow] = {}
        self._registry_flagged = False

    def _window(self, agent_id: str) -> _AgentWindow:
        window = self._agents.get(agent_id)
        if window is None:
            window = self._agents[agent_id] = _AgentWindow()
        return window

    def _trim(self, window: _AgentWindow, now: datetime | None) -> None:
        while len(window.recent) > self.window_size:
            window.recent.popleft()
        if now is not None:
            while window.recent and (now - window.recent[0]) > _SEVEN_DAYS:
                window.recent.popleft()

    def compute(self, span: dict, *, counterparty: str | None = None) -> list[str]:
        """Flags for ``span`` (a built 1.1 record, before it is emitted).
        Deterministic for a given sequence of spans; never raises."""
        try:
            return self._compute(span, counterparty)
        except Exception:  # noqa: BLE001
            return []

    def _compute(self, span: dict, counterparty: str | None) -> list[str]:
        flags: list[str] = []
        agent_id = span.get("agent_id") or "?"
        window = self._window(agent_id)
        kind = span.get("kind")
        attrs = span.get("attrs") or {}
        now = _parse_ts(span.get("end_ts")) or _parse_ts(span.get("start_ts"))
        if now is not None:
            window.recent.append(now)
            self._trim(window, now)

        if not self.facts.found and not self._registry_flagged:
            self._registry_flagged = True
            flags.append("no_registry")
        facts = self.facts.for_agent(span.get("agent_id"))

        session_id = span.get("session_id")
        if session_id != window.current_session:
            if window.current_session is not None:
                window.last_session_models = set(window.session_models)
                window.last_session_integrations = set(window.session_integrations)
            window.current_session = session_id
            window.session_models = set()
            window.session_integrations = set()

        if kind == "approval" and span.get("trace_id"):
            window.approved_traces.add(span["trace_id"])

        if kind == "llm_call" and span.get("model"):
            model = span["model"]
            window.session_models.add(model)
            if window.last_session_models and model not in window.last_session_models:
                flags.append("model_changed")

        if kind in ("action", "tool_call"):
            tool = span.get("tool")
            if tool and facts is not None and facts.tools and tool not in facts.tools:
                flags.append("undeclared_tool")
            amount = span.get("amount") or {}
            limit = facts.max_per_action if facts else None
            if (
                limit and isinstance(amount.get("amount"), (int, float))
                and amount.get("currency", "USD") == limit["currency"]
                and amount["amount"] > limit["amount"]
            ):
                flags.append("over_declared_limit")
            side_effect = attrs.get("side_effect")
            money = side_effect == "payment" or (facts is not None and tool in facts.money_tools) or isinstance(amount.get("amount"), (int, float))
            if (side_effect in _BYPASS_SIDE_EFFECTS or money) and not span.get("approval_span_id"):
                if span.get("trace_id") not in window.approved_traces:
                    flags.append("approval_bypassed")
            if counterparty is not None:
                if counterparty in window.counterparties:
                    pass
                else:
                    window.counterparties.add(counterparty)
                    if len(window.counterparties) > 1:
                        flags.append("new_counterparty")
            integration = span.get("integration")
            if integration:
                window.session_integrations.add(integration)
                if window.last_session_integrations and integration not in window.last_session_integrations:
                    flags.append("integration_changed")
            if tool and now is not None:
                times = window.tool_times.setdefault(tool, deque())
                times.append(now)
                while times and (now - times[0]).total_seconds() > 60:
                    times.popleft()
                if len(times) > self.burst_threshold:
                    flags.append("burst")
            if tool:
                if span.get("status") == "error":
                    window.tool_failures[tool] = window.tool_failures.get(tool, 0) + 1
                    if window.tool_failures[tool] == 3:
                        flags.append("repeat_failure")
                else:
                    window.tool_failures[tool] = 0
        return flags

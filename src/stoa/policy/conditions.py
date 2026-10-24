"""Evaluating a policy's structured condition against one call.

The call is a flat namespace (the same one the runtime's expression rules
see): ``tool``, ``args`` (captured fields in clear, the rest hashed),
``side_effect``, ``amount``, ``approval``, ``agent``, ``session``, plus
``text`` for input/output triggers. Stateful conditions read a
``WindowStore``: a small JSON file beside the traces holding the recent
numeric observations per agent, tool and field, pruned to the longest
window any policy asks for. Nothing here raises; an unevaluable condition
reports ``error`` and the policy records it.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .killswitch import KillSwitch
from .schema import WINDOW_RE

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_window(text: str) -> timedelta:
    match = WINDOW_RE.match(text or "")
    if not match:
        return timedelta(hours=24)
    return timedelta(seconds=int(match.group(1)) * _UNIT_SECONDS[match.group(2)])


class WindowStore:
    """Recent observations for ``window_sum_gt`` / ``window_count_gt``.

    One JSON file: ``{"events": [[ts, agent, tool, field, value], ...]}``.
    Observations are added after a decision, so a call never counts itself.
    Writes are best-effort; a store that cannot be written keeps working in
    memory for the life of the process.
    """

    def __init__(self, path: str | Path | None, *, keep: timedelta = timedelta(days=7)) -> None:
        self.path = Path(path) if path else None
        self.keep = keep
        self._events: list[list] = []
        self._lock = threading.Lock()
        if self.path and self.path.is_file():
            try:
                self._events = list(json.loads(self.path.read_text(encoding="utf-8")).get("events") or [])
            except (OSError, ValueError):
                self._events = []

    def observe(self, ts: datetime, agent: str, tool: str, fields: dict) -> None:
        with self._lock:
            for name, value in fields.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                self._events.append([ts.isoformat(), agent, tool, name, float(value)])
            self._events.append([ts.isoformat(), agent, tool, "", 1.0])  # the call itself, for counts
            cutoff = (ts - self.keep).isoformat()
            self._events = [e for e in self._events if e[0] >= cutoff]
            self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"events": self._events}, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass

    def window_sum(self, now: datetime, agent: str, tool: str | None, field: str, window: timedelta) -> float:
        since = (now - window).isoformat()
        with self._lock:
            return sum(e[4] for e in self._events if e[0] >= since and e[1] == agent and (tool is None or e[2] == tool) and e[3] == field)

    def window_count(self, now: datetime, agent: str, tool: str | None, window: timedelta) -> int:
        since = (now - window).isoformat()
        with self._lock:
            return sum(1 for e in self._events if e[0] >= since and e[1] == agent and (tool is None or e[2] == tool) and e[3] == "")


# --- built-in classifiers: heuristics, no models, local -------------------------------------

_INJECTION_PATTERNS = [
    re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|rules)", re.I),
    re.compile(r"(you are now|from now on you are|act as) ", re.I),
    re.compile(r"(system|developer) (prompt|message)\s*:", re.I),
    re.compile(r"(disregard|forget) (your|the) (instructions|guidelines|rules)", re.I),
    re.compile(r"(reveal|print|show) (your|the) (system prompt|instructions)", re.I),
    re.compile(r"[​‌‍⁠﻿]"),  # zero-width characters
    re.compile(r"(?:[A-Za-z0-9+/]{40,}={0,2})"),  # long base64 blobs
]
_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),  # card-like digit runs
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),  # IBAN
    re.compile(r"\+?\d[\d\s().-]{8,}\d"),  # phone
]


def classify(name: str, text: str) -> float:
    """A score in 0..1 from local heuristics. ``prompt_injection`` counts
    instruction-override patterns and hidden payloads; ``pii`` counts
    identifier shapes. Not a model, and labeled as such in the policy's
    evidence."""
    if not text:
        return 0.0
    patterns = _INJECTION_PATTERNS if name == "prompt_injection" else _PII_PATTERNS if name == "pii" else []
    hits = sum(1 for p in patterns if p.search(text))
    return min(1.0, hits / 2.0) if patterns else 0.0


# --- evaluation ----------------------------------------------------------------------------------


def evaluate_condition(cond: dict, ns: dict, *, store: WindowStore | None = None, killswitch: KillSwitch | None = None, now: datetime | None = None, expr_eval=None) -> tuple[bool | None, str]:
    """``(fired, reason)``. ``fired`` is None when the condition could not be evaluated."""
    now = now or datetime.now(timezone.utc)
    try:
        if not cond:
            return False, "empty condition"
        if "all" in cond:
            results = [evaluate_condition(c, ns, store=store, killswitch=killswitch, now=now, expr_eval=expr_eval) for c in cond["all"]]
            if any(r[0] is None for r in results):
                return None, next(r[1] for r in results if r[0] is None)
            return all(r[0] for r in results), "; ".join(r[1] for r in results if r[0])
        if "any" in cond:
            results = [evaluate_condition(c, ns, store=store, killswitch=killswitch, now=now, expr_eval=expr_eval) for c in cond["any"]]
            fired = [r for r in results if r[0]]
            return bool(fired), fired[0][1] if fired else "no branch fired"
        key, value = next(iter(cond.items()))
        amount = ns.get("amount")
        args = ns.get("args") or {}
        agent = (ns.get("agent") or {}).get("id") or "?"
        tool = ns.get("tool")
        if key == "amount_gt":
            return (amount is not None and amount > value), f"amount {amount} > {value}" if amount is not None else "no amount"
        if key == "amount_gte":
            return (amount is not None and amount >= value), f"amount {amount} >= {value}" if amount is not None else "no amount"
        if key == "window_sum_gt":
            if store is None:
                return None, "no window store"
            window = parse_window(value["window"])
            field = value["field"]
            current = args.get(field) if field != "amount" or amount is None else amount
            current = float(current) if isinstance(current, (int, float)) and not isinstance(current, bool) else 0.0
            total = store.window_sum(now, agent, tool if (ns.get("_scope_tool")) else None, field, window) + current
            return total > value["value"], f"{field} over {value['window']}: {total:g} > {value['value']}"
        if key == "window_count_gt":
            if store is None:
                return None, "no window store"
            window = parse_window(value["window"])
            count = store.window_count(now, agent, tool if (ns.get("_scope_tool")) else None, window) + 1
            return count > value["value"], f"calls over {value['window']}: {count} > {value['value']}"
        if key in ("field_in", "field_not_in"):
            present = args.get(value["field"])
            inside = present in value["values"]
            fired = inside if key == "field_in" else (present is not None and not inside)
            return fired, f"{value['field']} {'in' if inside else 'not in'} the list"
        if key == "regex_match":
            text = args.get(value["field"])
            if text is None and value["field"] == "text":
                text = ns.get("text")
            fired = bool(text is not None and re.search(value["pattern"], str(text)))
            return fired, f"{value['field']} {'matches' if fired else 'does not match'} the pattern"
        if key == "approval_missing":
            missing = not (ns.get("approval") or {}).get("granted")
            return (missing == bool(value)), "no approval on the call" if missing else "approval present"
        if key == "killswitch":
            state = killswitch.is_killed(agent) if killswitch else False
            return (state == bool(value)), (f"kill switch set for {agent}" if state else "kill switch clear")
        if key == "classifier":
            text = ns.get("text") or " ".join(str(v) for v in args.values() if isinstance(v, str))
            score = classify(value["name"], text)
            threshold = float(value.get("threshold", 0.5))
            return score >= threshold, f"{value['name']} score {score:.2f} vs {threshold:.2f}"
        if key == "expr":
            if expr_eval is None:
                return None, "no expression evaluator"
            return bool(expr_eval(value, ns)), f"expr {value!r}"
        return None, f"unknown condition {key}"
    except Exception as exc:  # noqa: BLE001
        return None, f"condition error: {exc}"


def condition_text(cond: dict) -> str:
    """One line a reader can scan: 'amount > 200', 'sum(amount) over 24h > 5000'."""
    if not cond:
        return "always"
    if "all" in cond:
        return " and ".join(condition_text(c) for c in cond["all"])
    if "any" in cond:
        return " or ".join(condition_text(c) for c in cond["any"])
    key, value = next(iter(cond.items()))
    if key == "amount_gt":
        return f"amount > {value:g}" if isinstance(value, (int, float)) else f"amount > {value}"
    if key == "amount_gte":
        return f"amount >= {value:g}" if isinstance(value, (int, float)) else f"amount >= {value}"
    if key == "window_sum_gt":
        return f"sum({value.get('field')}) over {value.get('window')} > {value.get('value')}"
    if key == "window_count_gt":
        return f"calls over {value.get('window')} > {value.get('value')}"
    if key == "field_in":
        return f"{value.get('field')} in {value.get('values')}"
    if key == "field_not_in":
        return f"{value.get('field')} not in the allow-list"
    if key == "regex_match":
        return f"{value.get('field')} matches /{value.get('pattern')}/"
    if key == "approval_missing":
        return "no approval on the call" if value else "approval present"
    if key == "killswitch":
        return "kill switch set" if value else "kill switch clear"
    if key == "classifier":
        return f"{value.get('name')} score >= {value.get('threshold', 0.5)}"
    if key == "expr":
        return str(value)
    return key

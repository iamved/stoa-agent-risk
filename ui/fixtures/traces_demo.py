"""Deterministic demo traces for the Meridian Pay fixture (stoa-trace/1.1).

Two trace directories tell the runtime half of the September story:

* ``meridian-pay-august``: account-actions before the push. Every refund
  cites an approval; amounts stay under the declared $500. This is what the
  committed baseline is built from.
* ``meridian-pay``: the week after the push. account-actions moves money
  without approval on some calls and once over the limit; meridian-support
  refunds with no approval at all, calls a tool the scan never listed
  (``export_transcript``), and emails through an integration the scan never
  found. Knowledge and escalation record nothing, so they read as idle.

Everything is fixed text: ids from a counter, timestamps from a table, the
chain signed with a demo HMAC key. Flags are computed by the same engine
the SDK uses, against the head registry, so the fixture carries exactly
what a real run would.
"""

from __future__ import annotations

import json
from pathlib import Path

from stoa import __version__
from stoa.runtime.chain import GENESIS, chain_record
from stoa.runtime.flags import FlagEngine
from stoa.runtime.keys import HmacSigner
from stoa.runtime.policy import decide, load_policy
from stoa.runtime.registry import RegistryFacts, load_registry_facts
from stoa.runtime.spans import build_span, header_record
from stoa.policy.conditions import WindowStore

POLICY_FILE = Path(__file__).resolve().parents[2] / "examples" / "meridian-pay" / "stoa.policy.toml"


class _Killed:
    """A kill switch that is set: used once, for the drill span."""

    def is_killed(self, agent_id, agent_name=None):
        return True

    def reason(self, agent_id):
        return "drill"

DEMO_KEY = "hmac:6d6572696469616e2d64656d6f"  # "meridian-demo" as hex
ACCOUNT, SUPPORT, FRONT = "b8f0111742fc", "bc3db1f17013", "2a61ffb1db0d"


class _Writer:
    def __init__(self, facts: RegistryFacts, *, policy_path: Path | None = None) -> None:
        self.records: list[dict] = []
        self.flags = FlagEngine(facts)
        self.facts = facts
        self.policy = load_policy(policy_path) if policy_path else None
        self.store = WindowStore(None)
        self.n = 0

    def ident(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n:04x}"

    def _policy(self, attrs: dict, *, agent: str, tool: str, side_effect: str, amount, approval_id, end: str, killed: bool = False) -> tuple[str | None, str]:
        """Stamp the policy decisions the SDK would have written for this call. Returns (enforcement, status)."""
        if self.policy is None or not self.policy.rules:
            return None, "ok"
        from datetime import datetime, timezone

        facts = self.facts.for_agent(agent)
        now = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        ns = {
            "tool": tool, "args": {"amount": amount} if amount is not None else {}, "side_effect": side_effect, "amount": amount,
            "approval": {"granted": approval_id is not None, "span_id": approval_id},
            "agent": {"id": agent, "name": facts.name if facts else agent, "declared_tools": sorted(facts.tools) if facts else [], "max_per_action": facts.max_per_action if facts else None},
            "session": {"id": None},
        }
        decisions = decide(self.policy, ns, fail_open=True, store=self.store, killswitch=_Killed() if killed else None, now=now)
        attrs["policy_rules"] = ",".join(d.rule_id for d in decisions)
        attrs["policy_decisions"] = ",".join(d.decision for d in decisions)
        attrs["policy_actions"] = ",".join(d.action or d.decision for d in decisions)
        denied = next((d for d in decisions if d.decision == "deny" and d.enforced), None)
        if denied:
            attrs["policy_denied_by"] = denied.rule_id
            return "denied", "error"
        if amount is not None:
            self.store.observe(now, agent, tool, {"amount": amount})
        if any(d.decision in ("deny", "require_approval", "observe", "mask") for d in decisions):
            return "observed", "ok"
        return "allowed", "ok"

    def span(self, *, kind: str, agent: str, trace: str, session: str, start: str, end: str, parent: str | None = None, status: str = "ok", attrs: dict | None = None, counterparty: str | None = None, killed: bool = False, **fields) -> str:
        span_id = self.ident("s")
        attrs = dict(attrs or {})
        enforcement = None
        if kind == "action" and fields.get("tool"):
            amount = fields.get("amount")
            enforcement, status = self._policy(attrs, agent=agent, tool=fields["tool"], side_effect=attrs.get("side_effect", "write"), amount=amount, approval_id=fields.get("approval_span_id"), end=end, killed=killed)
        record = build_span(
            trace_id=trace, span_id=span_id, parent_span_id=parent, kind=kind, start_ts=start, end_ts=end,
            status=status, redaction="redacted", agent_id=agent, session_id=session, attrs=attrs, enforcement=enforcement, **fields,
        )
        flags = self.flags.compute(record, counterparty=counterparty)
        if flags:
            record.setdefault("attrs", {})["flags"] = sorted(flags)
        self.records.append(record)
        return span_id

    def write(self, path: Path) -> None:
        signer = HmacSigner(bytes.fromhex(DEMO_KEY.split(":")[1]))
        header = chain_record(header_record(__version__, "redacted", 0, key_grade=signer.grade), GENESIS, signer)
        prev = header["hash"]
        lines = [json.dumps(header, separators=(",", ":"), sort_keys=True)]
        for record in self.records:
            chain_record(record, prev, signer)
            prev = record["hash"]
            lines.append(json.dumps(record, separators=(",", ":"), sort_keys=True))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")


def _ts(day: str, hour: int, minute: int, second: int = 0, ms: int = 0) -> str:
    return f"{day}T{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}Z"


def _refund_session(w: _Writer, *, agent: str, day: str, hour: int, amount: float, model: str, approved: bool, tool: str = "issue_refund", extra_tool: str | None = None, send: bool = False, customer: str = "c1") -> None:
    trace = w.ident("t")
    session = w.ident("x")
    run_start, run_end = _ts(day, hour, 0), _ts(day, hour, 1, 30)
    w.span(kind="llm_call", agent=agent, trace=trace, session=session, start=_ts(day, hour, 0, 1), end=_ts(day, hour, 0, 2, 400), provider="openai", model=model, cost=0.0021,
           attrs={"gen_ai.usage.input_tokens": 412, "gen_ai.usage.output_tokens": 96})
    approval = None
    if approved:
        approval = w.span(kind="approval", agent=agent, trace=trace, session=session, start=_ts(day, hour, 0, 20), end=_ts(day, hour, 0, 58),
                          approved_by="a4f1c2e9b7d3", approval_method="slack_interactive", attrs={"granted": True, "actor_type": "human", "latency_ms": 38000})
    w.span(kind="action", agent=agent, trace=trace, session=session, start=_ts(day, hour, 1, 0), end=_ts(day, hour, 1, 2, 300),
           capability="payment_access", integration="stripe", tool=tool, amount=amount, currency="USD", approval_span_id=approval,
           attrs={"side_effect": "payment", "limit_field": "amount"}, counterparty=customer)
    if extra_tool:
        w.span(kind="action", agent=agent, trace=trace, session=session, start=_ts(day, hour, 1, 5), end=_ts(day, hour, 1, 6),
               tool=extra_tool, attrs={"side_effect": "external_send"})
    if send:
        w.span(kind="action", agent=agent, trace=trace, session=session, start=_ts(day, hour, 1, 10), end=_ts(day, hour, 1, 11),
               capability="email_send", integration="sendgrid", tool="send_email", attrs={"side_effect": "external_send"})
    w.span(kind="agent_run", agent=agent, trace=trace, session=session, start=run_start, end=run_end, attrs={"user_ref": "9b1e4d0c7a2f"})


def _front_session(w: _Writer, *, day: str, hour: int) -> None:
    trace = w.ident("t")
    session = w.ident("x")
    w.span(kind="llm_call", agent=FRONT, trace=trace, session=session, start=_ts(day, hour, 0, 1), end=_ts(day, hour, 0, 1, 900), provider="openai", model="gpt-4o", cost=0.0008)
    w.span(kind="action", agent=FRONT, trace=trace, session=session, start=_ts(day, hour, 0, 2), end=_ts(day, hour, 0, 2, 200), tool="verify_identity", attrs={"side_effect": "read"})
    w.span(kind="delegation", agent=FRONT, trace=trace, session=session, start=_ts(day, hour, 0, 3), end=_ts(day, hour, 0, 3, 100), from_agent_id=FRONT, to_agent_id=ACCOUNT)
    w.span(kind="agent_run", agent=FRONT, trace=trace, session=session, start=_ts(day, hour, 0, 0), end=_ts(day, hour, 0, 4))


def _drill(w: _Writer, *, agent: str, day: str, hour: int) -> None:
    """A kill-switch drill: the flag set, the next refund blocked by POL-BASE-001, the time recorded."""
    trace = w.ident("t")
    session = w.ident("x")
    w.span(kind="action", agent=agent, trace=trace, session=session, start=_ts(day, hour, 0, 1), end=_ts(day, hour, 0, 2, 800),
           capability="payment_access", integration="stripe", tool="issue_refund", amount=20.0, currency="USD",
           attrs={"side_effect": "payment", "limit_field": "amount"}, killed=True)
    w.span(kind="agent_run", agent=agent, trace=trace, session=session, start=_ts(day, hour, 0, 0), end=_ts(day, hour, 0, 3),
           attrs={"killswitch_drill": True, "seconds_to_stop": 1.8, "drill_by": "platform-risk"})


def write_demo_traces(out: Path, head_registry_path: Path) -> tuple[Path, Path]:
    """Write both directories; returns (august_dir, september_dir)."""
    facts = load_registry_facts(head_registry_path)

    august = _Writer(facts)
    for i, (day, amount) in enumerate([("2026-08-18", 120.0), ("2026-08-19", 45.0), ("2026-08-20", 310.0), ("2026-08-21", 80.0), ("2026-08-24", 260.0), ("2026-08-25", 150.0)]):
        _front_session(august, day=day, hour=9)
        _refund_session(august, agent=ACCOUNT, day=day, hour=10 + i % 3, amount=amount, model="gpt-4o", approved=True, customer=f"c{i}")
    august_dir = out / "meridian-pay-august"
    august.write(august_dir / "trace-demo-0000.jsonl")

    september = _Writer(facts, policy_path=POLICY_FILE)
    # (day, hour, agent, amount, approved, extras). Support refunds cluster on the 18th so the daily cap is tested for real.
    plan = [
        ("2026-09-15", 10, ACCOUNT, 180.0, True, {}), ("2026-09-15", 11, SUPPORT, 60.0, False, {}),
        ("2026-09-16", 10, ACCOUNT, 420.0, True, {}), ("2026-09-16", 13, SUPPORT, 240.0, False, {"send": True}),
        ("2026-09-17", 10, ACCOUNT, 900.0, False, {}), ("2026-09-17", 12, SUPPORT, 35.0, False, {}),
        ("2026-09-18", 9, SUPPORT, 90.0, False, {}), ("2026-09-18", 10, ACCOUNT, 95.0, True, {}),
        ("2026-09-18", 11, SUPPORT, 260.0, False, {"tool": "waive_fee"}), ("2026-09-18", 13, SUPPORT, 150.0, False, {}),
        ("2026-09-18", 15, SUPPORT, 500.0, False, {"extra_tool": "export_transcript"}),
        ("2026-09-19", 10, ACCOUNT, 70.0, False, {}), ("2026-09-19", 11, SUPPORT, 120.0, False, {}),
        ("2026-09-20", 10, ACCOUNT, 230.0, True, {}), ("2026-09-21", 11, SUPPORT, 85.0, False, {}),
    ]
    for i, (day, hour, agent, amount, approved, extra) in enumerate(plan):
        if agent == ACCOUNT:
            _front_session(september, day=day, hour=hour - 1)
        _refund_session(september, agent=agent, day=day, hour=hour, amount=amount, model="gpt-4o" if agent == ACCOUNT else "gpt-4o-mini", approved=approved, customer=f"c{i % 5}", **extra)
    _drill(september, day="2026-09-21", hour=16, agent=SUPPORT)
    september_dir = out / "meridian-pay"
    september.write(september_dir / "trace-demo-0000.jsonl")
    return august_dir, september_dir

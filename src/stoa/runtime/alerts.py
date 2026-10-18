"""Local alerts over a trace window (`stoa runtime alerts`) — `runtime-alerts/1.0`.

Rules live under ``[alerts]`` in ``stoa.policy.toml``; a file without that
block gets the defaults below. Evaluation reads the same documents the
dashboard does (analysis, drift, chain) and never the raw spans, so it runs
anywhere the files are. Delivery is optional and local: a webhook signed
with ``X-Stoa-Signature: sha256=<hmac>`` over the body, a Slack incoming
webhook, or the terminal. Alerts are deduplicated per ``(agent_id, rule_id)``
within ``dedupe_minutes`` using a small state file next to the traces;
medium and low alerts fold into one digest message unless the rule says
``digest = "none"``.

Example::

    [alerts]
    dedupe_minutes = 15

    [alerts.channels.slack]
    webhook_url_env = "STOA_SLACK_WEBHOOK"

    [alerts.channels.webhook]
    url = "https://risk.example.test/stoa"
    hmac_secret_env = "STOA_WEBHOOK_SECRET"

    [[alerts.rules]]
    id = "approval-bypassed"
    trigger = "flag == 'approval_bypassed' and side_effect in ['payment', 'delete', 'external_send']"
    severity = "critical"
    channels = ["slack", "webhook"]

Triggers are the policy evaluator's expressions over one of three event
shapes: a flagged span (``flag``, ``agent``, ``tool``, ``side_effect``,
``amount``), a drift event (``drift_kind``, ``drift_class``, ``agent``), or
the window itself (``chain_break``, ``silent_days``, ``rt_findings``,
``score_delta_24h`` when two analyses are compared).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .policy import UnknownName, evaluate

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ALERTS_SCHEMA = "runtime-alerts/1.0"
SEVERITIES = ("critical", "high", "medium", "low")

DEFAULT_RULES: list[dict] = [
    {"id": "undeclared-tool", "trigger": "flag == 'undeclared_tool'", "severity": "high", "summary": "{agent} called {tool}, a tool the scan never listed."},
    {"id": "approval-bypassed", "trigger": "flag == 'approval_bypassed' and side_effect in ['payment', 'delete', 'external_send']", "severity": "critical", "summary": "{agent} ran {tool} ({side_effect}) with no approval on the path."},
    {"id": "over-declared-limit", "trigger": "flag == 'over_declared_limit'", "severity": "high", "summary": "{agent} moved {amount} on {tool}, over its declared limit."},
    {"id": "new-counterparty", "trigger": "flag == 'new_counterparty'", "severity": "medium", "summary": "{agent} paid a counterparty it had not paid before."},
    {"id": "burst", "trigger": "flag == 'burst'", "severity": "medium", "summary": "{agent} called {tool} in a burst."},
    {"id": "policy-denied", "trigger": "enforcement == 'denied'", "severity": "high", "summary": "A policy denied {tool} for {agent}."},
    {"id": "model-or-integration-changed", "trigger": "flag in ['model_changed', 'integration_changed']", "severity": "medium", "summary": "{agent} changed its model or an integration without a new scan."},
    {"id": "approval-rate-drop", "trigger": "drift_kind == 'approval_rate_drop'", "severity": "high", "summary": "Approval rate fell for {agent} against the baseline."},
    {"id": "chain-broken", "trigger": "chain_break == true", "severity": "critical", "summary": "A trace file's chain is broken: {detail}."},
    {"id": "agent-silent", "trigger": "silent_days >= 7", "severity": "low", "summary": "{agent} has recorded nothing for {silent_days} days."},
]


@dataclass
class AlertRule:
    id: str
    trigger: str
    severity: str = "medium"
    channels: list = field(default_factory=list)
    digest: str | None = None  # None = by severity (medium/low digest), "none" = always immediate
    summary: str = ""


@dataclass
class AlertConfig:
    dedupe_minutes: int = 15
    channels: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def load_alert_config(path: str | Path | None) -> AlertConfig:
    """``[alerts]`` from stoa.policy.toml; defaults when absent or unreadable."""
    config = AlertConfig(rules=[AlertRule(**r) for r in DEFAULT_RULES])
    if not path or not Path(path).is_file():
        return config
    try:
        block = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("alerts") or {}
    except Exception as exc:  # noqa: BLE001
        config.warnings.append(f"alerts block unreadable: {exc}")
        return config
    defaults = block.get("defaults") or {}
    config.dedupe_minutes = int(block.get("dedupe_minutes", defaults.get("dedupe_minutes", 15)))
    config.channels = dict(block.get("channels") or {})
    rules = block.get("rules")
    if isinstance(rules, list) and rules:
        parsed = []
        for index, raw in enumerate(rules):
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("trigger"):
                config.warnings.append(f"alerts.rules[{index}]: needs id and trigger; ignored")
                continue
            severity = raw.get("severity", "medium")
            if severity not in SEVERITIES:
                config.warnings.append(f"alerts.rules[{index}] ({raw['id']}): severity must be one of {SEVERITIES}; ignored")
                continue
            parsed.append(AlertRule(id=str(raw["id"]), trigger=str(raw["trigger"]), severity=severity, channels=list(raw.get("channels") or []), digest=raw.get("digest"), summary=str(raw.get("summary") or "")))
        config.rules = parsed
    return config


# --- evaluation ---------------------------------------------------------------------------


def _events(analysis: dict, drift: dict | None, chain: dict | None, registry: dict | None, now: datetime) -> list[dict]:
    """Every candidate the rules look at, as flat namespaces."""
    names = {a["id"]: ((a.get("declared") or {}).get("name") or a.get("display_name") or a.get("name") or a["id"]) for a in (registry or {}).get("agents") or []}
    out: list[dict] = []
    for agent_id, summary in (analysis.get("agents") or {}).items():
        agent = names.get(agent_id, agent_id)
        for event in summary.get("flag_events") or []:
            amount = event.get("amount") or {}
            for flag in event.get("flags") or []:
                out.append({"shape": "flag", "flag": flag, "agent": agent, "agent_id": agent_id, "tool": event.get("tool"), "side_effect": None, "amount": amount.get("amount"), "currency": amount.get("currency"), "enforcement": None, "ts": event.get("ts"), "event_ids": [event.get("trace_ref", {}).get("span_id")]})
        last = summary.get("last_ts")
        silent = (now - datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)).days if last else None
        out.append({"shape": "window", "agent": agent, "agent_id": agent_id, "silent_days": silent, "chain_break": False, "rt_findings": 0, "ts": last, "event_ids": []})
    for agent_id in analysis.get("no_runtime_evidence") or []:
        window_end = (analysis.get("window") or {}).get("end")
        silent = (now - datetime.strptime(window_end, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)).days if window_end else None
        out.append({"shape": "window", "agent": names.get(agent_id, agent_id), "agent_id": agent_id, "silent_days": silent, "chain_break": False, "rt_findings": 0, "ts": window_end, "event_ids": []})
    for event in (drift or {}).get("events") or []:
        out.append({"shape": "drift", "drift_kind": event.get("kind"), "drift_class": event.get("class"), "agent": names.get(event.get("agent_id"), event.get("agent_id")), "agent_id": event.get("agent_id"), "ts": (analysis.get("window") or {}).get("end"), "event_ids": []})
    for item in (chain or {}).get("files") or []:
        if not item.get("ok"):
            out.append({"shape": "chain", "chain_break": True, "agent": "traces", "agent_id": "*", "detail": f"{item['file']} line {item.get('first_break')}, {item.get('break_reason')}", "ts": (analysis.get("window") or {}).get("end"), "event_ids": []})
    return out


def evaluate_alerts(analysis: dict, *, drift: dict | None = None, chain: dict | None = None, registry: dict | None = None, config: AlertConfig | None = None, now: datetime | None = None, state: dict | None = None) -> dict:
    """Build the alerts document. ``state`` (mutated) holds the dedupe table
    ``{"agent|rule": "<last fired iso>"}``; pass the loaded state file."""
    config = config or load_alert_config(None)
    now = now or datetime.now(timezone.utc)
    state = state if state is not None else {}
    alerts: list[dict] = []
    deduped = 0
    for event in _events(analysis, drift, chain, registry, now):
        namespace = {k: v for k, v in event.items() if k not in ("shape", "event_ids")}
        # money-side flags imply the side effect the trigger asks about
        if event.get("flag") in ("approval_bypassed", "over_declared_limit"):
            namespace["side_effect"] = "payment"
        for rule in config.rules:
            try:
                fired = bool(evaluate(rule.trigger, {**{"flag": None, "drift_kind": None, "drift_class": None, "chain_break": False, "silent_days": None, "enforcement": None, "side_effect": None, "tool": None, "amount": None, "rt_findings": 0, "score_delta_24h": 0, "detail": ""}, **namespace}))
            except (UnknownName, ValueError):
                fired = False
            if not fired:
                continue
            key = f"{event.get('agent_id')}|{rule.id}"
            last = state.get(key)
            if last:
                try:
                    if now - datetime.fromisoformat(last) < timedelta(minutes=config.dedupe_minutes):
                        deduped += 1
                        continue
                except ValueError:
                    pass
            state[key] = now.isoformat()
            fallback = f"{rule.id}: {event.get('detail') or event.get('agent')}"
            summary = (rule.summary or fallback).format(**{**{"amount": f"{event.get('amount')} {event.get('currency') or ''}".strip()}, **{k: v for k, v in event.items() if k != "amount"}})
            alerts.append({
                "alert_id": hashlib.sha256(f"{key}|{event.get('ts')}|{rule.id}".encode()).hexdigest()[:16],
                "rule_id": rule.id,
                "severity": rule.severity,
                "agent_id": event.get("agent_id"),
                "agent": event.get("agent"),
                "fired_at": now.isoformat(),
                "event_ts": event.get("ts"),
                "event_ids": [e for e in event.get("event_ids", []) if e],
                "summary": summary,
                "channels": rule.channels,
                "digest": rule.digest if rule.digest is not None else ("none" if rule.severity in ("critical", "high") else "daily"),
            })
    order = {s: i for i, s in enumerate(SEVERITIES)}
    alerts.sort(key=lambda a: (order[a["severity"]], a["agent"] or "", a["rule_id"]))
    return {"schema": ALERTS_SCHEMA, "generated_at": now.isoformat(), "window": analysis.get("window"), "alerts": alerts, "deduplicated": deduped, "warnings": list(config.warnings)}


# --- delivery -----------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, headers: dict, attempts: int = 3) -> tuple[bool, str]:
    last = ""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - the customer's own URL
                return True, f"{response.status}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
    return False, last


def deliver(document: dict, config: AlertConfig, *, dashboard_url: str | None = None, post=_post) -> list[dict]:
    """Send immediate alerts one by one and digest alerts as one message per
    channel. Returns one record per delivery attempt. Channels that are not
    configured are skipped and reported, never raise."""
    records: list[dict] = []
    immediate = [a for a in document["alerts"] if a["digest"] == "none"]
    digest = [a for a in document["alerts"] if a["digest"] != "none"]
    channels = config.channels or {}

    def send(channel: str, payload: dict) -> None:
        spec = channels.get(channel)
        if channel == "stdout" or not spec:
            if spec is None and channel != "stdout":
                records.append({"channel": channel, "ok": False, "detail": "channel not configured"})
                return
            print(json.dumps(payload, indent=2))
            records.append({"channel": "stdout", "ok": True, "detail": "printed"})
            return
        body = json.dumps({**payload, "dashboard_url": dashboard_url}, separators=(",", ":")).encode("utf-8")
        if channel == "slack":
            url = os.environ.get(spec.get("webhook_url_env", "")) or spec.get("webhook_url")
            if not url:
                records.append({"channel": channel, "ok": False, "detail": "no Slack webhook URL"})
                return
            text = payload.get("text") or payload.get("summary")
            ok, detail = post(url, json.dumps({"text": text}).encode("utf-8"), {})
        else:
            url = spec.get("url")
            if not url:
                records.append({"channel": channel, "ok": False, "detail": "no webhook url"})
                return
            secret = os.environ.get(spec.get("hmac_secret_env", "")) or spec.get("hmac_secret") or ""
            headers = {"X-Stoa-Signature": _sign(secret, body)} if secret else {}
            ok, detail = post(url, body, headers)
        records.append({"channel": channel, "ok": ok, "detail": detail})

    for alert in immediate:
        for channel in alert["channels"] or ["stdout"]:
            send(channel, {**alert, "text": f"[{alert['severity']}] {alert['summary']}"})
    if digest:
        by_channel: dict[str, list[dict]] = {}
        for alert in digest:
            for channel in alert["channels"] or ["stdout"]:
                by_channel.setdefault(channel, []).append(alert)
        for channel, items in by_channel.items():
            text = "Stoa digest: " + "; ".join(f"[{a['severity']}] {a['summary']}" for a in items)
            send(channel, {"digest": True, "alerts": items, "text": text, "summary": text})
    return records


def synthetic_alert(rule_id: str, config: AlertConfig) -> dict:
    """A test alert for `stoa runtime alerts --test RULE_ID`, so channel wiring can be confirmed."""
    rule = next((r for r in config.rules if r.id == rule_id), None)
    if rule is None:
        raise KeyError(rule_id)
    now = datetime.now(timezone.utc).isoformat()
    return {"schema": ALERTS_SCHEMA, "generated_at": now, "window": None, "alerts": [{
        "alert_id": "test", "rule_id": rule.id, "severity": rule.severity, "agent_id": "test-agent", "agent": "test-agent",
        "fired_at": now, "event_ts": now, "event_ids": [], "summary": f"Test alert for rule {rule.id}; wiring check, no event behind it.",
        "channels": rule.channels, "digest": "none",
    }], "deduplicated": 0, "warnings": []}


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass

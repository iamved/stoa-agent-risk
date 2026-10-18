"""Local alerts: rule loading, evaluation over analysis/drift/chain, dedupe, digest, delivery, and the OTLP attribute map."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stoa.cli import main
from stoa.runtime.alerts import DEFAULT_RULES, deliver, evaluate_alerts, load_alert_config, synthetic_alert
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.chain import verify_dir
from stoa.runtime.drift import build_baseline, compute_drift
from stoa.runtime.otel import span_attributes

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "fixtures"
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _registry():
    return json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())["registry"]


def _inputs():
    registry = _registry()
    analysis = analyze_traces(FIXTURES / "traces" / "meridian-pay", registry)
    baseline = build_baseline(analyze_traces(FIXTURES / "traces" / "meridian-pay-august", registry))
    drift = compute_drift(analysis, baseline, registry)
    chain = verify_dir(FIXTURES / "traces" / "meridian-pay").to_dict()
    return registry, analysis, drift, chain


def test_defaults_fire_on_the_demo_window():
    registry, analysis, drift, chain = _inputs()
    doc = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, now=NOW)
    assert doc["schema"] == "runtime-alerts/1.0"
    rules = {a["rule_id"] for a in doc["alerts"]}
    assert {"approval-bypassed", "undeclared-tool", "over-declared-limit", "approval-rate-drop", "new-counterparty"} <= rules
    assert "chain-broken" not in rules
    first = doc["alerts"][0]
    assert first["severity"] == "critical" and first["rule_id"] == "approval-bypassed" and first["event_ids"]
    assert "meridian-support" in {a["agent"] for a in doc["alerts"] if a["rule_id"] == "undeclared-tool"}
    assert any(a["rule_id"] == "over-declared-limit" and "900" in a["summary"] for a in doc["alerts"])
    # digest by severity unless the rule says otherwise
    assert all(a["digest"] == "none" for a in doc["alerts"] if a["severity"] in ("critical", "high"))
    assert all(a["digest"] == "daily" for a in doc["alerts"] if a["severity"] in ("medium", "low"))


def test_dedupe_window_and_silent_agent():
    registry, analysis, drift, chain = _inputs()
    state: dict = {}
    first = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, now=NOW, state=state)
    again = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, now=NOW + timedelta(minutes=5), state=state)
    assert first["alerts"] and again["alerts"] == [] and again["deduplicated"] >= len(first["alerts"])
    later = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, now=NOW + timedelta(hours=1), state=state)
    assert len(later["alerts"]) == len(first["alerts"])
    # idle agents are silent for the days since the window end: nothing at one day, alerts after a week
    assert not [a for a in first["alerts"] if a["rule_id"] == "agent-silent"]
    week = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, now=NOW + timedelta(days=10), state={})
    silent = [a for a in week["alerts"] if a["rule_id"] == "agent-silent"]
    assert {a["agent"] for a in silent} >= {"meridian-knowledge", "meridian-escalation"} and all(a["severity"] == "low" for a in silent)


def test_chain_break_alert_and_custom_rules(tmp_path):
    registry, analysis, drift, _ = _inputs()
    chain = {"files": [{"file": "trace-x.jsonl", "ok": False, "first_break": 7, "break_reason": "hash does not match the record"}]}
    policy = tmp_path / "stoa.policy.toml"
    policy.write_text('[alerts]\ndedupe_minutes = 1\n[alerts.channels.webhook]\nurl = "https://risk.example.test/stoa"\nhmac_secret_env = "STOA_WEBHOOK_SECRET"\n[[alerts.rules]]\nid = "chain"\ntrigger = "chain_break == true"\nseverity = "critical"\nchannels = ["webhook"]\n[[alerts.rules]]\nid = "bad"\ntrigger = "flag == 1"\nseverity = "loud"\n')
    config = load_alert_config(policy)
    assert [r.id for r in config.rules] == ["chain"] and config.warnings and config.dedupe_minutes == 1
    doc = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, config=config, now=NOW)
    assert [a["rule_id"] for a in doc["alerts"]] == ["chain"] and "trace-x.jsonl line 7" in doc["alerts"][0]["summary"]


def test_delivery_signs_webhooks_and_digests_the_rest(monkeypatch, capsys):
    registry, analysis, drift, chain = _inputs()
    config = load_alert_config(None)
    config.channels = {"webhook": {"url": "https://risk.example.test/stoa", "hmac_secret_env": "STOA_WEBHOOK_SECRET"}, "slack": {"webhook_url_env": "STOA_SLACK_WEBHOOK"}}
    for rule in config.rules:
        rule.channels = ["webhook", "slack"]
    monkeypatch.setenv("STOA_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("STOA_SLACK_WEBHOOK", "https://hooks.slack.test/abc")
    doc = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, config=config, now=NOW)
    posts = []

    def fake_post(url, body, headers, attempts=3):
        posts.append((url, body, headers))
        return True, "200"

    records = deliver(doc, config, dashboard_url="https://example.test/dash", post=fake_post)
    assert all(r["ok"] for r in records)
    webhook_posts = [p for p in posts if p[0].startswith("https://risk")]
    slack_posts = [p for p in posts if p[0].startswith("https://hooks")]
    immediate = [a for a in doc["alerts"] if a["digest"] == "none"]
    assert len(webhook_posts) == len(immediate) + 1 and len(slack_posts) == len(immediate) + 1  # one digest per channel
    import hashlib
    import hmac
    url, body, headers = webhook_posts[0]
    assert headers["X-Stoa-Signature"] == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert json.loads(body)["dashboard_url"] == "https://example.test/dash"
    assert "Stoa digest" in json.loads(webhook_posts[-1][1])["text"]
    # an unconfigured channel is reported, not raised
    config.channels = {}
    records = deliver(synthetic_alert("burst", config), config, post=fake_post)
    assert records and records[0]["channel"] == "webhook" and records[0]["ok"] is False
    with pytest.raises(KeyError):
        synthetic_alert("no-such-rule", config)


def test_cli_alerts_prints_writes_and_tests(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reg.json").write_text(json.dumps(_registry()))
    assert main(["runtime", "alerts", str(FIXTURES / "traces" / "meridian-pay"), "--registry", "reg.json", "--out", "alerts.json", "--state", "state.json"]) == 0
    out = capsys.readouterr().out
    assert "approval-bypassed" in out and "alert(s)" in out
    doc = json.loads((tmp_path / "alerts.json").read_text())
    assert doc["schema"] == "runtime-alerts/1.0" and json.loads((tmp_path / "state.json").read_text())
    assert main(["runtime", "alerts", "--test", "undeclared-tool"]) == 0
    assert "Test alert for rule undeclared-tool" in capsys.readouterr().out
    assert main(["runtime", "alerts", "--test", "nope"]) == 2
    assert len(DEFAULT_RULES) == 10


def test_otlp_attribute_map_is_flat_and_content_free():
    span = {"kind": "action", "agent_id": "a", "tool": "issue_refund", "amount": {"amount": 12.5, "currency": "USD"}, "cost": {"amount": 0.002, "currency": "USD"}, "model": "gpt-4o", "provider": "openai", "session_id": "s", "enforcement": "observed", "status": "ok", "trace_id": "t", "span_id": "x", "parent_span_id": None, "redaction": "redacted", "hash": "abc",
            "attrs": {"flags": ["burst", "undeclared_tool"], "gen_ai.usage.input_tokens": 4, "side_effect": "payment", "prompt_sha256": "deadbeef", "nested": {"no": 1}}}
    attrs = span_attributes(span)
    assert attrs["stoa.amount"] == 12.5 and attrs["stoa.currency"] == "USD" and attrs["gen_ai.usage.cost"] == 0.002
    assert attrs["gen_ai.request.model"] == "gpt-4o" and attrs["gen_ai.system"] == "openai"
    assert attrs["stoa.flags"] == "burst,undeclared_tool" and attrs["gen_ai.usage.input_tokens"] == 4
    assert attrs["stoa.attr.side_effect"] == "payment" and attrs["stoa.attr.prompt_sha256"] == "deadbeef"
    assert "stoa.attr.nested" not in attrs and "stoa.parent_span_id" not in attrs
    assert all(isinstance(v, (str, int, float, bool)) for v in attrs.values())


def test_otlp_mirror_degrades_without_the_package_or_endpoint(tmp_path, monkeypatch):
    from stoa import runtime as rt
    from stoa.runtime.otel import OtlpMirror
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    with pytest.warns(RuntimeWarning):
        assert OtlpMirror(None).active is False
    pytest.importorskip("opentelemetry", reason="the OTLP mirror needs the [runtime] extra") if False else None
    rt.shutdown()
    with pytest.warns(RuntimeWarning):
        rt.configure(str(tmp_path), agent_id="a", exporter="otlp", otlp_endpoint="http://127.0.0.1:9/v1/traces")
    with rt.stoa_span("action", tool="t"):
        pass
    rt.shutdown()
    assert list(tmp_path.glob("*.jsonl"))  # the file sink still wrote

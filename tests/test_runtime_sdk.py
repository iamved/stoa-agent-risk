"""Runtime overlay Phase 1: trace schema, SDK, JSONL exporter, reader.

Covers the Phase-1 slice of the runtime-overlay test plan: schema round-trip,
parent/child links, redact-by-default (content never on disk unless opted
in), rotation, no-op degradation on unwritable dirs, never-raises, reader
fail-open, and the hot-path performance smoke budget.
"""

from __future__ import annotations

import json
import os
import time
import warnings

import pytest

from stoa import runtime as rt
from stoa.runtime.reader import TraceReader
from stoa.runtime.spans import TRACE_SCHEMA, build_span, redact_attrs, sha256_text


@pytest.fixture(autouse=True)
def _clean_sdk():
    """Every test starts and ends with the SDK dormant."""
    rt.shutdown()
    yield
    rt.shutdown()


def _read_all(traces_dir):
    reader = TraceReader(traces_dir)
    return list(reader.spans()), reader.stats


# --- schema round-trip -------------------------------------------------------


def test_span_round_trip_through_file(tmp_path):
    rt.configure(str(tmp_path), agent_id="a09ff38687e9")
    with rt.stoa_span(
        "action", capability="payment_access", integration="stripe",
        amount=120.5, currency="USD",
    ):
        pass
    rt.shutdown()

    spans, stats = _read_all(tmp_path)
    assert stats.spans_read == 1 and stats.bad_lines == 0
    (span,) = spans
    assert span["kind"] == "action"
    assert span["agent_id"] == "a09ff38687e9"
    assert span["capability"] == "payment_access"
    assert span["integration"] == "stripe"
    assert span["amount"] == {"amount": 120.5, "currency": "USD"}
    assert span["status"] == "ok"
    assert span["redaction"] == "redacted"
    assert "vocabulary" not in span  # scanner ids are not "custom"
    assert span["start_ts"].endswith("Z") and span["end_ts"].endswith("Z")


def test_header_line_first_in_every_file(tmp_path):
    rt.configure(str(tmp_path))
    with rt.stoa_span("llm_call", provider="openai", model="gpt-4o"):
        pass
    rt.shutdown()
    (path,) = sorted(tmp_path.glob("*.jsonl"))
    first = json.loads(path.read_text().splitlines()[0])
    assert first["kind"] == "header"
    assert first["schema"] == TRACE_SCHEMA
    assert first["redaction"] == "redacted"


def test_custom_vocabulary_flagged_not_dropped():
    span = build_span(
        trace_id="t", span_id="s", parent_span_id=None, kind="tool_call",
        start_ts="x", end_ts="y", status="ok", redaction="redacted",
        capability="totally_custom_thing",
    )
    assert span["capability"] == "totally_custom_thing"
    assert span["vocabulary"] == "custom"


def test_delegation_span_links_both_agents(tmp_path):
    rt.configure(str(tmp_path))
    with rt.stoa_span("delegation", from_agent_id="aaaa", to_agent_id="bbbb"):
        pass
    rt.shutdown()
    (span,), _ = _read_all(tmp_path)
    assert span["from_agent_id"] == "aaaa" and span["to_agent_id"] == "bbbb"


# --- parent/child + trace propagation ----------------------------------------


def test_nested_spans_share_trace_and_link_parent(tmp_path):
    rt.configure(str(tmp_path))
    with rt.stoa_span("agent_run") as outer_id:
        with rt.stoa_span("llm_call", provider="openai"):
            pass
    rt.shutdown()
    spans, _ = _read_all(tmp_path)
    inner = next(s for s in spans if s["kind"] == "llm_call")
    outer = next(s for s in spans if s["kind"] == "agent_run")
    assert inner["trace_id"] == outer["trace_id"]
    assert inner["parent_span_id"] == outer["span_id"] == outer_id
    assert outer["parent_span_id"] is None


# --- redaction ----------------------------------------------------------------


def test_content_never_on_disk_by_default(tmp_path):
    secret_prompt = "customer SSN is 123-45-6789 please refund"
    rt.configure(str(tmp_path))
    with rt.stoa_span("llm_call", attrs={"prompt": secret_prompt, "tokens": 42}):
        pass
    rt.shutdown()

    raw = b"".join(p.read_bytes() for p in tmp_path.glob("*.jsonl"))
    assert secret_prompt.encode() not in raw
    assert b"123-45-6789" not in raw
    (span,), _ = _read_all(tmp_path)
    assert span["attrs"]["prompt_sha256"] == sha256_text(secret_prompt)
    assert span["attrs"]["prompt_chars"] == len(secret_prompt)
    assert span["attrs"]["tokens"] == 42  # numeric attrs pass through


def test_capture_content_opt_in_with_hook(tmp_path):
    rt.configure(
        str(tmp_path), capture_content=True,
        redaction_hook=lambda text: text.replace("123-45-6789", "[SSN]"),
    )
    with rt.stoa_span("llm_call", attrs={"prompt": "SSN 123-45-6789 refund"}):
        pass
    rt.shutdown()
    (span,), _ = _read_all(tmp_path)
    assert span["redaction"] == "content"
    assert span["attrs"]["prompt"] == "SSN [SSN] refund"


def test_redact_attrs_handles_non_string_values():
    out = redact_attrs({"payload": {"a": 1}}, capture_content=False, redaction_hook=None)
    assert set(out) == {"payload_sha256", "payload_chars"}


# --- degradation & safety -------------------------------------------------------


def test_unconfigured_sdk_is_a_passthrough():
    @rt.stoa_trace()
    def work(x):
        return x * 2

    assert work(21) == 42
    with rt.stoa_span("action"):
        pass  # no exporter, no crash


def test_unwritable_dir_warns_once_then_noop(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o500)
    try:
        rt.configure(str(blocked / "traces"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with rt.stoa_span("action"):
                pass
            rt.flush()
            with rt.stoa_span("action"):  # second span: already no-op
                pass
            rt.flush()
        runtime_warnings = [w for w in caught if "stoa.runtime" in str(w.message)]
        assert len(runtime_warnings) == 1
        assert "no-op" in str(runtime_warnings[0].message)
    finally:
        os.chmod(blocked, 0o700)


def test_wrapped_exception_propagates_and_span_is_error(tmp_path):
    rt.configure(str(tmp_path))

    @rt.stoa_trace(kind="tool_call")
    def explode():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        explode()
    rt.shutdown()
    (span,), _ = _read_all(tmp_path)
    assert span["status"] == "error"


def test_sdk_internal_failure_never_reaches_caller(tmp_path, monkeypatch):
    rt.configure(str(tmp_path))
    from stoa.runtime import _state

    monkeypatch.setattr(
        _state.exporter, "emit", lambda span: (_ for _ in ()).throw(OSError("disk"))
    )

    @rt.stoa_trace()
    def work():
        return "ok"

    assert work() == "ok"  # exporter blew up; caller never sees it


def test_agent_hint_recorded_when_no_agent_id(tmp_path):
    rt.configure(str(tmp_path))

    @rt.stoa_trace()
    def my_agent_entry():
        return 1

    my_agent_entry()
    rt.shutdown()
    (span,), _ = _read_all(tmp_path)
    assert span["agent_id"] is None
    assert span["agent_hint"]["qualname"].endswith("my_agent_entry")


# --- rotation -------------------------------------------------------------------


def test_rotation_by_size_each_file_has_header(tmp_path):
    rt.configure(str(tmp_path), max_file_bytes=400)
    for _ in range(30):
        with rt.stoa_span("tool_call", tool="search"):
            pass
    rt.shutdown()
    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) > 1
    for path in files:
        first = json.loads(path.read_text().splitlines()[0])
        assert first["kind"] == "header"
    spans, stats = _read_all(tmp_path)
    assert len(spans) == 30 and stats.files_read == len(files)


# --- reader fail-open -------------------------------------------------------------


def test_reader_skips_corrupt_lines_and_counts_them(tmp_path):
    rt.configure(str(tmp_path))
    with rt.stoa_span("action"):
        pass
    rt.shutdown()
    (path,) = tmp_path.glob("*.jsonl")
    with open(path, "a") as handle:
        handle.write("{not json\n")
        handle.write('{"kind": "not_a_real_kind", "span_id": "x"}\n')

    spans, stats = _read_all(tmp_path)
    assert len(spans) == 1
    assert stats.bad_lines == 2
    assert stats.spans_read == 1


def test_reader_missing_header_warns_but_reads(tmp_path):
    span = build_span(
        trace_id="t", span_id="s", parent_span_id=None, kind="action",
        start_ts="x", end_ts="y", status="ok", redaction="redacted",
    )
    (tmp_path / "raw.jsonl").write_text(json.dumps(span) + "\n")
    spans, stats = _read_all(tmp_path)
    assert len(spans) == 1
    assert stats.headers_missing == 1


def test_reader_skips_unknown_major_version(tmp_path):
    lines = [
        json.dumps({"kind": "header", "schema": "stoa-trace/2.0"}),
        json.dumps({"kind": "action", "span_id": "s"}),
    ]
    (tmp_path / "future.jsonl").write_text("\n".join(lines) + "\n")
    spans, stats = _read_all(tmp_path)
    assert spans == []
    assert stats.files_skipped == 1
    assert any("unsupported trace schema" in w for w in stats.warnings)


def test_reader_empty_dir_is_explicit_not_crash(tmp_path):
    spans, stats = _read_all(tmp_path)
    assert spans == []
    assert any("no trace files" in w for w in stats.warnings)


def test_reader_records_file_and_line_provenance(tmp_path):
    rt.configure(str(tmp_path))
    with rt.stoa_span("action"):
        pass
    rt.shutdown()
    (span,), _ = _read_all(tmp_path)
    assert span["_trace_file"].startswith("trace-")
    assert span["_trace_line"] == 2  # line 1 is the header


# --- performance smoke -----------------------------------------------------------


def test_hot_path_overhead_budget(tmp_path):
    """Documented budget: ~50µs typical per span on the hot path. The test
    asserts a deliberately loose 1ms median so slow CI machines never flake;
    a regression to blocking I/O on the hot path would blow past this."""
    rt.configure(str(tmp_path))
    durations = []
    for _ in range(500):
        start = time.perf_counter()
        with rt.stoa_span("tool_call", tool="t"):
            pass
        durations.append(time.perf_counter() - start)
    rt.shutdown()
    durations.sort()
    assert durations[len(durations) // 2] < 0.001


def test_static_scanner_never_imports_runtime():
    """`stoa scan` must work with the runtime package absent/broken: no
    static-toolchain module may import stoa.runtime at module level."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import stoa.scanner, stoa.cli, stoa.report_json, stoa.report_html\n"
        "bad = [m for m in sys.modules if m.startswith('stoa.runtime')]\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()

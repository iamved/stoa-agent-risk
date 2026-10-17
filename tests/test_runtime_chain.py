"""Trace chain (stoa-trace/1.1): canonical form, hashing, key grades,
verification, and tamper detection."""

from __future__ import annotations

import json

import pytest

from stoa import runtime as rt
from stoa.runtime.chain import canonical_json, chain_record, record_hash, verify_dir, verify_file
from stoa.runtime.keys import HmacSigner, Signer, load_signer, parse_key

HMAC = "hmac:" + "ab" * 16


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    yield
    rt.shutdown()


def _write(tmp_path, spans=3, key=HMAC):
    rt.configure(str(tmp_path), agent_id="a09ff38687e9", signing_key=key)
    for i in range(spans):
        with rt.stoa_span("action", tool=f"t{i}"):
            pass
    rt.flush()
    rt.shutdown()
    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    return files[0]


def test_canonical_json_is_stable_and_excludes_hash_sig_and_provenance():
    a = {"b": 1, "a": {"z": "é", "y": [1, 2]}, "hash": "x", "sig": "y", "_trace_file": "f"}
    b = {"a": {"y": [1, 2], "z": "é"}, "b": 1}
    assert canonical_json(a) == canonical_json(b) == '{"a":{"y":[1,2],"z":"é"},"b":1}'
    assert record_hash(a, "") == record_hash(b, "")
    assert record_hash(a, "") != record_hash(a, "prev")


def test_every_record_links_to_the_previous_one(tmp_path):
    path = _write(tmp_path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["kind"] == "header" and records[0]["prev_hash"] == ""
    assert records[0]["key_grade"] == "hmac-sha256"
    for prev, cur in zip(records, records[1:]):
        assert cur["prev_hash"] == prev["hash"]
        assert cur["hash"] == record_hash(cur, cur["prev_hash"])
        assert cur["sig"] and cur["signer_fingerprint"] == records[0]["signer_fingerprint"]


def test_verify_passes_with_the_key_and_reports_grade(tmp_path):
    path = _write(tmp_path)
    report = verify_file(path, HMAC)
    assert report.ok and report.records == 4 and report.signed == 4
    assert report.key_grade == "hmac-sha256" and len(report.signer_fingerprints) == 1
    assert verify_dir(tmp_path, HMAC).ok
    assert rt.verify_chain(str(tmp_path), HMAC).to_dict()["ok"] is True


def test_mutated_record_breaks_the_chain_at_that_line(tmp_path):
    path = _write(tmp_path)
    lines = path.read_text().splitlines()
    record = json.loads(lines[2])
    record["tool"] = "something_else"
    lines[2] = json.dumps(record, separators=(",", ":"), sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    report = verify_file(path, HMAC)
    assert report.first_break == 3 and "hash" in report.break_reason


def test_deleted_line_breaks_the_chain(tmp_path):
    path = _write(tmp_path)
    lines = path.read_text().splitlines()
    del lines[2]
    path.write_text("\n".join(lines) + "\n")
    report = verify_file(path, HMAC)
    assert report.first_break == 3 and "prev_hash" in report.break_reason


def test_wrong_key_fails_the_signature_not_the_chain(tmp_path):
    path = _write(tmp_path)
    report = verify_file(path, "hmac:" + "cd" * 16)
    assert report.first_break == 1 and "signature" in report.break_reason


def test_no_key_is_grade_none_and_still_chained(tmp_path):
    path = _write(tmp_path, key=None)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["key_grade"] == "none" and records[1]["sig"] is None
    report = verify_file(path)
    assert report.ok and report.signed == 0 and report.key_grade == "none"


def test_pre_1_1_file_is_unchained_not_broken(tmp_path):
    path = tmp_path / "trace-old.jsonl"
    path.write_text(json.dumps({"kind": "header", "schema": "stoa-trace/1.0", "redaction": "redacted"}) + "\n"
                    + json.dumps({"kind": "action", "trace_id": "t", "span_id": "s", "start_ts": "x", "end_ts": "y", "status": "ok", "redaction": "redacted"}) + "\n")
    report = verify_file(path)
    assert report.ok and report.unchained


def test_key_specs_and_fail_open_loading(monkeypatch):
    assert isinstance(parse_key(HMAC), HmacSigner)
    assert parse_key(None).grade == "none"
    with pytest.raises(ValueError):
        parse_key("rot13:abc")
    with pytest.warns(RuntimeWarning):
        assert load_signer("rot13:abc").grade == "none"
    monkeypatch.setenv("STOA_SIGNING_KEY", HMAC)
    assert load_signer().grade == "hmac-sha256"
    assert isinstance(Signer(), Signer)


def test_ed25519_grade_needs_the_extra_or_says_so():
    pytest.importorskip("cryptography", reason="ed25519 grade needs the [runtime] extra")
    signer = parse_key("ed25519:" + "11" * 32)
    assert signer.grade == "ed25519" and signer.public_key_hex
    h = "ab" * 32
    assert signer.verify(h, signer.sign(h))
    assert not signer.verify(h, "00" * 64)


def test_ed25519_without_the_extra_degrades_with_a_warning(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("no cryptography")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.warns(RuntimeWarning):
        assert load_signer("ed25519:" + "11" * 32).grade == "none"


def test_chain_record_sets_the_four_fields():
    record = chain_record({"kind": "x"}, "", HmacSigner(b"k"))
    assert set(("prev_hash", "hash", "sig", "signer_fingerprint")) <= set(record)

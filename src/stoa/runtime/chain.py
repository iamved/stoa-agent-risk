"""Hash chaining and signing for trace files (``stoa-trace/1.1``).

Every record in a file, the header included, carries:

- ``prev_hash``  the ``hash`` of the record before it (``""`` for the header);
- ``hash``       ``sha256(canonical_json(record without hash/sig) + prev_hash)``;
- ``sig``        the signature over ``hash`` under the configured key, or
                 ``null`` at grade ``none``;
- ``signer_fingerprint``  which key signed it (``null`` at grade ``none``).

The chain runs per file and starts at the header, so one trace file is one
verifiable unit; rotation starts a new chain. ``verify_dir`` reports the
first break per file: a mutated record, a deleted or reordered line, or a
signature that fails under the key the header names. Chaining happens on
the exporter's background thread, never on the hot path.

``canonical_json`` is the one serialization both sides agree on: sorted
keys, no whitespace, UTF-8 preserved. Reader-added provenance fields
(``_trace_file``, ``_trace_line``) are never part of it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .keys import Signer, verifier_for_header

CHAIN_FIELDS = ("prev_hash", "hash", "sig", "signer_fingerprint")
GENESIS = ""


def canonical_json(record: dict) -> str:
    body = {
        k: v for k, v in record.items()
        if k not in ("hash", "sig") and not k.startswith("_")
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(record: dict, prev_hash: str) -> str:
    return hashlib.sha256((canonical_json(record) + prev_hash).encode("utf-8")).hexdigest()


def chain_record(record: dict, prev_hash: str, signer: Signer) -> dict:
    """Return ``record`` with the four chain fields set. Mutates and returns
    the same dict (the exporter owns it by then)."""
    record["prev_hash"] = prev_hash
    record["signer_fingerprint"] = signer.fingerprint
    record["hash"] = record_hash(record, prev_hash)
    record["sig"] = signer.sign(record["hash"])
    return record


@dataclass
class FileReport:
    file: str
    records: int = 0
    signed: int = 0
    key_grade: str = "none"
    signer_fingerprints: list = field(default_factory=list)
    first_break: int | None = None
    break_reason: str | None = None
    unchained: bool = False

    @property
    def ok(self) -> bool:
        return self.first_break is None


@dataclass
class ChainReport:
    directory: str
    files: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.files)

    @property
    def records(self) -> int:
        return sum(f.records for f in self.files)

    @property
    def broken(self) -> list:
        return [f for f in self.files if not f.ok]

    def to_dict(self) -> dict:
        return {
            "schema": "runtime-chain/1.0",
            "directory": self.directory,
            "ok": self.ok,
            "records": self.records,
            "files": [
                {
                    "file": f.file, "ok": f.ok, "records": f.records, "signed": f.signed,
                    "key_grade": f.key_grade, "signer_fingerprints": f.signer_fingerprints,
                    "first_break": f.first_break, "break_reason": f.break_reason,
                    "unchained": f.unchained,
                }
                for f in self.files
            ],
        }


def _claims_chain(header: dict) -> bool:
    """True when the header's schema is 1.1 or later, so a missing hash is a break."""
    schema = str(header.get("schema") or "")
    try:
        major, minor = schema.rsplit("/", 1)[-1].split(".")[:2]
        return int(major) > 1 or (int(major) == 1 and int(minor) >= 1)
    except (ValueError, IndexError):
        return False


def verify_file(path: str | Path, key: str | None = None) -> FileReport:
    """Walk one file's chain. A pre-1.1 file (no chain fields at all) is
    reported ``unchained`` and not as broken: there was nothing to verify."""
    path = Path(path)
    report = FileReport(file=path.name)
    prev = GENESIS
    verifier: Signer | None = None
    fingerprints: set[str] = set()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("not an object")
            except (json.JSONDecodeError, ValueError):
                report.first_break, report.break_reason = line_no, "unparseable line"
                return report
            report.records += 1
            if "hash" not in record:
                if line_no == 1 and record.get("kind") == "header" and not _claims_chain(record):
                    report.unchained = True
                    report.key_grade = "none"
                    return report  # a 1.0 file: nothing to verify
                report.first_break, report.break_reason = line_no, "record carries no hash"
                return report
            if verifier is None:
                header = record if record.get("kind") == "header" else {}
                report.key_grade = header.get("key_grade") or "none"
                verifier = verifier_for_header(header, key)
            if record.get("prev_hash") != prev:
                report.first_break, report.break_reason = line_no, "prev_hash does not match the previous record"
                return report
            expected = record_hash(record, prev)
            if record.get("hash") != expected:
                report.first_break, report.break_reason = line_no, "hash does not match the record"
                return report
            if record.get("signer_fingerprint"):
                fingerprints.add(record["signer_fingerprint"])
            if verifier.grade != "none":
                if verifier.grade == "hmac-sha256" and not key and verifier.fingerprint is None:
                    pass  # no secret available: the hash chain was checked, the signature cannot be
                elif not verifier.verify(record["hash"], record.get("sig")):
                    report.first_break, report.break_reason = line_no, f"signature does not verify ({verifier.grade})"
                    return report
                else:
                    report.signed += 1
            prev = record["hash"]
    report.signer_fingerprints = sorted(fingerprints)
    return report


def verify_dir(traces_dir: str | Path, key: str | None = None) -> ChainReport:
    directory = Path(traces_dir)
    report = ChainReport(directory=str(directory))
    if not directory.is_dir():
        return report
    for path in sorted(p for p in directory.glob("*.jsonl") if p.is_file()):
        report.files.append(verify_file(path, key))
    return report

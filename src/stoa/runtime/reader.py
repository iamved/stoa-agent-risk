"""Streaming trace reader — generator-based, fail-open on every line.

Analysis must handle ≥100k spans without pathological memory use, so this
never slurps a file: it yields one span dict at a time. Every failure mode
degrades gracefully and is *counted*, never silent:

- unreadable file            → warning recorded, file skipped
- malformed JSON line        → counted in ``stats.bad_lines``, line skipped
- missing header line        → counted, file still read (assume current schema)
- unknown schema **major**   → warning recorded, file skipped (misreading
  spans would be worse than ignoring them)
- newer schema **minor**     → read anyway (additive-first, house style)

Files are read in sorted name order so identical trace input always yields
an identical span sequence — the analysis determinism invariant starts here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .spans import SPAN_KINDS, TRACE_SCHEMA

_CURRENT_MAJOR = TRACE_SCHEMA.rsplit("/", 1)[1].split(".")[0]


@dataclass
class TraceReadStats:
    """Mutated in place while the generator is consumed."""

    files_read: int = 0
    files_skipped: int = 0
    spans_read: int = 0
    bad_lines: int = 0
    headers_missing: int = 0
    dropped_spans_reported: int = 0
    redaction_modes: set = field(default_factory=set)
    warnings: list = field(default_factory=list)


class TraceReader:
    """``reader = TraceReader(dir); for span in reader.spans(): ...`` —
    consult ``reader.stats`` after (or during) consumption."""

    def __init__(self, traces_dir: str | Path) -> None:
        self.traces_dir = Path(traces_dir)
        self.stats = TraceReadStats()

    def trace_files(self) -> list[Path]:
        if not self.traces_dir.is_dir():
            return []
        return sorted(p for p in self.traces_dir.glob("*.jsonl") if p.is_file())

    def spans(self):
        files = self.trace_files()
        if not files:
            self.stats.warnings.append(
                f"no trace files (*.jsonl) found under {self.traces_dir}"
            )
            return
        for path in files:
            yield from self._read_file(path)

    def _read_file(self, path: Path):
        try:
            handle = open(path, "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            self.stats.files_skipped += 1
            self.stats.warnings.append(f"cannot read {path.name}: {exc}")
            return
        with handle:
            first = True
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("not an object")
                except (json.JSONDecodeError, ValueError):
                    self.stats.bad_lines += 1
                    first = False
                    continue

                if first:
                    first = False
                    if record.get("kind") == "header":
                        if not self._accept_header(path, record):
                            return  # unknown major: skip rest of file
                        continue
                    self.stats.headers_missing += 1
                    self.stats.warnings.append(
                        f"{path.name}: no header line; assuming {TRACE_SCHEMA}"
                    )
                    # fall through: this first line is a span

                if record.get("kind") == "header":  # rotation artifact mid-file
                    self._accept_header(path, record)
                    continue
                if record.get("kind") not in SPAN_KINDS:
                    self.stats.bad_lines += 1
                    continue
                record["_trace_file"] = path.name
                record["_trace_line"] = line_no
                self.stats.spans_read += 1
                yield record
            self.stats.files_read += 1

    def _accept_header(self, path: Path, header: dict) -> bool:
        schema = str(header.get("schema", ""))
        major = schema.rsplit("/", 1)[-1].split(".")[0] if "/" in schema else ""
        if major and major != _CURRENT_MAJOR:
            self.stats.files_skipped += 1
            self.stats.warnings.append(
                f"{path.name}: unsupported trace schema {schema!r} "
                f"(this stoa reads {TRACE_SCHEMA}); file skipped"
            )
            return False
        mode = header.get("redaction")
        if mode:
            self.stats.redaction_modes.add(mode)
        self.stats.dropped_spans_reported += int(header.get("dropped_spans") or 0)
        return True

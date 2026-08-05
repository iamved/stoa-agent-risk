"""JSONL trace exporter: buffered, rotating, and fail-open by design.

Hot-path contract (the part that runs inside the customer's agent process):
``emit()`` is a dict append to a bounded queue — no I/O, no locks beyond the
queue's own, no exceptions escaping. A background daemon thread drains the
queue and appends JSONL to files under the customer's configured trace
directory. If the queue is full the span is dropped and counted (the count
is flushed into the next file header on rotation); if a write ever fails
(read-only filesystem, disk full), the exporter warns once via
``warnings.warn`` and becomes a permanent no-op. Instrumentation must never
crash or block the customer's agent — a lost span is always preferable to a
broken production process.

Zero telemetry: this module writes to the local filesystem only. There is no
network code anywhere in it.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import warnings
from pathlib import Path

from .spans import header_record

DEFAULT_MAX_FILE_BYTES = 16 * 1024 * 1024
_QUEUE_MAX = 10_000
_BATCH_MAX = 256
_POLL_SECONDS = 0.2


class JSONLExporter:
    """Append spans as JSONL under ``trace_dir``, rotating by size."""

    def __init__(
        self,
        trace_dir: str | Path,
        *,
        sdk_version: str,
        redaction: str = "redacted",
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self._trace_dir = Path(trace_dir)
        self._sdk_version = sdk_version
        self._redaction = redaction
        self._max_file_bytes = max_file_bytes
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAX)
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._failed = False
        self._warned = False
        self._handle = None
        self._bytes_written = 0
        self._seq = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="stoa-trace-exporter", daemon=True
        )
        self._thread.start()

    # --- hot path ----------------------------------------------------------

    def emit(self, span: dict) -> None:
        """Enqueue one span. Never raises, never blocks, never does I/O."""
        if self._failed:
            return
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            with self._dropped_lock:
                self._dropped += 1
        except Exception:  # noqa: BLE001 - instrumentation must never raise
            pass

    # --- background thread ---------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            batch: list[dict] = []
            try:
                batch.append(self._queue.get(timeout=_POLL_SECONDS))
            except queue.Empty:
                continue
            while len(batch) < _BATCH_MAX:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()

    def _write_batch(self, batch: list[dict]) -> None:
        if self._failed:
            return
        try:
            for span in batch:
                if self._handle is None or self._bytes_written >= self._max_file_bytes:
                    self._rotate()
                line = json.dumps(span, separators=(",", ":"), sort_keys=True) + "\n"
                encoded = line.encode("utf-8")
                self._handle.write(encoded)
                self._bytes_written += len(encoded)
            self._handle.flush()
        except Exception as exc:  # noqa: BLE001 - fail-open, warn loudly, once
            self._failed = True
            if not self._warned:
                self._warned = True
                warnings.warn(
                    f"stoa.runtime: cannot write traces under {self._trace_dir} "
                    f"({exc!r}); tracing is now a no-op for this process.",
                    RuntimeWarning,
                    stacklevel=2,
                )

    def _rotate(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        pid = os.getpid()
        while True:
            path = self._trace_dir / f"trace-{pid}-{self._seq:04d}.jsonl"
            self._seq += 1
            if not path.exists():
                break
        self._handle = open(path, "ab")
        with self._dropped_lock:
            dropped, self._dropped = self._dropped, 0
        header = header_record(self._sdk_version, self._redaction, dropped)
        line = (json.dumps(header, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        self._handle.write(line)
        self._bytes_written = len(line)

    # --- lifecycle -----------------------------------------------------------

    def flush(self, timeout: float = 5.0) -> None:
        """Drain the queue (best-effort, bounded). Safe to call anytime.

        Polls ``unfinished_tasks`` rather than ``empty()``: a span leaves the
        queue *before* its batch is written, so ``empty()`` alone would let
        flush return with the last batch still in flight.
        """
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.start()
        try:
            while (
                self._queue.unfinished_tasks > 0
                and not deadline.is_set()
                and not self._failed
            ):
                deadline.wait(0.01)
        finally:
            timer.cancel()
        if self._handle is not None and not self._failed:
            try:
                self._handle.flush()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self.flush()
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None

    @property
    def failed(self) -> bool:
        return self._failed

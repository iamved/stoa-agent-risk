"""OTLP mirror for trace spans (the ``[runtime]`` extra).

The JSONL file stays the record (the chain lives there); this mirror sends
each span to the customer's own OpenTelemetry collector as well, as a
GenAI-style span with the attribute contract the design fixed:
``stoa.agent_id``, ``stoa.kind``, ``stoa.capability``, ``stoa.integration``,
``stoa.provider``, ``stoa.model``, ``stoa.amount``, ``stoa.currency``,
``stoa.approval_span_id``, ``stoa.redaction``, plus ``stoa.session_id``,
``stoa.enforcement``, ``stoa.flags`` and the ``gen_ai.*`` usage attributes
the SDK already writes. Content never leaves the process because the span
never held any.

Imports ``opentelemetry`` lazily and only when configured; without the
package, ``configure(exporter="otlp")`` warns once and keeps the file sink.
The endpoint is always the customer's (``otlp_endpoint`` or
``$OTEL_EXPORTER_OTLP_ENDPOINT``); there is no default remote URL.
"""

from __future__ import annotations

import os
import warnings

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
_SCALAR_FIELDS = ("kind", "agent_id", "capability", "integration", "provider", "model", "tool", "approval_span_id", "redaction", "session_id", "enforcement", "status", "trace_id", "span_id", "parent_span_id")


def span_attributes(span: dict) -> dict:
    """The flat attribute map one stoa span becomes. Pure; used by the mirror and the tests."""
    attrs: dict = {}
    for field in _SCALAR_FIELDS:
        value = span.get(field)
        if value is not None:
            attrs[f"stoa.{field}"] = str(value)
    amount = span.get("amount")
    if isinstance(amount, dict):
        attrs["stoa.amount"] = float(amount.get("amount", 0.0))
        attrs["stoa.currency"] = str(amount.get("currency", "USD"))
    cost = span.get("cost")
    if isinstance(cost, dict):
        attrs["gen_ai.usage.cost"] = float(cost.get("amount", 0.0))
    if span.get("model"):
        attrs["gen_ai.request.model"] = str(span["model"])
    if span.get("provider"):
        attrs["gen_ai.system"] = str(span["provider"])
    for key, value in (span.get("attrs") or {}).items():
        if key == "flags" and isinstance(value, list):
            attrs["stoa.flags"] = ",".join(str(v) for v in value)
        elif key.startswith("gen_ai."):
            attrs[key] = value
        elif isinstance(value, (str, int, float, bool)):
            attrs[f"stoa.attr.{key}"] = value
    if span.get("hash"):
        attrs["stoa.hash"] = str(span["hash"])
    return attrs


def _parse_ns(ts: str | None) -> int | None:
    if not ts:
        return None
    from datetime import datetime, timezone

    try:
        return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp() * 1e9)
    except ValueError:
        return None


class OtlpMirror:
    """Forward spans to an OTLP/HTTP collector. Fail-open: any error warns once and the mirror goes quiet."""

    def __init__(self, endpoint: str | None = None, *, service_name: str = "stoa-agent") -> None:
        self.endpoint = endpoint or os.environ.get(ENDPOINT_ENV)
        self._tracer = None
        self._provider = None
        self._failed = False
        self._warned = False
        if not self.endpoint:
            self._fail("no OTLP endpoint configured (otlp_endpoint or $OTEL_EXPORTER_OTLP_ENDPOINT)")
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            self._provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
            self._provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=self.endpoint)))
            self._tracer = self._provider.get_tracer("stoa.runtime")
            trace.set_tracer_provider(self._provider)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"opentelemetry not usable ({exc!r}); pip install stoa-agent-risk[runtime]")

    def _fail(self, reason: str) -> None:
        self._failed = True
        if not self._warned:
            self._warned = True
            warnings.warn(f"stoa.runtime: OTLP mirror off: {reason}. Traces still go to the JSONL file.", RuntimeWarning, stacklevel=3)

    @property
    def active(self) -> bool:
        return not self._failed and self._tracer is not None

    def emit(self, span: dict) -> None:
        if not self.active:
            return
        try:
            start, end = _parse_ns(span.get("start_ts")), _parse_ns(span.get("end_ts"))
            otel_span = self._tracer.start_span(f"stoa.{span.get('kind', 'span')}", start_time=start, attributes=span_attributes(span))
            otel_span.end(end_time=end)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"export failed ({exc!r})")

    def close(self) -> None:
        try:
            if self._provider is not None:
                self._provider.shutdown()
        except Exception:  # noqa: BLE001
            pass

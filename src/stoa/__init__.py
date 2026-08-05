"""Stoa: local-first AI agent inventory and risk scanner."""

__version__ = "0.5.0"

# 1.4: runtime trace overlay additions (runtime_evidence, liveness_state,
# trace_ref, top-level runtime block) — all optional, emitted only by
# `stoa runtime merge`; a plain scan differs from 1.3 output by this string
# alone (the documented additive-minor precedent, see SCHEMA.md).
SCHEMA_VERSION = "1.4"

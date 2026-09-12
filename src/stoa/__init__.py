"""Stoa: local-first AI agent inventory and risk scanner."""

__version__ = "0.7.0"

# 1.4: runtime trace overlay additions (runtime_evidence, liveness_state,
# trace_ref, top-level runtime block) — all optional, emitted only by
# `stoa runtime merge`; a plain scan differs from 1.3 output by this string
# alone (the documented additive-minor precedent, see SCHEMA.md).
# 1.5: regulatory crosswalk annotation layer — a `crosswalk` object on every
# finding, a top-level `crosswalk` version block, and a per-dimension roll-up
# on `dimension_summary`. Presentation/labeling only; dimension scores are
# byte-for-byte unchanged.
# 1.6: agents discovered in infrastructure code (IaC collector) carry
# `source`, `discovery_tier`, and `platform` — emitted only when non-default,
# so a code-only scan differs from 1.5 by this string alone.
SCHEMA_VERSION = "1.6"

"""Stoa: local-first AI agent inventory and risk scanner."""

__version__ = "0.7.4"

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
# 1.8: dashboard data contract — `repository.head_commit` ({hash, date} of
# HEAD, the commit's own date, never wall-clock), `score_before_controls`
# on every dimension entry (the score with control credit not yet
# subtracted; `score`/`exposure` unchanged), and a top-level `risk_register`
# echoing `[[risk_register]]` from stoa-declared.toml. All additive; a scan
# without git or declarations differs from 1.7 by this string and the one
# extra integer per dimension entry.
SCHEMA_VERSION = "1.8"

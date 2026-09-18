"""The Stoa dashboard: a self-contained multi-screen HTML view of a scan.

Three small modules, all pure over documents the scanner already writes:

* :mod:`envelope` wraps a registry (plus an optional diff and history) in a
  versioned ``stoa-dashboard/1.0`` document the compiled UI reads.
* :mod:`register` derives risk-register rows from the registry's dimension
  assessments and merges the ``[[risk_register]]`` block declared in
  ``stoa-declared.toml``.
* :mod:`history` keeps a short, per-commit trail of scan summaries under
  ``.stoa/history/`` for trend sparklines.

The UI is a view layer: nothing here recomputes, reweights, or alters any
score. The scanner is the source of truth.
"""

from .envelope import ENVELOPE_SCHEMA, build_envelope  # noqa: F401
from .history import HISTORY_SCHEMA, entry_from_registry, load_history, record_history  # noqa: F401
from .register import build_register  # noqa: F401

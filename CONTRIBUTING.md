# Contributing to Stoa

Thanks for your interest! Stoa is a local-first static scanner — contributions
that improve detection accuracy, reduce false positives, or harden secret
handling are especially welcome.

## Development setup

```bash
git clone https://github.com/iamved/stoa-agent-risk
cd stoa-agent-risk
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Ground rules

- **No secret leakage.** Raw secrets must never appear in any output surface;
  `tests/test_redaction.py` enforces this and new output paths need matching
  tests. Never commit realistic-looking credentials — test keys are assembled
  at runtime in `tests/conftest.py`.
- **Honest language.** Stoa reports candidates and evidence, never certainty.
  New rules and copy must follow the vocabulary in the README ("agent
  candidate", "control not observed", "call site").
- **Deterministic output.** JSON and HTML must be byte-identical for the same
  tree and config: no timestamps, sorted collections, atomic writes.
- **Declarative rules.** New detection patterns go in `src/stoa/rules.py`,
  compiled once, with tests for both matches and near-miss false positives.
- **Gating is conservative.** Only high-confidence findings from gate-eligible
  rules may fail a build. A rule that can't prove exploitability must not gate.

## Pull requests

- Run `pytest` locally; CI runs it on Python 3.10 and 3.12.
- Add or update tests for any behavior change.
- Schema changes to `stoa-registry.json` must follow the versioning policy in
  `SCHEMA.md` (additive → minor bump; breaking → major bump; reserved field
  names stay reserved).

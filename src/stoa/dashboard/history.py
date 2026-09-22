"""Per-commit scan summaries under ``.stoa/history/`` (trend sparklines).

An entry is a *summary*, never a full registry: the dashboard's trend line
needs a handful of numbers per scan, and full registries from older scanner
versions must not be diffed against the current one (rule-version skew —
see docs/diff.md). Entries are keyed by the short commit hash, so rescanning
the same commit overwrites its entry instead of adding a duplicate, and the
directory stays a pure function of which commits were scanned.

Without git metadata (``--no-git``, or not a repository) nothing is recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

HISTORY_SCHEMA = "stoa-history-entry/1.1"
HISTORY_DIR = Path(".stoa") / "history"


# 1.1: `agents` carries, per agent record, the few fields the dashboard's loss
# model reads, so the modeled loss can be drawn over past scans. Still a
# summary: no findings, no evidence, no paths beyond the record's own.
_LOSS_TOOL_KEYS = ("name", "money_action", "high_impact")
_LOSS_DECLARED_KEYS = ("economic_authority", "data_classes", "users", "autonomy_intent")


def _loss_inputs(agent: dict) -> dict:
    declared = agent.get("declared") or {}
    dims = (agent.get("dimension_assessment") or {}).get("dimensions") or []
    return {
        "id": agent["id"],
        "name": agent.get("name"),
        "display_name": agent.get("display_name"),
        "capabilities": list(agent.get("capabilities") or []),
        "tools": [{k: t.get(k) for k in _LOSS_TOOL_KEYS} for t in agent.get("tools") or []],
        "autonomy_level": {"level": (agent.get("autonomy_level") or {}).get("level")},
        "declared": {k: declared[k] for k in _LOSS_DECLARED_KEYS if k in declared} if declared else None,
        "dimension_assessment": {"dimensions": [
            {"id": d["id"], "score": d.get("score", 0), "controls_observed": list(d.get("controls_observed") or [])}
            for d in dims
        ]},
    }


def entry_from_registry(registry: dict) -> dict | None:
    """Summarize a registry document; None when it carries no head_commit."""
    repository = registry.get("repository") or {}
    head = repository.get("head_commit")
    if not head or not head.get("hash"):
        return None
    summary = registry.get("summary") or {}
    dims = (registry.get("dimension_summary") or {}).get("dimensions") or []
    return {
        "schema": HISTORY_SCHEMA,
        "git_ref": repository.get("git_ref"),
        "head_commit": {"hash": head["hash"], "date": head.get("date")},
        "scanner_version": (registry.get("tool") or {}).get("version"),
        "registry_schema_version": registry.get("schema_version"),
        "agent_candidates": summary.get("agent_candidates", 0),
        "findings": dict(summary.get("findings") or {}),
        "dimensions": [
            {
                "id": d["id"],
                "max_exposure": d.get("max_exposure"),
                "agents_elevated": d.get("agents_elevated", 0),
                "agents_moderate": d.get("agents_moderate", 0),
            }
            for d in dims
        ],
        "agents": [_loss_inputs(a) for a in registry.get("agents") or []],
    }


def _entry_sort_key(entry: dict) -> tuple:
    head = entry.get("head_commit") or {}
    return (head.get("date") or "", head.get("hash") or "")


def load_history(root: Path) -> list[dict]:
    """All readable entries, oldest first. Unreadable files are skipped."""
    directory = Path(root) / HISTORY_DIR
    if not directory.is_dir():
        return []
    entries: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") == HISTORY_SCHEMA:
            entries.append(data)
    entries.sort(key=_entry_sort_key)
    return entries


def record_history(root: Path, registry: dict, keep: int) -> Path | None:
    """Write this scan's entry and prune to the newest *keep*. Returns the
    written path, or None when nothing was recorded (no git, or keep == 0)."""
    if keep <= 0:
        return None
    entry = entry_from_registry(registry)
    if entry is None:
        return None
    directory = Path(root) / HISTORY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{entry['head_commit']['hash']}.json"
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    entries = [(p, json.loads(p.read_text(encoding="utf-8")))
               for p in directory.glob("*.json")]
    entries = [(p, e) for p, e in entries if isinstance(e, dict) and e.get("schema") == HISTORY_SCHEMA]
    entries.sort(key=lambda pe: _entry_sort_key(pe[1]))
    for stale_path, _ in entries[:-keep] if len(entries) > keep else []:
        try:
            stale_path.unlink()
        except OSError:
            pass
    return path

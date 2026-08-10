"""Report presentation config loader (Task 4).

Loads ``data/report.toml`` — versioned collapse/grouping thresholds for the
HTML report. Presentation only; never touches scoring. Override per-repo via
``stoa.toml`` ``[report] path`` (mirrors the crosswalk/taxonomy mechanism).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class ReportConfigError(Exception):
    """Invalid report config; maps to exit code 2."""


# Exposure tiers, worst first — shared vocabulary for the collapse threshold.
_TIER_RANK = {"severe": 3, "elevated": 2, "moderate": 1, "low": 0}


@dataclass(frozen=True)
class ReportConfig:
    id: str
    version: str
    fix_first_max: int
    fix_first_min_severity: str
    agent_collapse_below_tier: str
    contradiction_group_threshold: int
    dimension_proxy_merge: bool

    def tier_rank(self, tier: str) -> int:
        return _TIER_RANK.get(tier, 0)

    @property
    def collapse_rank(self) -> int:
        return _TIER_RANK.get(self.agent_collapse_below_tier, 1)


def _parse(data: dict, source: str) -> ReportConfig:
    meta = data.get("report", {})
    if not meta.get("id") or not meta.get("version"):
        raise ReportConfigError(f"{source}: [report] needs id and version")
    c = data.get("collapse", {})
    tier = str(c.get("agent_collapse_below_tier", "moderate"))
    if tier not in _TIER_RANK:
        raise ReportConfigError(
            f"{source}: agent_collapse_below_tier={tier!r} must be one of "
            f"{sorted(_TIER_RANK)}"
        )
    return ReportConfig(
        id=str(meta["id"]),
        version=str(meta["version"]),
        fix_first_max=int(c.get("fix_first_max", 5)),
        fix_first_min_severity=str(c.get("fix_first_min_severity", "high")),
        agent_collapse_below_tier=tier,
        contradiction_group_threshold=int(c.get("contradiction_group_threshold", 3)),
        dimension_proxy_merge=bool(c.get("dimension_proxy_merge", True)),
    )


@lru_cache(maxsize=1)
def default_report_config() -> ReportConfig:
    text = (resources.files("stoa") / "data" / "report.toml").read_text(encoding="utf-8")
    return _parse(tomllib.loads(text), "default report config")


def load_report_config(path: Path | None) -> ReportConfig:
    if path is None:
        return default_report_config()
    if not path.is_file():
        raise ReportConfigError(f"report config not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ReportConfigError(f"invalid report TOML in {path}: {exc}") from exc
    return _parse(data, str(path))

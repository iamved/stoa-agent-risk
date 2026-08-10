"""Regulatory crosswalk loader (Feature 1).

Loads ``data/crosswalk.toml`` — a versioned annotation layer mapping each
rule to one primary OWASP LLM Top 10 (2025) class and one primary EU AI Act
article, plus a plain-English "so what" gloss. This is presentation/labeling
only; it never participates in scoring (hard constraint 1).

Override per-repo via ``stoa.toml`` ``[crosswalk] path`` (mirrors the custom
dimension-taxonomy mechanism). Any rule the crosswalk does not map falls into
an explicit ``unmapped`` state that still renders — never silently dropped.
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


class CrosswalkError(Exception):
    """Invalid crosswalk file; maps to exit code 2."""


@dataclass(frozen=True)
class CrosswalkEntry:
    owasp_llm_2025: str  # "" is an honest blank, not a gap
    eu_ai_act: str
    relation: str  # "exposure" | "control-observed"
    so_what: str

    def to_dict(self) -> dict:
        return {
            "owasp_llm_2025": self.owasp_llm_2025 or None,
            "eu_ai_act": self.eu_ai_act or None,
            "relation": self.relation,
            "so_what": self.so_what,
        }


# The explicit state for a rule the crosswalk does not cover. Renders as
# "unmapped" everywhere rather than vanishing.
UNMAPPED = CrosswalkEntry(
    owasp_llm_2025="", eu_ai_act="", relation="unmapped",
    so_what="No regulatory crosswalk mapping is defined for this rule.",
)


@dataclass(frozen=True)
class Crosswalk:
    id: str
    version: str
    owasp_llm_version: str
    eu_ai_act_reference: str
    entries: dict[str, CrosswalkEntry]

    def entry(self, rule_id: str) -> CrosswalkEntry:
        return self.entries.get(rule_id, UNMAPPED)

    def version_block(self) -> dict:
        """Top-level registry block: attributes a mapping to a reviewed version."""
        return {
            "id": self.id,
            "version": self.version,
            "owasp_llm_version": self.owasp_llm_version,
            "eu_ai_act_reference": self.eu_ai_act_reference,
        }


_VALID_RELATIONS = {"exposure", "control-observed"}


def _parse(data: dict, source: str) -> Crosswalk:
    meta = data.get("crosswalk", {})
    if not meta.get("id") or not meta.get("version"):
        raise CrosswalkError(f"{source}: [crosswalk] needs id and version")
    entries: dict[str, CrosswalkEntry] = {}
    for rule_id, raw in (data.get("rules") or {}).items():
        if not isinstance(raw, dict):
            raise CrosswalkError(f"{source}: [rules.{rule_id}] must be a table")
        relation = raw.get("relation", "exposure")
        if relation not in _VALID_RELATIONS:
            raise CrosswalkError(
                f"{source}: [rules.{rule_id}].relation={relation!r} "
                f"must be one of {sorted(_VALID_RELATIONS)}"
            )
        entries[rule_id] = CrosswalkEntry(
            owasp_llm_2025=str(raw.get("owasp_llm_2025", "")),
            eu_ai_act=str(raw.get("eu_ai_act", "")),
            relation=relation,
            so_what=str(raw.get("so_what", "")),
        )
    return Crosswalk(
        id=str(meta["id"]),
        version=str(meta["version"]),
        owasp_llm_version=str(meta.get("owasp_llm_version", "")),
        eu_ai_act_reference=str(meta.get("eu_ai_act_reference", "")),
        entries=entries,
    )


@lru_cache(maxsize=1)
def default_crosswalk() -> Crosswalk:
    text = (resources.files("stoa") / "data" / "crosswalk.toml").read_text(encoding="utf-8")
    return _parse(tomllib.loads(text), "default crosswalk")


def load_crosswalk(path: Path | None) -> Crosswalk:
    if path is None:
        return default_crosswalk()
    if not path.is_file():
        raise CrosswalkError(f"crosswalk file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CrosswalkError(f"invalid crosswalk TOML in {path}: {exc}") from exc
    return _parse(data, str(path))


# All 10 OWASP LLM Top 10 (2025) classes, for the report's coverage strip.
# Order is the canonical LLM01..LLM10. Kept here (not in TOML) because it is
# a fixed external fact, not a per-repo mapping.
OWASP_LLM_2025 = (
    ("LLM01", "Prompt Injection"),
    ("LLM02", "Sensitive Information Disclosure"),
    ("LLM03", "Supply Chain"),
    ("LLM04", "Data and Model Poisoning"),
    ("LLM05", "Improper Output Handling"),
    ("LLM06", "Excessive Agency"),
    ("LLM07", "System Prompt Leakage"),
    ("LLM08", "Vector and Embedding Weaknesses"),
    ("LLM09", "Misinformation"),
    ("LLM10", "Unbounded Consumption"),
)

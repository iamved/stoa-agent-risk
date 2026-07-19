"""Configuration loading and validation for Stoa.

Precedence: CLI options > ``stoa.toml`` > built-in defaults.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from .models import SEVERITIES
from .rules import RULES, VALID_RULE_ID

FAIL_LEVELS = ("none", "high", "critical")

DEFAULT_INCLUDE_EXTENSIONS = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")

DEFAULT_IGNORE_PATHS = (
    ".git/**",
    ".venv/**",
    "venv/**",
    "env/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".next/**",
    "coverage/**",
    "vendor/**",
    "third_party/**",
    "generated/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "*.min.js",
    "*.bundle.js",
)


class ConfigError(Exception):
    """Raised for invalid configuration; maps to exit code 2."""


@dataclass
class StoaConfig:
    """Effective scan configuration after merging all sources."""

    fail_on: str = "none"
    fail_on_new: str = "critical"
    max_file_bytes: int = 1_000_000
    follow_symlinks: bool = False
    respect_gitignore: bool = True
    include_extensions: tuple[str, ...] = DEFAULT_INCLUDE_EXTENSIONS
    ignore_paths: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATHS))
    extra_includes: list[str] = field(default_factory=list)
    extra_excludes: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)
    enabled_rules: dict[str, bool] = field(default_factory=dict)
    include_suppressed_in_json: bool = True

    def rule_enabled(self, rule_id: str) -> bool:
        return self.enabled_rules.get(rule_id, True)

    def effective_severity(self, rule_id: str) -> str:
        return self.severity_overrides.get(rule_id, RULES[rule_id].default_severity)


def _validate_rule_table(table: dict, section: str) -> None:
    for rule_id in table:
        if not VALID_RULE_ID.match(str(rule_id)) or rule_id not in RULES:
            raise ConfigError(
                f"Unknown rule ID {rule_id!r} in [{section}] of stoa.toml. "
                f"Known rules: {', '.join(sorted(RULES))}"
            )


def load_config(root: Path, config_path: Path | None = None) -> StoaConfig:
    """Load ``stoa.toml`` from *config_path* or *root*, merged over defaults."""
    config = StoaConfig()
    path = config_path if config_path is not None else root / "stoa.toml"
    if not path.is_file():
        if config_path is not None:
            raise ConfigError(f"Config file not found: {config_path}")
        return config

    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

    if "fail_on" in data:
        config.fail_on = _validated_level(data["fail_on"], "fail_on")
    if "fail_on_new" in data:
        config.fail_on_new = _validated_level(data["fail_on_new"], "fail_on_new")
    if "max_file_bytes" in data:
        if not isinstance(data["max_file_bytes"], int) or data["max_file_bytes"] <= 0:
            raise ConfigError("max_file_bytes must be a positive integer")
        config.max_file_bytes = data["max_file_bytes"]
    if "follow_symlinks" in data:
        config.follow_symlinks = bool(data["follow_symlinks"])
    if "respect_gitignore" in data:
        config.respect_gitignore = bool(data["respect_gitignore"])
    if "include_extensions" in data:
        exts = data["include_extensions"]
        if not isinstance(exts, list) or not all(isinstance(e, str) for e in exts):
            raise ConfigError("include_extensions must be a list of strings")
        config.include_extensions = tuple(exts)
    if "ignore_paths" in data:
        patterns = data["ignore_paths"]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ConfigError("ignore_paths must be a list of strings")
        config.ignore_paths = list(DEFAULT_IGNORE_PATHS) + patterns
    if "include_suppressed_in_json" in data:
        config.include_suppressed_in_json = bool(data["include_suppressed_in_json"])

    severity = data.get("severity", {})
    if severity:
        _validate_rule_table(severity, "severity")
        for rule_id, level in severity.items():
            if level not in SEVERITIES:
                raise ConfigError(
                    f"Invalid severity {level!r} for {rule_id}; expected one of {SEVERITIES}"
                )
            config.severity_overrides[rule_id] = level

    rules = data.get("rules", {})
    if rules:
        _validate_rule_table(rules, "rules")
        for rule_id, enabled in rules.items():
            config.enabled_rules[rule_id] = bool(enabled)

    return config


def _validated_level(value: object, key: str) -> str:
    if value not in FAIL_LEVELS:
        raise ConfigError(f"{key} must be one of {FAIL_LEVELS}, got {value!r}")
    return str(value)

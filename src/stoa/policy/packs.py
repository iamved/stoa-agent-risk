"""The shipped policy packs, read from ``stoa/policy/packs/*.toml``."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from .schema import PolicyDocument, validate_document

PACK_NAMES = ("baseline", "payments", "data", "exec", "tools-mcp", "fintech-regulated")


def pack_path(name: str) -> Path:
    if name not in PACK_NAMES:
        raise KeyError(name)
    return Path(str(resources.files("stoa.policy").joinpath("packs", f"{name}.toml")))


def load_pack(name: str) -> PolicyDocument:
    document = validate_document(pack_path(name).read_text(encoding="utf-8"), f"pack:{name}")
    for policy in document.policies:
        policy.pack = name
    return document

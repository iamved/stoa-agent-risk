"""Evidence renderer.

Copies the source submission into the packet and writes a SHA-256 manifest
listing every output file in the packet with its hash. The manifest is the
audit anchor: it lets a reviewer confirm exactly which submission produced
exactly which artifacts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_submission(submission_path: str, out_dir: Path) -> Path:
    """Copy the raw submission JSON into the packet."""
    dest = out_dir / "submission.json"
    shutil.copyfile(submission_path, dest)
    return dest


def write_manifest(out_dir: Path, submission: dict[str, Any]) -> Path:
    """Write manifest.json: every file in out_dir (except the manifest itself)
    with size and SHA-256, plus the submission's own scan hash for traceability.
    """
    out_dir = Path(out_dir)
    entries = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            entries.append(
                {
                    "file": str(p.relative_to(out_dir)),
                    "sha256": _sha256(p),
                    "bytes": p.stat().st_size,
                }
            )
    manifest = {
        "packet_for": submission.get("business_context", {})
        .get("company", {})
        .get("name"),
        "registry_scan_hash": submission.get("meta", {}).get("registry_scan_hash"),
        "sample_data": submission.get("meta", {}).get("sample_data", False),
        "files": entries,
    }
    dest = out_dir / "manifest.json"
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return dest

"""Run the Meridian end-to-end feature driver as an integration test.

Skipped when the `stoa` CLI or `git` is unavailable. Exercises the whole tool
surface (scan, dimensions, SARIF, diff, approve, gates, redaction) via
examples/meridian-ops/run-e2e.sh and asserts every check passes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[1] / "examples" / "meridian-ops" / "run-e2e.sh"


def _stoa_under_test() -> str | None:
    """The stoa installed alongside the interpreter running the tests."""
    candidate = Path(sys.executable).parent / "stoa"
    if candidate.exists():
        return str(candidate)
    return shutil.which("stoa")


@pytest.mark.skipif(_stoa_under_test() is None, reason="stoa CLI not available")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_meridian_end_to_end():
    assert DRIVER.is_file(), "e2e driver missing"
    env = {**os.environ, "STOA": _stoa_under_test()}
    result = subprocess.run(
        ["bash", str(DRIVER)],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    tail = "\n".join(result.stdout.splitlines()[-40:])
    assert result.returncode == 0, f"e2e driver failed:\n{tail}\n{result.stderr[-2000:]}"
    assert "0 failed" in result.stdout, tail

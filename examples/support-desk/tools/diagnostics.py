"""Operational diagnostics the escalation agent can trigger."""

import subprocess
from pathlib import Path


def ping_upstream(host: str) -> bool:
    result = subprocess.run(["ping", "-c", "1", host], capture_output=True, timeout=10)
    return result.returncode == 0


def tail_error_log(lines: int = 50) -> str:
    log = Path("/var/log/support-desk/error.log")
    if not log.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8").splitlines()[-lines:])

"""The kill switch: a state file the SDK reads at every guarded call.

``.stoa/killswitch.json`` holds per-agent flags::

    {"agents": {"bc3db1f17013": {"reason": "duplicate refunds", "by": "@ved", "since": "..."}},
     "all": null,
     "drills": [{"agent_id": ..., "by": ..., "started": ..., "stopped": ..., "seconds_to_stop": 1.8}]}

``STOA_KILLSWITCH=agent1,agent2`` or ``STOA_KILLSWITCH=*`` overrides from
the environment. The SDK caches on file mtime, so a check is a stat call,
no polling thread. The kill switch stops the next guarded tool call (the
policy ``killswitch = true`` with ``action = "block"``), not the model call
already in flight; the drill measures exactly that gap.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_NAME = Path(".stoa") / "killswitch.json"
ENV = "STOA_KILLSWITCH"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def find_state(start: str | Path | None = None) -> Path:
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / ".stoa").is_dir():
            return directory / STATE_NAME
    return here / STATE_NAME


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("agents", {})
    data.setdefault("all", None)
    data.setdefault("drills", [])
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class KillSwitch:
    """Read side, with an mtime cache. Never raises."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else find_state()
        self._mtime: float | None = None
        self._data: dict = {"agents": {}, "all": None, "drills": []}

    def _refresh(self) -> dict:
        try:
            mtime = self.path.stat().st_mtime if self.path.is_file() else None
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            self._data = _read(self.path) if mtime is not None else {"agents": {}, "all": None, "drills": []}
        return self._data

    def is_killed(self, agent_id: str | None, agent_name: str | None = None) -> bool:
        env = os.environ.get(ENV, "")
        if env:
            wanted = {x.strip() for x in env.split(",") if x.strip()}
            if "*" in wanted or (agent_id and agent_id in wanted) or (agent_name and agent_name in wanted):
                return True
        data = self._refresh()
        if data.get("all"):
            return True
        return bool(agent_id and agent_id in (data.get("agents") or {})) or bool(agent_name and agent_name in (data.get("agents") or {}))

    def reason(self, agent_id: str | None) -> str:
        data = self._refresh()
        entry = (data.get("agents") or {}).get(agent_id or "") or data.get("all") or {}
        return str(entry.get("reason") or "kill switch set")


def kill(agent_id: str, *, reason: str, by: str, path: str | Path | None = None) -> dict:
    path = Path(path) if path else find_state()
    data = _read(path)
    entry = {"reason": reason, "by": by, "since": _now()}
    if agent_id == "*":
        data["all"] = entry
    else:
        data["agents"][agent_id] = entry
    _write(path, data)
    return entry


def release(agent_id: str, *, by: str, path: str | Path | None = None) -> bool:
    path = Path(path) if path else find_state()
    data = _read(path)
    had = False
    if agent_id == "*":
        had = data.get("all") is not None
        data["all"] = None
    elif agent_id in data["agents"]:
        had = True
        del data["agents"][agent_id]
    data.setdefault("releases", []).append({"agent_id": agent_id, "by": by, "at": _now()})
    _write(path, data)
    return had


def drill(agent_id: str, *, by: str, wait_for_stop, timeout: float = 30.0, path: str | Path | None = None) -> dict:
    """Set the flag, wait until ``wait_for_stop()`` reports the first blocked
    call (or time out), release, and record ``seconds_to_stop`` as evidence.
    ``wait_for_stop`` is a callable returning True once a blocked span is seen."""
    path = Path(path) if path else find_state()
    started = time.monotonic()
    kill(agent_id, reason="drill", by=by, path=path)
    stopped: float | None = None
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            if wait_for_stop():
                stopped = time.monotonic()
                break
            time.sleep(0.05)
    finally:
        release(agent_id, by=by, path=path)
    result = {"agent_id": agent_id, "by": by, "started": _now(), "seconds_to_stop": round(stopped - started, 3) if stopped else None, "timed_out": stopped is None}
    data = _read(path)
    data["drills"].append(result)
    _write(path, data)
    return result


def drills(path: str | Path | None = None) -> list[dict]:
    return list(_read(Path(path) if path else find_state()).get("drills") or [])

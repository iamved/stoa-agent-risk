"""Generate the dashboard fixtures from examples/meridian-pay.

Every fixture is produced by the real scanner over a real example tree, so
the UI is only ever designed against data Stoa can actually emit. Run from
the repo root:

    .venv/bin/python ui/fixtures/build.py

Outputs (all deterministic):

* meridian-pay.envelope.json  — head scan + diff against baseline + 3-entry
                                history + declared risk register
* meridian-pay.baseline.json  — the baseline registry the diff was taken against
* hostile.envelope.json       — head envelope with script-breaking strings
                                planted in every user-derived field class
* large.envelope.json         — head envelope inflated to 5,000 findings
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from stoa.config import load_config  # noqa: E402
from stoa.dashboard import build_envelope, entry_from_registry  # noqa: E402
from stoa.registry_diff import diff_registries  # noqa: E402
from stoa.report_json import build_document  # noqa: E402
from stoa.scanner import ScanOptions, run_scan  # noqa: E402

EXAMPLE = REPO_ROOT / "examples" / "meridian-pay"
OUT = Path(__file__).resolve().parent

HOSTILE = [
    "</script><script>alert(1)</script>",
    "<!-- comment --><img src=x onerror=alert(2)>",
    "line sep ator",
    "${{7*7}} {{constructor.constructor('alert(3)')()}}",
    "\"quoted\" 'and' `backticked` \\backslash",
]

# Fixture commits: hash + committer date, standing in for git metadata so the
# history and drift screens have real anchors. The dates are fixed text, never
# a wall-clock read, so the fixtures are reproducible.
COMMITS = {
    "baseline": ("a1b2c3d", "2026-07-21T09:12:44+00:00", "release/2026-07"),
    "middle": ("b7c8d9e", "2026-08-18T14:03:10+00:00", "release/2026-08"),
    "head": ("e4f5a6b", "2026-09-15T16:45:02+00:00", "main"),
}

REGISTER_BLOCK = '''
[[risk_register]]
risk_id = "unreviewed-high-impact-action/b8f0111742fc"
owner = "digital-servicing@meridian.example"
treatment = "mitigate"
rationale = "Dual approval on issue_refund and change_payout_account being added in Q4"
review_by = "2026-12-01"
status = "in_progress"

[[risk_register]]
risk_id = "mandate-overreach/f18cfdb42fdb"
owner = "platform-risk@meridian.example"
treatment = "transfer"
rationale = "Covered under the AI liability submission; evidence pack prepared from this scan"
review_by = "2026-11-15"
status = "open"

[[risk_register]]
risk_id = "boundary-leakage/000000000000"
owner = "someone@meridian.example"
treatment = "accept"
rationale = "Stale: this agent was removed two releases ago"
'''


def _scan(root: Path) -> dict:
    config = load_config(root)
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    document = build_document(result, config)
    # Declaration warnings from the loader name the file by absolute path;
    # strip the temporary scan root so the fixture is reproducible anywhere.
    prefix = str(root.resolve()) + "/"
    document["warnings"] = [w.replace(prefix, "") for w in document["warnings"]]
    return document


def _stamp(registry: dict, which: str) -> dict:
    hash_, date, ref = COMMITS[which]
    registry["repository"]["git_ref"] = hash_
    registry["repository"]["head_commit"] = {"hash": hash_, "date": date}
    registry["repository"]["name"] = "meridian-pay"
    return registry


def _variant(tmp: Path, name: str, *, drop_tools: list[str], max_per_action: int | None) -> Path:
    """Copy the example and shrink the account-actions agent's reach."""
    root = tmp / name
    shutil.copytree(EXAMPLE, root)
    agent = root / "code" / "agents" / "account_actions_agent.py"
    text = agent.read_text()
    for tool in drop_tools:
        text = text.replace(f", {tool}", "").replace(f"{tool}, ", "")
    agent.write_text(text)
    declared = root / "stoa-declared.toml"
    if max_per_action is not None:
        declared.write_text(
            declared.read_text().replace(
                "max_per_action = { amount = 500, currency = \"USD\" }",
                f"max_per_action = {{ amount = {max_per_action}, currency = \"USD\" }}",
            )
        )
    return root


def build(out: Path = OUT) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        baseline_root = _variant(tmp, "baseline", drop_tools=["issue_refund", "waive_fee", "reissue_card", "change_payout_account"], max_per_action=100)
        middle_root = _variant(tmp, "middle", drop_tools=["change_payout_account"], max_per_action=250)
        head_root = tmp / "head"
        shutil.copytree(EXAMPLE, head_root)
        with open(head_root / "stoa-declared.toml", "a") as handle:
            handle.write(REGISTER_BLOCK)

        baseline = _stamp(_scan(baseline_root), "baseline")
        middle = _stamp(_scan(middle_root), "middle")
        head = _stamp(_scan(head_root), "head")

    diff = diff_registries(baseline, head)
    history = [entry_from_registry(r) for r in (baseline, middle, head)]
    envelope = build_envelope(head, diff=diff, history=history)

    _write(out, "meridian-pay.baseline.json", baseline)
    _write(out, "meridian-pay.envelope.json", envelope)
    _write(out, "hostile.envelope.json", _hostile(envelope))
    _write(out, "large.envelope.json", _large(envelope, 5000))


def _hostile(envelope: dict) -> dict:
    env = copy.deepcopy(envelope)
    reg = env["registry"]
    i = 0

    def nxt() -> str:
        nonlocal i
        value = HOSTILE[i % len(HOSTILE)]
        i += 1
        return value

    reg["repository"]["name"] = "meridian-pay " + HOSTILE[0]
    reg["warnings"].append("warning " + HOSTILE[1])
    for agent in reg["agents"]:
        agent["display_name"] = agent["display_name"] + " " + nxt()
        if agent.get("declared"):
            agent["declared"]["purpose"] = nxt()
        for tool in agent.get("tools", []):
            tool["name"] = tool["name"] + nxt()
        for finding in agent["findings"]:
            finding["snippet"] = nxt() + " " + finding["snippet"]
            finding["title"] = finding["title"] + " " + nxt()
            finding["remediation"] = nxt()
            if finding.get("message"):
                finding["message"] = nxt()
            for step in finding.get("flow", []):
                step["snippet"] = nxt()
        for entry in agent["dimension_assessment"]["dimensions"]:
            entry["statement"] = nxt()
    for finding in reg["repository_findings"]:
        finding["snippet"] = HOSTILE[0]
        finding["path"] = "src/" + HOSTILE[2] + ".py"
    for row in env["register"]:
        if row["declared"]:
            row["declared"]["rationale"] = HOSTILE[0]
            row["declared"]["owner"] = HOSTILE[1]
    for rule in env["rules"].values():
        rule["remediation"] = rule["remediation"] + " " + HOSTILE[3]
    if env["diff"]:
        for entry in env["diff"]["agents"]["changed"]:
            entry["name"] = entry["name"] + HOSTILE[0]
    return env


def _large(envelope: dict, total: int) -> dict:
    """Inflate to *total* findings by cloning across agents with fresh
    fingerprints and lines. Register rows and dimension scores are left as
    the scanner produced them; this fixture is for table performance only."""
    env = copy.deepcopy(envelope)
    reg = env["registry"]
    agents = reg["agents"]
    templates = [f for a in agents for f in a["findings"]] + reg["repository_findings"]
    have = len(templates)
    n = 0
    while have + n < total:
        agent = agents[n % len(agents)]
        base = copy.deepcopy(templates[n % len(templates)])
        base["fingerprint"] = f"{n:016x}"
        base["line"] = 1 + (n * 7) % 900
        base["path"] = agent["path"]
        base["is_new"] = n % 11 == 0
        agent["findings"].append(base)
        n += 1
    counts: dict[str, int] = {}
    for a in agents:
        for f in a["findings"]:
            if not f.get("suppressed"):
                counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    for f in reg["repository_findings"]:
        if not f.get("suppressed"):
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    reg["summary"]["findings"] = {s: counts.get(s, 0) for s in ("critical", "high", "medium", "low", "info")}
    reg["repository"]["name"] = "meridian-pay-large"
    return env


def _write(out: Path, name: str, document: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        shown = path.relative_to(REPO_ROOT)
    except ValueError:
        shown = path
    print(f"wrote {shown} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)

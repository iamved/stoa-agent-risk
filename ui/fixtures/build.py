"""Generate the dashboard fixtures from examples/meridian-pay.

Every fixture is produced by the real scanner over a real example tree, so
the UI is only ever designed against data Stoa can actually emit. Run from
the repo root:

    .venv/bin/python ui/fixtures/build.py

Outputs (all deterministic):

* meridian-pay.envelope.json  — head scan + diff against baseline + 3-entry
                                history + declared risk register. The history
                                tells a story: in July and August the
                                account-actions agent capped amounts in code
                                and the support chatbot did not exist; the
                                September push removed the cap and added the
                                chatbot.
* meridian-pay.baseline.json  — the baseline registry the diff was taken against
* hostile.envelope.json       — head envelope with script-breaking strings
                                planted in every user-derived field class
* large.envelope.json         — head envelope inflated to 5,000 findings
* first-run.envelope.json     — what a customer's first `stoa scan` gives: no
                                stoa-declared.toml, no .stoa/underwriting.toml,
                                no baseline, no history
* no-agents.envelope.json     — a scan that finds no agent candidates at all
* two-stacks.envelope.json    — the example plus twins/account_actions.tf, so
                                account-actions is defined twice (code and a
                                Bedrock agent) and resolves to one agent; its
                                diff is against the same tree with the Bedrock
                                action group missing, a real authority increase
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from stoa.cli import _load_underwriting  # noqa: E402
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
risk_id = "mandate-overreach/bc3db1f17013"
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


def _stamp(registry: dict, which: str, name: str = "meridian-pay") -> dict:
    hash_, date, ref = COMMITS[which]
    registry["repository"]["git_ref"] = hash_
    registry["repository"]["head_commit"] = {"hash": hash_, "date": date}
    registry["repository"]["name"] = name
    return registry


def _first_run(tmp: Path) -> Path:
    """The example as a customer first meets it: code only, nothing declared."""
    root = tmp / "first-run"
    shutil.copytree(EXAMPLE, root)
    (root / "stoa-declared.toml").unlink()
    shutil.rmtree(root / ".stoa")
    return root


def _no_agents(tmp: Path) -> Path:
    root = tmp / "no-agents"
    root.mkdir()
    (root / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    return root


# The amount cap the earlier scans carried in code: a bounding construct the
# scanner recognises (autonomy bounded, not unrestricted). The September push
# removed it.
_CAP = (
    "MAX_PER_ACTION = {cap}  # hard cap, checked before any tool runs\n"
    "\n"
    "def act(state: MessagesState):\n"
    "    amount = state.get(\"amount\", 0)\n"
    "    if amount > MAX_PER_ACTION:\n"
    "        return {{\"messages\": [(\"assistant\", \"Above the cap. Escalating to a person.\")]}}\n"
)


def _variant(tmp: Path, name: str, *, cap: int, drop_tools: list[str], max_per_action: int) -> Path:
    """Copy the example as it stood before the September push: the support
    chatbot does not exist, and account-actions caps amounts in code."""
    root = tmp / name
    shutil.copytree(EXAMPLE, root)
    (root / "code" / "agents" / "support_agent.py").unlink()
    agent = root / "code" / "agents" / "account_actions_agent.py"
    text = agent.read_text()
    for tool in drop_tools:
        text = text.replace(f", {tool}", "").replace(f"{tool}, ", "")
    text = text.replace("def act(state: MessagesState):\n", _CAP.format(cap=cap), 1)
    assert "MAX_PER_ACTION" in text
    agent.write_text(text)
    declared = root / "stoa-declared.toml"
    toml = declared.read_text().replace(
        "max_per_action = { amount = 500, currency = \"USD\" }",
        f"max_per_action = {{ amount = {max_per_action}, currency = \"USD\" }}",
    )
    # The chatbot's declaration did not exist yet either.
    start = toml.index('[agents."bc3db1f17013"]')
    end = toml.find("\n[", start + 1)
    toml = toml[:start] + (toml[end + 1:] if end != -1 else "")
    declared.write_text(toml)
    return root


TWIN = Path(__file__).resolve().parent / "twins" / "account_actions.tf"
TWIN_DECLARATION = '''
[agents."ddb08fa73da1"]      # aws/account_actions.tf :: aws_bedrockagent_agent.account_actions
name = "meridian-account-actions"
same_as = ["b8f0111742fc"]
owner = "digital-servicing@meridian.example"
purpose = "Account actions on Bedrock"
users = "customers"
production_status = "production"
autonomy_intent = "human_approved"
data_classes = ["personal", "financial"]
'''


def _two_stacks(tmp: Path, name: str, *, action_group: bool) -> Path:
    """The example with account-actions also defined as a Bedrock agent."""
    root = tmp / name
    shutil.copytree(EXAMPLE, root)
    text = TWIN.read_text()
    if not action_group:
        text, n = re.subn(r'resource "aws_bedrockagent_agent_action_group" "account_tools" \{.*?\n\}\n', "", text, flags=re.S)
        assert n == 1
    (root / "aws" / "account_actions.tf").write_text(text)
    # Declared as the same agent as the code record, with the same intent, so the
    # contradiction fires on both records and the two resolve to one agent.
    with open(root / "stoa-declared.toml", "a") as handle:
        handle.write(TWIN_DECLARATION)
    return root


def build(out: Path = OUT) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        baseline_root = _variant(tmp, "baseline", cap=100, drop_tools=["change_payout_account"], max_per_action=100)
        middle_root = _variant(tmp, "middle", cap=250, drop_tools=[], max_per_action=250)
        head_root = tmp / "head"
        shutil.copytree(EXAMPLE, head_root)
        with open(head_root / "stoa-declared.toml", "a") as handle:
            handle.write(REGISTER_BLOCK)

        baseline = _stamp(_scan(baseline_root), "baseline")
        middle = _stamp(_scan(middle_root), "middle")
        head = _stamp(_scan(head_root), "head")
        underwriting = _load_underwriting(head_root, None)
        first_run_root = _first_run(tmp)
        first_run = _stamp(_scan(first_run_root), "head", "acme-support")
        first_run_underwriting = _load_underwriting(first_run_root, None)
        no_agents = _stamp(_scan(_no_agents(tmp)), "head", "acme-billing")
        two_stacks_base = _stamp(_scan(_two_stacks(tmp, "two-stacks-base", action_group=False)), "middle")
        two_stacks = _stamp(_scan(_two_stacks(tmp, "two-stacks", action_group=True)), "head")
        two_stacks_underwriting = _load_underwriting(head_root, None)

    diff = diff_registries(baseline, head)
    history = [entry_from_registry(r) for r in (baseline, middle, head)]
    envelope = build_envelope(head, diff=diff, baseline=baseline, history=history, underwriting=underwriting)

    _write(out, "meridian-pay.baseline.json", baseline)
    _write(out, "meridian-pay.envelope.json", envelope)
    _write(out, "hostile.envelope.json", _hostile(envelope))
    _write(out, "large.envelope.json", _large(envelope, 5000))
    _write(out, "first-run.envelope.json", build_envelope(first_run, underwriting=first_run_underwriting))
    _write(out, "no-agents.envelope.json", build_envelope(no_agents))
    _write(out, "two-stacks.envelope.json", build_envelope(
        two_stacks, diff=diff_registries(two_stacks_base, two_stacks), baseline=two_stacks_base,
        history=[entry_from_registry(r) for r in (two_stacks_base, two_stacks)], underwriting=two_stacks_underwriting))


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
    # Agents in one file share that file's findings; count unique fingerprints
    # so the target is 5,000 distinct findings, as the dashboard shows them.
    have = len({f["fingerprint"] for f in templates})
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

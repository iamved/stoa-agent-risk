"""Risk-rule detection: secrets, passwords, SQL, exceptions, HTTP, controls."""

from __future__ import annotations

from conftest import fake_anthropic_key, fake_openai_key

from stoa.config import StoaConfig
from stoa.risk_detection import detect_control_prompts, detect_risks


def scan(content: str, path: str = "src/app.py", language: str = "python",
         testlike: bool = False, config: StoaConfig | None = None):
    return detect_risks(content, path, language, testlike, config or StoaConfig())


def by_rule(findings, rule_id: str):
    return [f for f in findings if f.rule_id == rule_id]


# --- SEC001 -----------------------------------------------------------------

def test_openai_key_detected_high_confidence():
    key = fake_openai_key()
    findings = by_rule(scan(f'api_key = "{key}"'), "SEC001")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "critical"
    assert finding.confidence == "high"
    assert key not in finding.snippet
    assert "[REDACTED:" in finding.snippet


def test_anthropic_github_slack_stripe_keys_detected():
    keys = [
        fake_anthropic_key(),
        "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv",
        "xoxb-" + "1234567890-Ab1Cd2Ef3Gh4Ij5Kl6Mn7",
        "sk_live_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn",
    ]
    for key in keys:
        findings = by_rule(scan(f'token = "{key}"'), "SEC001")
        assert len(findings) == 1, key
        assert key not in findings[0].snippet


def test_placeholder_key_low_confidence():
    findings = by_rule(scan('key = "sk-proj-fakekeyforexampleuseonly00000"'), "SEC001")
    assert len(findings) == 1
    assert findings[0].confidence == "low"


def test_low_entropy_key_low_confidence():
    findings = by_rule(scan('key = "sk-proj-aaaaaaaaaaaaaaaaaaaaaaaaa"'), "SEC001")
    assert findings and findings[0].confidence == "low"


def test_key_in_comment_low_confidence():
    findings = by_rule(scan(f'# old key: {fake_openai_key()}'), "SEC001")
    assert findings and findings[0].confidence == "low"


def test_key_in_test_path_medium_confidence():
    findings = by_rule(
        scan(f'key = "{fake_openai_key()}"', path="tests/test_keys.py", testlike=True),
        "SEC001",
    )
    assert findings and findings[0].confidence == "medium"


def test_env_var_usage_not_flagged():
    findings = scan('api_key = os.environ["OPENAI_API_KEY"]')
    assert by_rule(findings, "SEC001") == []


def test_secret_manager_usage_not_flagged():
    findings = scan('api_key = secretsmanager.get_secret_value(SecretId="openai")')
    assert by_rule(findings, "SEC001") == []
    assert by_rule(findings, "SEC002") == []


# --- SEC002 -----------------------------------------------------------------

def test_hardcoded_password_detected():
    findings = by_rule(scan('db_password = "s3cureH0rse9Battery"'), "SEC002")
    assert len(findings) == 1
    assert findings[0].confidence == "high"
    assert findings[0].severity == "critical"


def test_password_from_environment_not_flagged():
    assert by_rule(scan('password = os.getenv("DB_PASSWORD")'), "SEC002") == []


def test_placeholder_password_not_flagged():
    assert by_rule(scan('password = "changeme"'), "SEC002") == []
    assert by_rule(scan('password = "example-password"'), "SEC002") == []


def test_empty_or_field_name_not_flagged():
    assert by_rule(scan('password = ""'), "SEC002") == []
    assert by_rule(scan("password_field_name = get_field()"), "SEC002") == []


# --- SEC003 -----------------------------------------------------------------

def test_sql_fstring_detected():
    findings = by_rule(scan('cursor.execute(f"SELECT * FROM users WHERE id = {uid}")'), "SEC003")
    assert len(findings) == 1


def test_sql_dot_format_detected():
    findings = by_rule(scan('q = "DELETE FROM users WHERE id = {}".format(uid)'), "SEC003")
    assert len(findings) == 1


def test_sql_percent_format_detected():
    findings = by_rule(scan('q = "SELECT name FROM users WHERE id = %s" % uid'), "SEC003")
    assert len(findings) == 1


def test_sql_concatenation_detected():
    findings = by_rule(scan("q = \"SELECT id FROM orders WHERE ref = '\" + ref"), "SEC003")
    assert len(findings) == 1


def test_js_template_literal_detected():
    findings = by_rule(
        scan("const q = `SELECT id FROM orders WHERE ref = ${ref}`;", language="javascript"),
        "SEC003",
    )
    assert len(findings) == 1


def test_parameterized_sql_not_flagged():
    findings = by_rule(
        scan('cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))'), "SEC003"
    )
    assert findings == []


# --- REL001 -----------------------------------------------------------------

def test_bare_except_pass_detected():
    content = "try:\n    work()\nexcept:\n    pass\n"
    assert len(by_rule(scan(content), "REL001")) == 1


def test_except_exception_pass_detected():
    content = "try:\n    work()\nexcept Exception:\n    pass\n"
    findings = by_rule(scan(content), "REL001")
    assert len(findings) == 1
    assert findings[0].severity == "medium"


def test_empty_js_catch_detected():
    content = "try { work(); } catch (err) {}"
    assert len(by_rule(scan(content, language="javascript"), "REL001")) == 1


def test_handled_exception_not_flagged():
    content = "try:\n    work()\nexcept Exception as exc:\n    logger.error(exc)\n"
    assert by_rule(scan(content), "REL001") == []


# --- NET001 -----------------------------------------------------------------

def test_localhost_http_not_flagged():
    for url in ("http://localhost:8000/api", "http://127.0.0.1/x", "http://0.0.0.0:9"):
        assert by_rule(scan(f'requests.get("{url}", timeout=5)'), "NET001") == [], url


def test_test_domain_http_not_flagged():
    assert by_rule(scan('u = "http://service.test/api"'), "NET001") == []
    assert by_rule(scan('u = "http://example.com/docs"'), "NET001") == []


def test_public_http_endpoint_flagged():
    findings = by_rule(scan('requests.get("http://api.partner-corp.com/v1", timeout=5)'), "NET001")
    assert len(findings) == 1


def test_http_in_comment_not_flagged():
    assert by_rule(scan("# see http://internal-wiki.corp.com/page"), "NET001") == []


# --- NET002 -----------------------------------------------------------------

def test_request_without_timeout_flagged():
    findings = by_rule(scan('requests.get("https://api.corp.com/v1")'), "NET002")
    assert len(findings) == 1
    assert "timeout was" not in findings[0].title  # observational title
    assert findings[0].title == "Request timeout not observed"


def test_request_with_timeout_not_flagged():
    assert by_rule(scan('requests.get("https://api.corp.com/v1", timeout=10)'), "NET002") == []


def test_multiline_timeout_not_flagged():
    content = 'requests.post(\n    "https://api.corp.com/v1",\n    json=data,\n    timeout=10,\n)\n'
    assert by_rule(scan(content), "NET002") == []


def test_multiline_timeout_on_fifth_line_not_flagged():
    content = (
        "requests.post(\n"
        '    "https://api.corp.com/v1",\n'
        "    json=data,\n"
        "    headers=headers,\n"
        "    auth=(user, token),\n"
        "    timeout=10,\n"
        ")\n"
    )
    assert by_rule(scan(content), "NET002") == []


# --- CTRL rules -------------------------------------------------------------

def test_control_prompts_emitted_once_per_category():
    findings = detect_control_prompts("agent = build()", "src/a.py", "agent", 1, StoaConfig())
    assert sorted(f.rule_id for f in findings) == ["CTRL001", "CTRL002", "CTRL003"]
    assert all(f.severity == "info" for f in findings)


def test_control_prompt_skipped_when_control_observed():
    content = "from limits import rate_limit\nvalidate(input)\nauthenticate(user)\n"
    assert detect_control_prompts(content, "src/a.py", "agent", 1, StoaConfig()) == []


def test_control_rule_disabled_by_config():
    config = StoaConfig()
    config.enabled_rules["CTRL003"] = False
    findings = detect_control_prompts("agent = build()", "src/a.py", "agent", 1, config)
    assert "CTRL003" not in {f.rule_id for f in findings}


# --- Config severity overrides ---------------------------------------------

def test_severity_override_applied():
    config = StoaConfig()
    config.severity_overrides["NET001"] = "info"
    findings = by_rule(
        scan('u = "http://api.partner-corp.com/x"', config=config), "NET001"
    )
    assert findings and findings[0].severity == "info"


def test_disabled_rule_not_emitted():
    config = StoaConfig()
    config.enabled_rules["SEC003"] = False
    findings = scan('cursor.execute(f"SELECT * FROM t WHERE id = {x}")', config=config)
    assert by_rule(findings, "SEC003") == []


# --- Detection coverage for modern stacks -----------------------------------

def test_ai_sdk_provider_factories_detected():
    from stoa.integration_detection import detect_providers

    assert "groq" in detect_providers("const g = createGroq({ apiKey: k });")
    assert "openai" in detect_providers("import { openai } from '@ai-sdk/openai';")
    assert "anthropic" in detect_providers("const a = createAnthropic({});")
    assert "xai" in detect_providers("import { xai } from '@ai-sdk/xai';")


def test_vector_db_capability_detected():
    from stoa.integration_detection import detect_capabilities

    assert "vector_search" in detect_capabilities("index = pc.Index('docs')")
    assert "vector_search" in detect_capabilities("from qdrant_client import QdrantClient")


def test_mcp_capability_detected():
    from stoa.integration_detection import detect_capabilities

    assert "mcp_tools" in detect_capabilities("mcp = FastMCP('tools')")


def test_vector_db_integrations_detected():
    from stoa.integration_detection import detect_integrations

    integrations, _ = detect_integrations(
        "from pinecone import Pinecone\nimport chromadb\nfrom qdrant_client import QdrantClient"
    )
    assert {"pinecone", "chroma", "qdrant"}.issubset(set(integrations))

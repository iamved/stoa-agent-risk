"""Declarative detection rules: compiled once, consumed everywhere.

This module owns every regular expression Stoa uses so that detection stays
declarative, reviewable, and free of catastrophic backtracking. Nothing here
performs I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleSpec:
    """Metadata for one risk rule."""

    rule_id: str
    title: str
    category: str
    default_severity: str
    gateable: bool
    remediation: str


RULES: dict[str, RuleSpec] = {
    "SEC001": RuleSpec(
        rule_id="SEC001",
        title="Possible hardcoded API credential",
        category="secret",
        default_severity="critical",
        gateable=True,
        remediation="Load the credential from a secret manager or environment variable.",
    ),
    "SEC002": RuleSpec(
        rule_id="SEC002",
        title="Possible hardcoded password",
        category="secret",
        default_severity="high",
        gateable=True,
        remediation="Load the password from a secret manager or environment variable.",
    ),
    "SEC003": RuleSpec(
        rule_id="SEC003",
        title="Interpolated SQL statement",
        category="injection",
        default_severity="high",
        gateable=False,
        remediation="Use parameterized queries instead of string interpolation.",
    ),
    "REL001": RuleSpec(
        rule_id="REL001",
        title="Swallowed exception",
        category="reliability",
        default_severity="medium",
        gateable=False,
        remediation="Handle or log the exception instead of silently discarding it.",
    ),
    "NET001": RuleSpec(
        rule_id="NET001",
        title="Insecure non-local HTTP endpoint",
        category="network",
        default_severity="medium",
        gateable=False,
        remediation="Use HTTPS for non-local endpoints.",
    ),
    "NET002": RuleSpec(
        rule_id="NET002",
        title="Request timeout not observed",
        category="network",
        default_severity="medium",
        gateable=False,
        remediation="Pass an explicit timeout so a hung upstream cannot stall the agent.",
    ),
    "CTRL001": RuleSpec(
        rule_id="CTRL001",
        title="Authentication control not observed",
        category="control",
        default_severity="info",
        gateable=False,
        remediation="Confirm authentication is enforced before this agent acts; it was not observed in this file.",
    ),
    "CTRL002": RuleSpec(
        rule_id="CTRL002",
        title="Input validation control not observed",
        category="control",
        default_severity="info",
        gateable=False,
        remediation="Confirm inputs are validated before this agent acts; validation was not observed in this file.",
    ),
    "CTRL003": RuleSpec(
        rule_id="CTRL003",
        title="Rate limiting control not observed",
        category="control",
        default_severity="info",
        gateable=False,
        remediation="Confirm rate limiting exists for this agent's actions; it was not observed in this file.",
    ),
}

VALID_RULE_ID = re.compile(r"^[A-Z]{3,5}\d{3}$")

# ---------------------------------------------------------------------------
# Agent-candidate evidence
# ---------------------------------------------------------------------------

HIGH_AGENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "langchain": re.compile(
        r"\b(?:AgentExecutor|initialize_agent|"
        r"create_(?:react|tool_calling|openai_functions)_agent)\s*\("
    ),
    "langgraph": re.compile(r"\b(?:create_react_agent|StateGraph)\s*\("),
    "crewai": re.compile(
        r"\bCrew\s*\(|\bAgent\s*\(\s*(?:role|goal|backstory)\s*="
    ),
    "autogen": re.compile(
        r"\b(?:AssistantAgent|ConversableAgent|UserProxyAgent|"
        r"RoundRobinGroupChat|SelectorGroupChat)\s*\("
    ),
    "llamaindex": re.compile(
        r"\b(?:ReActAgent|FunctionAgent|AgentWorkflow|OpenAIAgent)\s*[.(]"
    ),
    "openai_agents_sdk": re.compile(
        r"^\s*from\s+agents\s+import\b|\bRunner\.(?:run|run_sync|run_streamed)\s*\(",
        re.MULTILINE,
    ),
    "pydantic_ai": re.compile(r"\bfrom\s+pydantic_ai(?:\.\w+)*\s+import\b"),
    "bedrock_agents": re.compile(r"\b(?:invoke_agent|retrieve_and_generate)\s*\("),
    "semantic_kernel": re.compile(
        r"\bimport\s+semantic_kernel\b|\bfrom\s+semantic_kernel\b|\bKernel\s*\(\s*\)"
    ),
}

SUPPORTING_PATTERNS: dict[str, re.Pattern[str]] = {
    "provider_call": re.compile(
        r"\b(?:responses|chat\.completions|messages)\.create\s*\(|"
        r"\b(?:generate_content|generateContent)\s*\("
    ),
    "litellm": re.compile(
        r"\blitellm\.(?:completion|acompletion)\s*\(|\bRouter\s*\("
    ),
    "tools": re.compile(
        r"\b(?:tools|tool_choice|functions)\s*[:=]\s*(?:\[|\{)"
    ),
    "execution": re.compile(
        r"\b(?:agent\.(?:run|invoke|ainvoke)|\w*agent\.(?:run|invoke|ainvoke)|"
        r"crew\.kickoff|Runner\.(?:run|run_sync|run_streamed))\s*\("
    ),
    "agent_class": re.compile(r"\bclass\s+(\w*Agent\w*)\b"),
}

# Generic *Agent names that are almost never AI agents.
GENERIC_AGENT_NAME = re.compile(
    r"(?i)\b\w*(?:user|browser|http|monitoring|build|release|deploy|forwarding)agent\w*\b"
)

# Constructor names whose assigned variable is a strong candidate name.
AGENT_CONSTRUCTOR_ASSIGNMENT = re.compile(
    r"^\s*(?:const\s+|let\s+|var\s+|export\s+(?:const\s+|default\s+)?)?"
    r"([A-Za-z_]\w*)\s*(?::\s*[\w.<>\[\] ]+)?=\s*(?:await\s+|new\s+)?"
    r"(Agent|AgentExecutor|Crew|AssistantAgent|ConversableAgent|UserProxyAgent|"
    r"ReActAgent|FunctionAgent|AgentWorkflow|OpenAIAgent|StateGraph|"
    r"initialize_agent|create_react_agent|create_tool_calling_agent|"
    r"create_openai_functions_agent)\s*[.(]",
    re.MULTILINE,
)

AGENT_LIKE_VARIABLE = re.compile(
    r"^\s*(?:const\s+|let\s+|var\s+)?([a-z_]\w*_agent|[a-z]\w*Agent)\s*=",
    re.MULTILINE,
)

AGENT_FACTORY_FUNCTION = re.compile(
    r"\b(?:def|function)\s+((?:build|create|make|get)_?\w*[aA]gent\w*)\s*\("
)

TESTLIKE_PATH = re.compile(
    r"(?:^|/)(?:test|tests|testing|__tests__|fixtures?|mocks?|examples?|"
    r"sample|samples|snapshots)(?:/|$)"
    r"|(?:^|/)test_[^/]*$|[^/]*_test\.\w+$|[^/]*\.(?:test|spec)\.\w+$"
)

# ---------------------------------------------------------------------------
# LLM provider evidence
# ---------------------------------------------------------------------------

PROVIDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(
        r"^\s*(?:import\s+openai\b|from\s+openai(?:\.\w+)*\s+import\b)|"
        r"(?:from\s+|require\()['\"]openai['\"]|"
        r"\b(?:OpenAI|AsyncOpenAI)\s*\(|api\.openai\.com|"
        r"['\"]gpt-[45][\w.-]*['\"]|['\"]o[134][\w.-]*['\"]|\bOPENAI_API_KEY\b",
        re.MULTILINE,
    ),
    "anthropic": re.compile(
        r"^\s*(?:import\s+anthropic\b|from\s+anthropic(?:\.\w+)*\s+import\b)|"
        r"(?:from\s+|require\()['\"]@anthropic-ai/sdk['\"]|"
        r"\b(?:Anthropic|AsyncAnthropic)\s*\(|api\.anthropic\.com|"
        r"['\"]claude-[\w.-]+['\"]|\bANTHROPIC_API_KEY\b",
        re.MULTILINE,
    ),
    "google": re.compile(
        r"google\.generativeai|google-genai|\bfrom\s+google\s+import\s+genai\b|"
        r"['\"]@google/generative-ai['\"]|\bvertexai\b|\bVertexAI\s*\(|"
        r"generativelanguage\.googleapis\.com|['\"]gemini-[\w.-]+['\"]|"
        r"\b(?:GOOGLE_API_KEY|GEMINI_API_KEY)\b"
    ),
    "azure_openai": re.compile(
        r"\bAzureOpenAI\s*\(|\.openai\.azure\.com|\bAZURE_OPENAI[A-Z_]*\b"
    ),
    "bedrock": re.compile(
        r"bedrock-runtime|bedrock-agent-runtime|\bChatBedrock\b|\bBedrockChat\b|"
        r"boto3\.client\(\s*['\"]bedrock|\binvoke_model\s*\("
    ),
    "groq": re.compile(
        r"^\s*from\s+groq\s+import\b|(?:from\s+|require\()['\"]groq-sdk['\"]|"
        r"\bGroq\s*\(|api\.groq\.com|\bGROQ_API_KEY\b",
        re.MULTILINE,
    ),
    "cohere": re.compile(
        r"^\s*import\s+cohere\b|^\s*from\s+cohere\s+import\b|"
        r"cohere\.(?:Client|ClientV2)\s*\(|api\.cohere\.(?:ai|com)|\bCOHERE_API_KEY\b",
        re.MULTILINE,
    ),
    "together": re.compile(
        r"^\s*from\s+together\s+import\b|\bTogether\s*\(|api\.together\.(?:xyz|ai)|"
        r"\bTOGETHER_API_KEY\b",
        re.MULTILINE,
    ),
    "mistral": re.compile(
        r"\bmistralai\b|api\.mistral\.ai|\bMISTRAL_API_KEY\b|"
        r"['\"]mistral-(?:large|medium|small|tiny)[\w.-]*['\"]"
    ),
    "perplexity": re.compile(r"api\.perplexity\.ai|\bPERPLEXITY_API_KEY\b"),
    "huggingface": re.compile(
        r"\bhuggingface_hub\b|\bInferenceClient\s*\(|api-inference\.huggingface\.co|"
        r"\b(?:HF_TOKEN|HUGGINGFACE(?:HUB)?_API_(?:KEY|TOKEN))\b"
    ),
    "ollama": re.compile(
        r"^\s*import\s+ollama\b|\bollama\.(?:chat|generate)\s*\(|localhost:11434|"
        r"\bChatOllama\b",
        re.MULTILINE,
    ),
    "openrouter": re.compile(r"openrouter\.ai|\bOPENROUTER_API_KEY\b"),
    "litellm": re.compile(
        r"^\s*import\s+litellm\b|^\s*from\s+litellm\s+import\b|"
        r"\blitellm\.(?:completion|acompletion)\s*\(",
        re.MULTILINE,
    ),
}

# LiteLLM-style "provider/model" strings map back to a concrete provider.
LITELLM_MODEL_PREFIX = re.compile(
    r"['\"](openai|anthropic|gemini|vertex_ai|groq|bedrock|mistral|azure|"
    r"together_ai|cohere|ollama|openrouter|perplexity|huggingface)/[\w.:-]+['\"]"
)

LITELLM_PREFIX_TO_PROVIDER = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "vertex_ai": "google",
    "groq": "groq",
    "bedrock": "bedrock",
    "mistral": "mistral",
    "azure": "azure_openai",
    "together_ai": "together",
    "cohere": "cohere",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "perplexity": "perplexity",
    "huggingface": "huggingface",
}

DIRECT_MODEL_ENDPOINTS = re.compile(
    r"https?://(?:"
    r"api\.openai\.com/v1/(?:responses|chat/completions)|"
    r"api\.anthropic\.com/v1/messages|"
    r"api\.groq\.com/openai/v1/chat/completions|"
    r"openrouter\.ai/api/v1/chat/completions"
    r")"
)

# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

CAPABILITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "tool_calling": re.compile(
        r"\btools\s*[:=]\s*(?:\[|\{)|\btool_choice\b|@tool\b|"
        r"\bStructuredTool\b|\bbind_tools\s*\(|\bFunctionTool\b"
    ),
    "function_calling": re.compile(
        r"\bfunctions\s*[:=]\s*\[|\bfunction_call\b|\bfunction_calling\b"
    ),
    "database_read": re.compile(
        r"(?i)['\"`][^'\"`]*\bSELECT\b[^'\"`]*\bFROM\b|f['\"][^'\"]*\bSELECT\b"
    ),
    "database_write": re.compile(
        r"(?i)\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b|\bDELETE\s+FROM\b|"
        r"\bDROP\s+TABLE\b|\bALTER\s+TABLE\b|\bTRUNCATE\s+TABLE\b|"
        r"\.(?:insert_one|insert_many|update_one|update_many|delete_one|delete_many)\s*\("
    ),
    "code_execution": re.compile(
        r"(?<![\w.])(?:eval|exec)\s*\(|\bnew\s+Function\s*\(|\bcompile\s*\([^)]*['\"]exec['\"]"
    ),
    "shell_execution": re.compile(
        r"\bsubprocess\.(?:run|Popen|call|check_call|check_output)\s*\(|"
        r"\bos\.(?:system|popen)\s*\(|\bchild_process\b|"
        r"\b(?:execSync|spawnSync|execFile|spawn)\s*\("
    ),
    "filesystem_read": re.compile(
        r"\.read_text\s*\(|\.read_bytes\s*\(|\bfs\.readFile|\breadFileSync\s*\(|"
        r"\bopen\s*\(\s*[^,)]+(?:,\s*['\"]rb?['\"])?\s*\)"
    ),
    "filesystem_write": re.compile(
        r"\.write_text\s*\(|\.write_bytes\s*\(|\bfs\.writeFile|\bwriteFileSync\s*\(|"
        r"\bopen\s*\([^)]*['\"][wa]b?['\"]|\bshutil\.(?:copy|move|rmtree)\b"
    ),
    "web_search": re.compile(
        r"(?i)\btavily\b|\bserpapi\b|\bTavilyClient\b|\bDuckDuckGoSearch\w*\b|"
        r"\bGoogleSerperAPI\w*\b|api\.bing\.microsoft\.com|serpapi\.com|"
        r"\bbrave.?search\b"
    ),
    "browser_automation": re.compile(
        r"(?i)\bplaywright\b|\bselenium\b|\bpuppeteer\b|\bwebdriver\b"
    ),
    "external_http": re.compile(
        r"\brequests\.(?:get|post|put|patch|delete|request)\s*\(|"
        r"\bhttpx\.(?:get|post|put|patch|delete|request|Client|AsyncClient)\b|"
        r"\baiohttp\.ClientSession\b|\bfetch\s*\(|\baxios\b|"
        r"\burllib\.request\.urlopen\s*\("
    ),
    "email_send": re.compile(
        r"(?i)\bsendgrid\b|\bsmtplib\b|\bSMTP\s*\(|\bnodemailer\b|"
        r"\bsend_email\s*\(|\bsesv?2?\b.{0,40}send|boto3\.client\(\s*['\"]ses"
    ),
    "messaging": re.compile(
        r"chat\.postMessage|chat_postMessage|hooks\.slack\.com|\bWebClient\s*\(|"
        r"\btwilio\b.{0,60}messages|messages\.create\s*\(|discord(?:app)?\.com/api/webhooks"
    ),
    "payment_access": re.compile(
        r"\bstripe\.(?:Charge|Refund|PaymentIntent|Payout|Transfer|SetupIntent)\b|"
        r"\bstripe\.(?:charges|refunds|paymentIntents|payouts|transfers)\b|"
        r"api\.stripe\.com"
    ),
    "customer_support": re.compile(
        r"(?i)\bzendesk\b|\bintercom\b|\bfreshdesk\b|zdesk|\.zendesk\.com"
    ),
    "source_control": re.compile(
        r"api\.github\.com|\bPyGithub\b|^\s*from\s+github\s+import\b|\boctokit\b|"
        r"\bgitlab\b|api\.bitbucket\.org",
        re.MULTILINE,
    ),
    "document_processing": re.compile(
        r"(?i)\bpython-docx\b|\bimport\s+docx\b|\bopenpyxl\b|\bunstructured\b|\bmammoth\b"
    ),
    "pdf_processing": re.compile(
        r"(?i)\bpypdf2?\b|\bpdfplumber\b|\bfitz\b|\bpymupdf\b|\bpdfminer\b"
    ),
    "cache_access": re.compile(
        r"(?i)\bredis\b|\bmemcached?\b|\bRedis\s*\(|redis://"
    ),
    "queue_access": re.compile(
        r"(?i)\bcelery\b|\bpika\b|\bkafka\b|\bamqp\b|boto3\.client\(\s*['\"]sqs|"
        r"sqs\.[a-z0-9-]+\.amazonaws\.com"
    ),
    "cloud_resource_access": re.compile(
        r"\bboto3\.(?:client|resource)\s*\(|\bgoogle\.cloud\b|"
        r"\bazure\.(?:mgmt|storage|identity)\b|\b@aws-sdk/"
    ),
}

HIGH_IMPACT_CAPABILITIES = frozenset(
    {
        "payment_access",
        "database_write",
        "shell_execution",
        "code_execution",
        "email_send",
        "messaging",
        "source_control",
        "cloud_resource_access",
        "filesystem_write",
    }
)

# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

INTEGRATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "slack": re.compile(
        r"https?://(?:hooks\.slack\.com|slack\.com/api)/|\bslack_sdk\b|"
        r"['\"]@slack/(?:web-api|bolt)['\"]|\bSLACK_[A-Z0-9_]*(?:URL|TOKEN|KEY)\b"
    ),
    "stripe": re.compile(
        r"https?://api\.stripe\.com/v1/|^\s*import\s+stripe\b|"
        r"(?:from\s+|require\()['\"]stripe['\"]|\bSTRIPE_[A-Z0-9_]*(?:KEY|SECRET|TOKEN)\b",
        re.MULTILINE,
    ),
    "github": re.compile(
        r"https?://api\.github\.com/|\bPyGithub\b|^\s*from\s+github\s+import\b|"
        r"['\"](?:@octokit/rest|octokit)['\"]|\bGITHUB_[A-Z0-9_]*TOKEN\b",
        re.MULTILINE,
    ),
    "gitlab": re.compile(
        r"https?://gitlab\.com/api/|\bpython-gitlab\b|^\s*import\s+gitlab\b|"
        r"\bGITLAB_[A-Z0-9_]*TOKEN\b",
        re.MULTILINE,
    ),
    "zendesk": re.compile(r"(?i)\.zendesk\.com|\bzenpy\b|\bZENDESK_[A-Z0-9_]+\b"),
    "salesforce": re.compile(
        r"https?://[^/\s'\"]+\.salesforce\.com/services/data/|\bsimple_salesforce\b|"
        r"\bjsforce\b|\bSALESFORCE_[A-Z0-9_]+\b"
    ),
    "hubspot": re.compile(r"https?://api\.hubapi\.com/|\bhubspot\b|\bHUBSPOT_[A-Z0-9_]+\b"),
    "twilio": re.compile(
        r"https?://api\.twilio\.com/|^\s*from\s+twilio\b|(?:require\()['\"]twilio['\"]|"
        r"\bTWILIO_[A-Z0-9_]+\b",
        re.MULTILINE,
    ),
    "sendgrid": re.compile(
        r"https?://api\.sendgrid\.com/|\bsendgrid\b|\bSENDGRID_[A-Z0-9_]+\b"
    ),
    "ses": re.compile(r"boto3\.client\(\s*['\"]sesv?2?['\"]|email\.[a-z0-9-]+\.amazonaws\.com"),
    "datadog": re.compile(r"(?i)\bdatadog\b|api\.datadoghq\.com|\bDD_API_KEY\b"),
    "sentry": re.compile(r"\bsentry_sdk\b|['\"]@sentry/|\bSENTRY_DSN\b|ingest\.sentry\.io"),
    "postgres": re.compile(
        r"postgres(?:ql)?://|\bpsycopg2?\b|^\s*import\s+asyncpg\b|(?:require\()['\"]pg['\"]|"
        r"\bPOSTGRES[A-Z0-9_]*_(?:URL|URI|HOST|PASSWORD)\b|\bDATABASE_URL\b",
        re.MULTILINE,
    ),
    "mysql": re.compile(r"mysql://|\bpymysql\b|\bmysql\.connector\b|(?:require\()['\"]mysql2?['\"]"),
    "mongodb": re.compile(r"mongodb(?:\+srv)?://|\bpymongo\b|\bMongoClient\s*\(|\bmongoose\b"),
    "redis": re.compile(r"redis(?:s)?://|^\s*import\s+redis\b|\bRedis\s*\(|\bioredis\b", re.MULTILINE),
    "snowflake": re.compile(r"\bsnowflake\.connector\b|\bsnowflake-sdk\b|\bSNOWFLAKE_[A-Z0-9_]+\b"),
    "bigquery": re.compile(r"\bgoogle\.cloud\.bigquery\b|\bbigquery\.Client\s*\(|\b@google-cloud/bigquery\b"),
    "aws": re.compile(r"\bboto3\b|\b@aws-sdk/|\bAWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|REGION)\b"),
    "gcp": re.compile(r"\bgoogle\.cloud\b|\bGOOGLE_APPLICATION_CREDENTIALS\b"),
    "azure": re.compile(r"\bazure\.(?:identity|storage|mgmt|keyvault)\b|\bAZURE_(?:CLIENT_ID|TENANT_ID|CLIENT_SECRET)\b"),
    "jira": re.compile(r"(?i)\.atlassian\.net/rest/api|^\s*from\s+jira\s+import\b|\bJIRA_[A-Z0-9_]+\b", re.MULTILINE),
    "linear": re.compile(r"api\.linear\.app|\b@linear/sdk\b|\bLINEAR_API_KEY\b"),
    "notion": re.compile(r"api\.notion\.com|\bnotion_client\b|\b@notionhq/client\b|\bNOTION_[A-Z0-9_]+\b"),
    "confluence": re.compile(r"(?i)/wiki/rest/api|\batlassian-python-api\b|\bCONFLUENCE_[A-Z0-9_]+\b"),
    "servicenow": re.compile(r"(?i)\.service-now\.com|\bpysnow\b|\bSERVICENOW_[A-Z0-9_]+\b"),
    "shopify": re.compile(r"(?i)myshopify\.com|\bshopify(?:_python)?_api\b|\bSHOPIFY_[A-Z0-9_]+\b"),
}

SENSITIVE_INTEGRATIONS = frozenset(
    {
        "stripe",
        "salesforce",
        "zendesk",
        "hubspot",
        "twilio",
        "sendgrid",
        "ses",
        "postgres",
        "mysql",
        "mongodb",
        "snowflake",
        "bigquery",
        "aws",
        "gcp",
        "azure",
        "github",
        "gitlab",
        "shopify",
        "servicenow",
    }
)

# ---------------------------------------------------------------------------
# Risk-rule patterns
# ---------------------------------------------------------------------------

SECRET_PATTERN = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9])
    (?:
        sk-(?:proj-)?[A-Za-z0-9_-]{20,}
      | sk-ant-[A-Za-z0-9_-]{20,}
      | gsk_[A-Za-z0-9]{20,}
      | sk_live_[A-Za-z0-9]{16,}
      | rk_live_[A-Za-z0-9]{16,}
      | gh[pousr]_[A-Za-z0-9]{20,}
      | xox[baprs]-[A-Za-z0-9-]{20,}
      | AKIA[0-9A-Z]{16}
    )
    (?![A-Za-z0-9])
    """
)

PLACEHOLDER_SECRET = re.compile(
    r"(?i)fake|dummy|example|redacted|changeme|placeholder|sample|"
    r"your[-_]?(?:api[-_]?)?key|not[-_]?a[-_]?real|x{5,}|(?:\.\.\.|…)"
)

PASSWORD_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd|db_password|database_password|admin_password)\b
    \s*[:=]\s*
    (?:f?["']([^"'\n]{4,})["'])
    """
)

PASSWORD_SAFE_CONTEXT = re.compile(
    r"(?i)os\.environ|getenv|process\.env|secretsmanager|secret_manager|"
    r"get_secret|vault|keyring|input\(|getpass"
)

SQL_KEYWORDS = r"(?:SELECT\s+[\w*,.\s()]+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE)"

SQL_FSTRING = re.compile(
    r"(?i)\bf['\"]{1,3}[^'\"\n]*" + SQL_KEYWORDS + r"[^'\"\n]*\{"
)
SQL_TEMPLATE_LITERAL = re.compile(
    r"(?i)`[^`\n]*" + SQL_KEYWORDS + r"[^`\n]*\$\{"
)
SQL_PERCENT_FORMAT = re.compile(
    r"(?i)['\"][^'\"\n]*" + SQL_KEYWORDS + r"[^'\"\n]*['\"]\s*%\s*[\w(]"
)
SQL_DOT_FORMAT = re.compile(
    r"(?i)['\"][^'\"\n]*" + SQL_KEYWORDS + r"[^'\"\n]*['\"]\s*\.\s*format\s*\("
)
SQL_CONCAT = re.compile(
    r"(?i)(?:\"[^\"\n]*" + SQL_KEYWORDS + r"[^\"\n]*\"|'[^'\n]*" + SQL_KEYWORDS + r"[^'\n]*')"
    r"\s*\+\s*[A-Za-z_]"
)

SQL_INTERPOLATION_PATTERNS = (
    SQL_FSTRING,
    SQL_TEMPLATE_LITERAL,
    SQL_PERCENT_FORMAT,
    SQL_DOT_FORMAT,
    SQL_CONCAT,
)

SWALLOWED_EXCEPT_PY = re.compile(
    r"^([ \t]*)except\b[^\n:]*:\s*(?:#[^\n]*)?\n\1[ \t]+pass\b",
    re.MULTILINE,
)
SWALLOWED_CATCH_JS = re.compile(
    r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}"
)

HTTP_URL = re.compile(r"http://([^\s'\"`<>)\]}]+)")
LOCAL_HTTP_HOST = re.compile(
    r"(?ix)^(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?|"
    r"[\w.-]*\.(?:test|local|localhost|invalid|example)|"
    r"example\.(?:com|org|net)|www\.w3\.org|schemas\.[\w.-]+|json-schema\.org)"
    r"(?:[:/]|$)"
)

OUTGOING_REQUEST_CALL = re.compile(
    r"\b(?:requests|httpx)\.(?:get|post|put|patch|delete|head|request)\s*\(|"
    r"\burllib\.request\.urlopen\s*\("
)
TIMEOUT_ARG = re.compile(r"\btimeout\s*=")

COMMENT_ONLY_LINE = re.compile(r"^\s*(?:#|//|\*|/\*)")

CONTROL_PATTERNS: dict[str, re.Pattern[str]] = {
    "CTRL001": re.compile(
        r"(?i)\bauthenticat\w+\b|\bauthoriz\w+\b|\bauth[_-]?token\b|"
        r"@login_required|\bverify_jwt\b|\bcheck_auth\b|\brequire[_-]?auth\b|"
        r"\bBearer\b|\bapi[_-]?key[_-]?(?:check|verify|required)\b"
    ),
    "CTRL002": re.compile(
        r"(?i)\bvalidat\w+\b|\bpydantic\b|\bmarshmallow\b|\bcerberus\b|"
        r"\bzod\b|\bjoi\b|\bBaseModel\b|\bsanitiz\w+\b|\bschema\s*\.\s*parse\b"
    ),
    "CTRL003": re.compile(
        r"(?i)\brate[_-]?limit\w*\b|\bthrottl\w+\b|\bLimiter\b|\bslowapi\b|"
        r"\bbottleneck\b|\btoken[_-]?bucket\b"
    ),
}

BOT_AUTHOR = re.compile(r"(dependabot|renovate|github-actions|\[bot\])", re.IGNORECASE)

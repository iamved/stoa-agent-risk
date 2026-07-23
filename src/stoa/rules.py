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
    canonical_name: str | None = None
    owasp: dict | None = None


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
    # --- v0.2 AI rules (OWASP LLM Top 10) ---------------------------------
    "AI001": RuleSpec(
        rule_id="AI001",
        title="Untrusted input observed flowing into prompt construction",
        category="ai-prompt",
        default_severity="high",
        gateable=False,
        remediation="Move untrusted content into a delimited user-role message and keep instruction text static.",
        canonical_name="STOA-LLM01-PROMPT-EXPOSURE",
        owasp={"llm_top10_v1_1": "LLM01", "llm_top10_2025": "LLM01"},
    ),
    "AI002": RuleSpec(
        rule_id="AI002",
        title="Model output observed reaching a dangerous execution or injection sink",
        category="ai-output",
        default_severity="critical",
        gateable=True,
        remediation="Dispatch through a static mapping of permitted actions; never execute or render model output directly.",
        canonical_name="STOA-LLM02-OUTPUT-EXEC",
        owasp={"llm_top10_v1_1": "LLM02", "llm_top10_2025": "LLM05"},
    ),
    "AI003": RuleSpec(
        rule_id="AI003",
        title="Approval control not observed for high-impact tool capability",
        category="ai-agency",
        default_severity="info",
        gateable=False,
        remediation="Confirm an approval or human-in-the-loop control gates this capability; none was observed in this file.",
        canonical_name="STOA-LLM08-UNOBSERVED-APPROVAL",
        owasp={"llm_top10_v1_1": "LLM08", "llm_top10_2025": "LLM06"},
    ),
    "AI004": RuleSpec(
        rule_id="AI004",
        title="Identifier suggesting sensitive data observed in an external model call",
        category="ai-disclosure",
        default_severity="medium",
        gateable=False,
        remediation="Pseudonymize sensitive fields before the model call and rejoin identifiers afterward.",
        canonical_name="STOA-LLM06-SENSITIVE-INTERPOLATION",
        owasp={"llm_top10_v1_1": "LLM06", "llm_top10_2025": "LLM02"},
    ),
    "AI005": RuleSpec(
        rule_id="AI005",
        title="Model, endpoint, or artifact dependency observed without a pin or integrity control",
        category="ai-supplychain",
        default_severity="medium",
        gateable=False,
        remediation="Pin a reviewed model revision or dated snapshot and use a TLS endpoint from an allowlist.",
        canonical_name="STOA-LLM05-UNPINNED-MODEL",
        owasp={"llm_top10_v1_1": "LLM05", "llm_top10_2025": "LLM03"},
    ),
    "AI006": RuleSpec(
        rule_id="AI006",
        title="Identifier suggesting sensitive data observed flowing to a network egress sink",
        category="ai-disclosure",
        default_severity="high",
        gateable=False,
        remediation="Strip sensitive fields before egress, or add the destination to [rules.AI006].allowed_hosts if org-approved.",
        canonical_name="STOA-EXFIL-NETWORK",
        owasp={"llm_top10_v1_1": "LLM06", "llm_top10_2025": "LLM02"},
    ),
    "AI007": RuleSpec(
        rule_id="AI007",
        title="Deterministic sampling not observed on high-impact-adjacent call sites",
        category="ai-stability",
        default_severity="info",
        gateable=False,
        remediation="Pin deterministic sampling (temperature=0) on consequential model call sites, or confirm variability is intended.",
        canonical_name="STOA-SAMPLING-CONFIG",
        owasp={"llm_top10_v1_1": "LLM05", "llm_top10_2025": "LLM03"},
    ),
    "CTRL004": RuleSpec(
        rule_id="CTRL004",
        title="Observability construct not observed for agent tool execution",
        category="control",
        default_severity="info",
        gateable=False,
        remediation="Confirm logging or tracing covers this agent's tool execution; none was observed in this file.",
        canonical_name="STOA-CTRL-OBSERVABILITY",
        owasp={"llm_top10_v1_1": "LLM10", "llm_top10_2025": "LLM10"},
    ),
}

# AI rules use a 2-letter prefix; CTRL/SEC/NET/REL use 3+.
VALID_RULE_ID = re.compile(r"^[A-Z]{2,5}\d{3}$")

# ---------------------------------------------------------------------------
# Agent-candidate evidence
# ---------------------------------------------------------------------------

HIGH_AGENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "langchain": re.compile(
        r"\b(?:AgentExecutor|initialize_agent|"
        r"create(?:_|(?=[A-Z]))(?:react|tool_calling|toolCalling|"
        r"openai_functions|openaiFunctions)(?:_agent|Agent))\s*\("
    ),
    "langgraph": re.compile(
        r"\b(?:create_react_agent|createReactAgent|StateGraph)\s*\("
    ),
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
    # Vercel AI SDK agentic markers only. A bare `generateText`/@ai-sdk import
    # is a single-shot call (scored as a provider call, staying low); the
    # strong signal is a multi-step loop or the Agent class.
    "vercel_ai_sdk": re.compile(
        r"\bExperimental_Agent\b|\b(?:maxSteps|stopWhen)\s*:"
    ),
    "mastra": re.compile(r"(?:from\s+|require\()['\"]@mastra/"),
    "smolagents": re.compile(
        r"\b(?:CodeAgent|ToolCallingAgent)\s*\(|^\s*from\s+smolagents\s+import\b",
        re.MULTILINE,
    ),
    "dspy": re.compile(r"\bdspy\.(?:ReAct|Agent)\b"),
    "agno": re.compile(
        r"^\s*from\s+agno(?:\.\w+)*\s+import\b|^\s*import\s+agno\b|\bagno\.agent\b",
        re.MULTILINE,
    ),
    "google_adk": re.compile(
        r"\bgoogle\.adk\b|^\s*from\s+google\.adk\b|(?:from\s+|require\()['\"]@iqai/adk['\"]",
        re.MULTILINE,
    ),
    "strands": re.compile(
        r"^\s*from\s+strands(?:_tools|_agents)?\s+import\b|^\s*import\s+strands\b",
        re.MULTILINE,
    ),
}

SUPPORTING_PATTERNS: dict[str, re.Pattern[str]] = {
    "provider_call": re.compile(
        r"\b(?:responses|chat\.completions|messages)\.create\s*\(|"
        r"\b(?:generate_content|generateContent)\s*\(|"
        r"\b(?:generateText|streamText|generateObject|streamObject)\s*\("
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
        r"(?:from\s+|require\()['\"](?:openai|@ai-sdk/openai)['\"]|"
        r"\b(?:OpenAI|AsyncOpenAI)\s*\(|\bcreateOpenAI\s*\(|api\.openai\.com|"
        r"['\"]gpt-[45][\w.-]*['\"]|['\"]o[134][\w.-]*['\"]|\bOPENAI_API_KEY\b",
        re.MULTILINE,
    ),
    "anthropic": re.compile(
        r"^\s*(?:import\s+anthropic\b|from\s+anthropic(?:\.\w+)*\s+import\b)|"
        r"(?:from\s+|require\()['\"](?:@anthropic-ai/sdk|@ai-sdk/anthropic)['\"]|"
        r"\b(?:Anthropic|AsyncAnthropic)\s*\(|\bcreateAnthropic\s*\(|api\.anthropic\.com|"
        r"['\"]claude-[\w.-]+['\"]|\bANTHROPIC_API_KEY\b",
        re.MULTILINE,
    ),
    "google": re.compile(
        r"google\.generativeai|google-genai|\bfrom\s+google\s+import\s+genai\b|"
        r"['\"](?:@google/generative-ai|@ai-sdk/google)['\"]|\bcreateGoogleGenerativeAI\s*\(|"
        r"\bvertexai\b|\bVertexAI\s*\(|"
        r"generativelanguage\.googleapis\.com|['\"]gemini-[\w.-]+['\"]|"
        r"\b(?:GOOGLE_API_KEY|GEMINI_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY)\b"
    ),
    "azure_openai": re.compile(
        r"\bAzureOpenAI\s*\(|\.openai\.azure\.com|\bAZURE_OPENAI[A-Z_]*\b|"
        r"['\"]@ai-sdk/azure['\"]|\bcreateAzure\s*\("
    ),
    "bedrock": re.compile(
        r"bedrock-runtime|bedrock-agent-runtime|\bChatBedrock\b|\bBedrockChat\b|"
        r"boto3\.client\(\s*['\"]bedrock|\binvoke_model\s*\(|"
        r"['\"]@ai-sdk/amazon-bedrock['\"]|\bcreateAmazonBedrock\s*\("
    ),
    "groq": re.compile(
        r"^\s*from\s+groq\s+import\b|(?:from\s+|require\()['\"](?:groq-sdk|@ai-sdk/groq)['\"]|"
        r"\bGroq\s*\(|\bcreateGroq\s*\(|api\.groq\.com|\bGROQ_API_KEY\b",
        re.MULTILINE,
    ),
    "cohere": re.compile(
        r"^\s*import\s+cohere\b|^\s*from\s+cohere\s+import\b|"
        r"(?:from\s+|require\()['\"]@ai-sdk/cohere['\"]|\bcreateCohere\s*\(|"
        r"cohere\.(?:Client|ClientV2)\s*\(|api\.cohere\.(?:ai|com)|\bCOHERE_API_KEY\b",
        re.MULTILINE,
    ),
    "together": re.compile(
        r"^\s*from\s+together\s+import\b|\bTogether\s*\(|api\.together\.(?:xyz|ai)|"
        r"['\"]@ai-sdk/togetherai['\"]|\bcreateTogetherAI\s*\(|\bTOGETHER_API_KEY\b",
        re.MULTILINE,
    ),
    "mistral": re.compile(
        r"\bmistralai\b|api\.mistral\.ai|\bMISTRAL_API_KEY\b|"
        r"['\"]@ai-sdk/mistral['\"]|\bcreateMistral\s*\(|"
        r"['\"]mistral-(?:large|medium|small|tiny)[\w.-]*['\"]"
    ),
    "xai": re.compile(
        r"['\"]@ai-sdk/xai['\"]|\bcreateXai\s*\(|api\.x\.ai|\bXAI_API_KEY\b|"
        r"['\"]grok-[\w.-]+['\"]"
    ),
    "perplexity": re.compile(
        r"api\.perplexity\.ai|\bPERPLEXITY_API_KEY\b|['\"]@ai-sdk/perplexity['\"]"
    ),
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
    "vector_search": re.compile(
        r"(?i)pinecone|weaviate|chromadb|qdrant|pgvector|milvus|lancedb|"
        r"\bfaiss\b|\bpc\.Index\s*\(|"
        r"\b(?:similarity_search|max_marginal_relevance_search)\s*\("
    ),
    "mcp_tools": re.compile(
        r"\bFastMCP\s*\(|['\"]@modelcontextprotocol/sdk|"
        r"^\s*from\s+mcp(?:\.\w+)*\s+import\b|\bmcp\.server\b|\b@mcp\.tool\b",
        re.MULTILINE,
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
    "pinecone": re.compile(
        r"(?i)\bpinecone\b|api\.pinecone\.io|\bPINECONE_[A-Z0-9_]+\b|\bpc\.Index\s*\("
    ),
    "weaviate": re.compile(r"(?i)\bweaviate\b|\bWEAVIATE_[A-Z0-9_]+\b"),
    "chroma": re.compile(r"(?i)\bchromadb\b|\bchroma_client\b|\bPersistentClient\s*\("),
    "qdrant": re.compile(r"(?i)qdrant"),
    "milvus": re.compile(r"(?i)\bmilvus\b|\bpymilvus\b|\bMILVUS_[A-Z0-9_]+\b"),
    "google_places": re.compile(
        r"(?i)maps\.googleapis\.com/maps/api/place|\bGOOGLE_PLACES_API_KEY\b"
    ),
    "eventbrite": re.compile(r"(?i)eventbriteapi\.com|\bEVENTBRITE_[A-Z0-9_]+\b"),
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

# ---------------------------------------------------------------------------
# v0.2 AI-rule patterns (Part II §AI005, Part IV §B — pattern/correlation)
# ---------------------------------------------------------------------------

# AI005 — supply chain / unpinned model
TRUST_REMOTE_CODE = re.compile(r"\b(?:from_pretrained|pipeline)\s*\([^)]*\btrust_remote_code\s*=\s*True")
FROM_PRETRAINED = re.compile(r"\bfrom_pretrained\s*\(\s*(['\"])([^'\"]+)\1([^)]*)\)")
REVISION_KW = re.compile(r"\brevision\s*=")
TORCH_PICKLE_LOAD = re.compile(r"\b(?:torch\.load|pickle\.load|marshal\.load)\s*\(")
MODEL_ASSIGN = re.compile(
    r"\bmodel\s*[:=]\s*(['\"])([A-Za-z0-9][\w.:\-/]*)\1|"
    r"\b(?:ChatOpenAI|ChatAnthropic|ChatGroq|OpenAI|Anthropic)\s*\([^)]*\bmodel\s*=\s*(['\"])([A-Za-z0-9][\w.:\-/]*)\3|"
    r"\b(?:openai|anthropic|groq|google|createGroq|createOpenAI|createAnthropic)\s*\(\s*(['\"])([A-Za-z0-9][\w.:\-/]*)\5"
)
# Dated model snapshots are pinned and never trigger floating-alias.
DATED_MODEL_SNAPSHOT = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})(?:$|['\"])|@[0-9a-f]{7,40}")
BASE_URL_ASSIGN = re.compile(
    r"\b(?:base_url|baseURL|api_base)\s*[:=]\s*(.+?)(?:[,)\n]|$)"
)
BASE_URL_HTTP = re.compile(r"^\s*['\"]http://([^'\"/]+)")
BASE_URL_DYNAMIC = re.compile(r"(?:os\.(?:environ|getenv)|process\.env|config\.)")

# recognized model call sites (for AI007 sampling analysis)
MODEL_CALL_SITE = re.compile(
    r"\b(?:chat\.completions|responses|messages)\.create\s*\(|"
    r"\b(?:generate_content|generateContent)\s*\(|"
    r"\.(?:invoke|ainvoke|stream)\s*\(|"
    r"\b(?:generateText|streamText|generateObject|streamObject)\s*\("
)
EMBEDDING_OR_MODERATION = re.compile(r"\b(?:embeddings|moderations|embed|embedMany)\b")
TEMPERATURE_DETERMINISTIC = re.compile(r"\btemperature\s*[:=]\s*0(?:\.[0-3]\d*)?\b")
TEMPERATURE_PRESENT = re.compile(r"\b(?:temperature|top_p)\s*[:=]")

# AI003 — tool binding + approval constructs
TOOL_BINDING = re.compile(
    r"@(?:tool|function_tool)\b|\btools\s*[:=]\s*[\[{]|"
    r"\bStructuredTool\.from_function\b|\bserver\.tool\s*\(|"
    r"\btool\s*\(\s*\{|\bFunctionTool\b|\btool_choice\b"
)
APPROVAL_CONSTRUCT = re.compile(
    r"\binterrupt(?:_before|_after)?\s*[(=]|\bCommand\s*\(\s*resume|"
    r"\brequires_approval\s*=\s*True\b|\bhuman_in_the_loop\b|"
    r"\bneedsApproval\s*:\s*true\b|\bHumanApprovalCallbackHandler\b|\bhuman_input\b|"
    r"\b(?:approv|confirm|authoriz|consent|reviewed?)\w*\b",
    re.IGNORECASE,
)

# CTRL004 — durable observability constructs
OBSERVABILITY_CONSTRUCT = re.compile(
    r"\b(?:logging|logger|log)\.(?:info|warning|warn|error|debug|exception|critical)\s*\(|"
    r"\bstructlog\b|\bloguru\b|@observe\b|\blangsmith\b|\blangfuse\b|"
    r"\bopentelemetry\b|\btraceloop\b|\bwandb\b|\btracer\.start_?[sS]pan\b|"
    r"\b(?:winston|pino|bunyan)\b|\bconsole\.(?:error|warn)\s*\("
)
ADHOC_OUTPUT = re.compile(r"\bprint\s*\(|\bconsole\.log\s*\(")

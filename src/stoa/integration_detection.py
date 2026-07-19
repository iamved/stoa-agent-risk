"""Provider, capability, and integration detection for a single file.

All results are static evidence only: Stoa reports what patterns were
observed, never how often anything executes at runtime. Integration match
counts are reported as *call sites*, not API call counts.
"""

from __future__ import annotations

from .rules import (
    CAPABILITY_PATTERNS,
    DIRECT_MODEL_ENDPOINTS,
    INTEGRATION_PATTERNS,
    LITELLM_MODEL_PREFIX,
    LITELLM_PREFIX_TO_PROVIDER,
    PROVIDER_PATTERNS,
)


def detect_providers(content: str) -> list[str]:
    """Detect LLM providers via imports, constructors, models, URLs, env vars."""
    providers: set[str] = set()
    for provider, pattern in PROVIDER_PATTERNS.items():
        if pattern.search(content):
            providers.add(provider)
    for match in LITELLM_MODEL_PREFIX.finditer(content):
        mapped = LITELLM_PREFIX_TO_PROVIDER.get(match.group(1))
        if mapped:
            providers.add(mapped)
    if DIRECT_MODEL_ENDPOINTS.search(content):
        endpoint = DIRECT_MODEL_ENDPOINTS.search(content).group(0)
        if "openai.com" in endpoint:
            providers.add("openai")
        elif "anthropic.com" in endpoint:
            providers.add("anthropic")
        elif "groq.com" in endpoint:
            providers.add("groq")
        elif "openrouter.ai" in endpoint:
            providers.add("openrouter")
    return sorted(providers)


def detect_capabilities(content: str) -> list[str]:
    """Detect static evidence of capabilities; presence is not runtime proof."""
    return sorted(
        capability
        for capability, pattern in CAPABILITY_PATTERNS.items()
        if pattern.search(content)
    )


def detect_integrations(content: str) -> tuple[list[str], dict[str, int]]:
    """Detect external integrations and count call sites per integration."""
    integrations: list[str] = []
    call_sites: dict[str, int] = {}
    for integration, pattern in INTEGRATION_PATTERNS.items():
        count = sum(1 for _ in pattern.finditer(content))
        if count:
            integrations.append(integration)
            call_sites[integration] = count
    return sorted(integrations), dict(sorted(call_sites.items()))

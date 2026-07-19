"""HTTP User-Agent parsing: must not be classified as an AI agent."""


class UserAgentParser:
    """Parses browser User-Agent headers."""

    def parse(self, user_agent: str) -> dict:
        browser = "unknown"
        if "Chrome" in user_agent:
            browser = "chrome"
        elif "Firefox" in user_agent:
            browser = "firefox"
        return {"browser": browser, "raw": user_agent}

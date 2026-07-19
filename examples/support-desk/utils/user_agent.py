"""Browser User-Agent parsing — intentionally NOT an AI agent (control)."""


class UserAgentParser:
    """Extracts browser family from a User-Agent header for analytics."""

    def parse(self, user_agent: str) -> dict:
        family = "other"
        if "Chrome" in user_agent:
            family = "chrome"
        elif "Safari" in user_agent:
            family = "safari"
        return {"family": family, "raw": user_agent}

"""Browser User-Agent parsing — intentionally NOT an AI agent."""
class UserAgentParser:
    def parse(self, ua: str) -> dict:
        return {"browser": "chrome" if "Chrome" in ua else "other"}

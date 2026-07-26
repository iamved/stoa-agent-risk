"""Parses the browser User-Agent header for session logging — intentionally
NOT an AI agent, despite the generic *Agent name."""


class UserAgentParser:
    def parse(self, ua: str) -> dict:
        return {"browser": "chrome" if "Chrome" in ua else "other"}

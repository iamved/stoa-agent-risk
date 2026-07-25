"""MCP server exposing script-generation tools to the agent mesh.

A hand-rolled agentic surface: it publishes tools that an LLM client can call.
No agent framework here — exactly the kind of surface framework-keyed detection
used to miss.
"""
import os, subprocess
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

mcp = FastMCP("meridian-scripts")
client = OpenAI()

@mcp.tool()
def generate_script(topic: str) -> str:
    """Generate a marketing script for a topic."""
    r = client.chat.completions.create(model="gpt-4o",
                                       messages=[{"role": "user", "content": topic}])
    return r.choices[0].message.content

@mcp.tool()
def render_video(script: str, out_path: str) -> str:
    """Render a video from a script via the local pipeline."""
    subprocess.run(["ffmpeg", "-i", script, out_path])          # shell_execution
    return out_path

if __name__ == "__main__":
    mcp.run()

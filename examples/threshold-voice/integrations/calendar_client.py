"""Books a follow-up slot on an external scheduling MCP server. Deliberately
pure MCP client glue with no other agentic construct anywhere in the file --
this is a stress-test case, not a real gap to fix here: it checks whether
client-only code with no other agent signal is scanned at all. (It won't
be -- see the fixture README.)
"""
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

SCHEDULING_SERVER = StdioServerParameters(command="scheduling-mcp-server")


async def book_followup(call_id: str, slot: str) -> None:
    async with stdio_client(SCHEDULING_SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("book_slot", {"call_id": call_id, "slot": slot})

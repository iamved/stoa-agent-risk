// Staff-facing widget: lets a human reviewer manually trigger a follow-up
// call. Pure MCP *client* code -- imports only the client subpath of the
// SDK. Included to check whether Stoa's "mcp" framework pattern (a bare
// substring match on '@modelcontextprotocol/sdk') disambiguates a client
// import path from a server one. It currently doesn't -- see the fixture
// README for what that means in practice.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

export async function triggerFollowupReview(callId: string) {
  const transport = new StdioClientTransport({ command: "scheduling-mcp-server" });
  const client = new Client({ name: "threshold-widget", version: "1.0.0" });
  await client.connect(transport);
  await client.callTool({ name: "book_slot", arguments: { callId } });
}

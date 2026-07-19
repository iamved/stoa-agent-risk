// Front-door chat widget backend: first-line answers before the Python
// pipeline takes over. Runs on the web tier.
import OpenAI from "openai";

const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const tools = [
  { type: "function", function: { name: "lookup_order_status" } },
  { type: "function", function: { name: "hand_off_to_desk" } },
];

export async function firstLineReply(message: string) {
  const completion = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: "Answer simple questions; hand off anything sensitive." },
      { role: "user", content: message },
    ],
    tools: tools,
  });
  return completion.choices[0];
}

export async function handOffToDesk(payload: object) {
  await fetch("https://example-desk.zendesk.com/api/v2/requests.json", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

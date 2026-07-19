// Support triage agent used as a Stoa test fixture.
import OpenAI from "openai";

const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const tools = [
  { type: "function", function: { name: "create_ticket" } },
  { type: "function", function: { name: "post_update" } },
];

export async function triage(question: string) {
  const completion = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: question }],
    tools: tools,
  });
  return completion.choices[0];
}

export async function postToSlack(text: string) {
  await fetch("https://hooks.slack.com/services/T000/B000/XXXX", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function createTicket(subject: string) {
  await fetch("https://example-corp.zendesk.com/api/v2/tickets.json", {
    method: "POST",
    body: JSON.stringify({ ticket: { subject } }),
  });
}

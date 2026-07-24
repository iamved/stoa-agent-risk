// Front-door support chat (web tier).
import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';

export async function reply(req: Request) {
  const body = await req.json();                                  // untrusted source
  const prompt = `You are support. Follow policy strictly. User said: ${body.message}`;  // AI001
  const out = await generateText({ model: openai('gpt-4o'), system: prompt });
  container.innerHTML = out.text;                                 // AI002 markup (model output -> innerHTML)
  await fetch("https://acme.zendesk.com/api/v2/tickets.json", { method: "POST", body: out.text });
  await fetch("https://hooks.slack.com/services/T/B/X", { method: "POST", body: "new ticket" });  // HEAD-ONLY
}

/**
 * What the finding panel says about one finding: the static part (what the
 * rule checks, why it matters, how to fix) comes from the rule's plain copy in
 * labels.ts; the generated part ("What we found") is built from the finding
 * and the agent it sits on, so it names the agent the way the rest of the
 * dashboard does. A rule without plain copy falls back to the scanner's text.
 */
import type { Envelope } from "./types";
import { PLAIN_CHECK, PLAIN_FIX, PLAIN_RULE_NAME, PLAIN_WHY, autonomyLabel, prose } from "./labels";
import { declaredOf } from "./agents";
import { joinWords } from "./overview";
import type { FindingRef } from "./selectors";

/** The scanner's sentence without its backticks, for rules with no plain copy. */
const plainScannerText = (text: string | null | undefined) => prose(text).replace(/`/g, "");

export function ruleName(env: Envelope, ruleId: string, fallback: string): string {
  return PLAIN_RULE_NAME[ruleId] ?? prose(env.rules[ruleId]?.title ?? fallback);
}

/** What the rule checks. Static. */
export function whatThisCheckDoes(env: Envelope, ruleId: string): string {
  const plain = PLAIN_CHECK[ruleId];
  if (plain) return plain;
  const rule = env.rules[ruleId];
  if (!rule) return "";
  return `${prose(rule.title)}.${rule.gateable ? " Can fail a build at high confidence." : ""}`;
}

/** The agent names the panel shows, joined. */
function agentNames(ref: FindingRef): string {
  return joinWords(ref.uniqueAgents.map((u) => u.name));
}

/**
 * What this finding found, generated from the finding and the agent it sits
 * on. The agent is named as the "Affected agent" field names it.
 */
export function whatWeFound(ref: FindingRef): string {
  const f = ref.finding;
  switch (f.rule_id) {
    case "DECL001": {
      const intent = ref.uniqueAgents.map((u) => declaredOf(u)?.autonomy_intent).find(Boolean) ?? /autonomy_intent='([^']+)'/.exec(f.snippet ?? "")?.[1] ?? "human_approved";
      const declared = intent === "recommend_only" ? "recommend-only" : "needing human approval";
      return `${agentNames(ref) || "This agent"} is declared as ${declared}, but its code can take actions with no approval step. Either the declaration is out of date, or the approval step is missing.`;
    }
    default:
      return plainScannerText(f.message);
  }
}

export function whyItMatters(env: Envelope, ref: FindingRef, title: string): string {
  return PLAIN_WHY[ref.finding.rule_id] ?? title;
}

export function howToFix(ref: FindingRef): string {
  return PLAIN_FIX[ref.finding.rule_id] ?? plainScannerText(ref.finding.remediation);
}

/** "Declared: human_approved / Found: unrestricted_autonomous" for DECL001; otherwise the snippet as the scanner wrote it. */
export function evidenceLines(ref: FindingRef): { label: string; value: string }[] | null {
  const f = ref.finding;
  if (f.rule_id !== "DECL001") return null;
  const m = /autonomy_intent='([^']+)'\s+vs\s+inferred='([^']+)'/.exec(f.snippet ?? "");
  if (!m) return null;
  return [{ label: "Declared", value: m[1]! }, { label: "Found", value: m[2]! }];
}

/** "code/tools/account_tools.py:17", with the column only when it says something. */
export function locationText(path: string, line: number, column?: number | null): string {
  return `${path}:${line}${column && column > 1 ? `:${column}` : ""}`;
}

export { autonomyLabel };

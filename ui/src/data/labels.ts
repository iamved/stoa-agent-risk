/**
 * Display labels for the scanner's raw values. The raw value is never lost:
 * drawers and exports show it, and every label here is a lookup, so a value
 * this file has not heard of is shown as the scanner wrote it.
 */

// --- autonomy ---------------------------------------------------------------------

const AUTONOMY_LABEL: Record<string, string> = {
  unrestricted_autonomous: "Acts on its own",
  bounded_autonomous: "Acts on its own, within limits",
  human_approved: "Acts after human approval",
  recommend_only: "Recommends only",
  indeterminate: "Not determined",
};

export function autonomyLabel(level: string | null | undefined): string {
  if (!level) return AUTONOMY_LABEL["indeterminate"]!;
  return AUTONOMY_LABEL[level] ?? level.replace(/_/g, " ");
}

// --- capabilities --------------------------------------------------------------------

export type CapabilityId = "payments" | "record_changes" | "system_changes" | "messages" | "external_calls" | "data_platform";

export const CAPABILITY_LABEL: Record<CapabilityId, string> = {
  payments: "Payments",
  record_changes: "Record changes",
  system_changes: "System changes",
  messages: "Messages",
  external_calls: "External calls",
  data_platform: "Data platform access",
};

/** Summary order: what a risk officer asks about first. */
export const CAPABILITY_ORDER: CapabilityId[] = ["payments", "record_changes", "system_changes", "messages", "external_calls", "data_platform"];

/**
 * Scanner capability tags that are a business capability, by label. Tags not
 * listed (tool_calling, function_calling, reads, search) describe how an agent
 * is built, not what it can do to the business, and stay out of summaries.
 */
const CAPABILITY_OF_TAG: Record<string, CapabilityId> = {
  payment_access: "payments",
  database_write: "record_changes",
  filesystem_write: "record_changes",
  queue_access: "record_changes",
  code_execution: "system_changes",
  shell_execution: "system_changes",
  source_control: "system_changes",
  cloud_resource_access: "system_changes",
  browser_automation: "system_changes",
  email_send: "messages",
  messaging: "messages",
  external_http: "external_calls",
};

/** Integrations that are a data platform. */
const DATA_PLATFORMS = new Set(["databricks", "snowflake", "bigquery", "redshift", "postgres", "mysql", "mongodb", "dynamodb", "s3"]);

export function businessCapabilities(capabilities: string[], integrations: string[]): CapabilityId[] {
  const out = new Set<CapabilityId>();
  for (const tag of capabilities) {
    const id = CAPABILITY_OF_TAG[tag];
    if (id) out.add(id);
  }
  if (integrations.some((i) => DATA_PLATFORMS.has(i))) out.add("data_platform");
  return CAPABILITY_ORDER.filter((id) => out.has(id));
}

// --- safeguards --------------------------------------------------------------------------

/** Names stay Stoa's; the subtitle says what the name means. */
export const SAFEGUARD_SUBTITLE: Record<string, string> = {
  approval: "A person confirms before the agent acts",
  kill_switch: "A way to halt the agent mid-run",
  authentication: "The caller is identified before the agent runs",
  validation: "Inputs and outputs are checked",
  rate_limit: "A cap on how often the agent can act",
  observability: "Logging and monitoring",
  deterministic_sampling: "Fixed model settings for consistent outputs",
  sandbox: "Isolated execution",
};

// --- dimensions ------------------------------------------------------------------------------

/** One plain line under each dimension name. The names are Stoa's taxonomy and are never changed. */
export const DIMENSION_SUBTITLE: Record<string, string> = {
  "boundary-leakage": "Data crossing a boundary it should not.",
  "mandate-overreach": "Agents can do more than they are declared to do.",
  "injection-tamper-surface": "Places where outside input can steer the agent.",
  "control-coverage-gap": "Expected safeguards not detected.",
  "unreviewed-high-impact-action": "Money or system changes with no human check detected.",
  "output-fidelity": "Whether outputs can be trusted as accurate.",
  "conduct-variability": "How consistently the agent behaves run to run.",
  "dependency-drift": "Models or dependencies that can change underneath you.",
};

/** Falls back to the taxonomy's own definition for a custom dimension. */
export function dimensionSubtitle(id: string, definition?: string): string {
  const known = DIMENSION_SUBTITLE[id];
  if (known) return known;
  const text = (definition ?? "").trim();
  return text ? (text.endsWith(".") ? text : `${text}.`) : "";
}

// --- money -----------------------------------------------------------------------------------------

export function amountLabel(v?: { amount: number; currency: string } | null): string {
  if (!v) return "";
  const symbol = v.currency === "USD" ? "$" : "";
  return `${symbol}${v.amount.toLocaleString("en-US")}${symbol ? "" : ` ${v.currency}`}`;
}

// --- scanner prose ----------------------------------------------------------------------------------

/**
 * Text the scanner wrote (messages, remediation, crosswalk sentences) is shown
 * as written except for em dashes, which UI copy does not use. A colon carries
 * the same "here is the consequence" meaning. Snippets are evidence and are
 * never passed through this.
 */
export function prose(text: string | null | undefined): string {
  return (text ?? "").replace(/\s*(?:\u2014|\s--\s)\s*/g, ": ");
}

// --- plain words for findings ----------------------------------------------------------------------

/**
 * A finding's title and next action, said for a risk officer. The scanner's
 * own sentence stays in the finding drawer under "Why it matters" and "How to
 * fix"; these are what the summary screens show. A rule not listed here shows
 * the scanner's sentence.
 */
export const PLAIN_TITLE: Record<string, string> = {
  DECL001: "Declared autonomy does not match what the code does.",
  AI008: "A payment can be charged twice if a request is retried.",
  DECL006: "This agent is missing from your declaration file.",
  DECL005: "A production agent has no logging or monitoring detected.",
  CTRL007: "No way to switch the agent off without a deploy was detected.",
  CTRL004: "No logging of what this agent does was detected.",
  AI003: "A high-impact action can run with no human approval detected.",
  AI005: "The model version is not pinned, so its behavior can change silently.",
  DECL003: "This agent can move money, but no spending limit is declared.",
  DECL002: "A spending limit is declared, but the code does not enforce it.",
  DECL004: "This agent handles data it is not declared to handle.",
  CTRL001: "No sign-in check before the agent acts was detected.",
  CTRL002: "No check on the agent's inputs was detected.",
  CTRL003: "No limit on how often the agent can act was detected.",
  CTRL005: "A loop with no limit on how many times it runs was detected.",
  CTRL006: "Code runs outside an isolated environment.",
  AI001: "Untrusted text is mixed into the agent's instructions.",
  AI002: "The model's output is executed or rendered without checks.",
  AI006: "Sensitive data is sent to an outside service.",
  AI007: "Model settings are not fixed, so outputs vary run to run.",
  SEC001: "A credential is written into the code.",
  SEC002: "A password is written into the code.",
};

export const PLAIN_ACTION: Record<string, string> = {
  DECL001: "Add the approval step, or correct the declaration.",
  AI008: "Give each payment request a unique reference so a retry cannot charge it again, and apply limits per request rather than per attempt.",
  DECL006: "Add this agent to your declaration file, even with partial details.",
  DECL005: "Add logging or tracing before relying on it in production.",
  CTRL007: "Add a setting or feature flag that can turn the agent off at once.",
  CTRL004: "Confirm logging or tracing covers what this agent does.",
  AI003: "Confirm a person approves this action before it runs.",
  AI005: "Pin a specific model version.",
  DECL003: "Declare the spending limit.",
  DECL002: "Enforce the declared limit in code.",
  DECL004: "Update the declaration, or confirm the finding is wrong.",
  CTRL001: "Confirm callers are signed in before the agent acts.",
  CTRL002: "Confirm inputs are checked before the agent acts.",
  CTRL003: "Confirm a rate limit applies to the agent's actions.",
  CTRL005: "Put a limit on how many times the loop can run.",
  CTRL006: "Run this code in an isolated environment.",
  AI001: "Keep instructions fixed and pass untrusted text as data.",
  AI002: "Only allow a fixed list of actions, and never run model output directly.",
  AI006: "Strip sensitive fields before sending, or approve the destination.",
  AI007: "Fix the model settings on decisions that matter.",
  SEC001: "Load the credential from a secret manager.",
  SEC002: "Load the password from a secret manager.",
};

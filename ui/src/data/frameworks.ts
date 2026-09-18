/**
 * Framework labeling. A labeling layer only: nothing here touches a score.
 * Per-rule mapping is one primary OWASP LLM class and one EU AI Act article
 * (from the scanner's crosswalk); NIST AI RMF is a report-level roll-up.
 */

export type FrameworkId = "owasp" | "eu" | "nist";

export const FRAMEWORKS: { id: FrameworkId; label: string; short: string }[] = [
  { id: "owasp", label: "OWASP LLM Top 10 (2025)", short: "OWASP" },
  { id: "eu", label: "EU AI Act", short: "EU AI Act" },
  { id: "nist", label: "NIST AI RMF", short: "NIST" },
];

/** OWASP Top 10 for LLM Applications, 2025 edition. */
export const OWASP_LLM_2025: { code: string; name: string }[] = [
  { code: "LLM01", name: "Prompt Injection" },
  { code: "LLM02", name: "Sensitive Information Disclosure" },
  { code: "LLM03", name: "Supply Chain" },
  { code: "LLM04", name: "Data and Model Poisoning" },
  { code: "LLM05", name: "Improper Output Handling" },
  { code: "LLM06", name: "Excessive Agency" },
  { code: "LLM07", name: "System Prompt Leakage" },
  { code: "LLM08", name: "Vector and Embedding Weaknesses" },
  { code: "LLM09", name: "Misinformation" },
  { code: "LLM10", name: "Unbounded Consumption" },
];

/** EU AI Act (Regulation (EU) 2024/1689) article titles, for the ones Stoa anchors to. */
export const EU_AI_ACT_ARTICLES: Record<string, string> = {
  "Art. 9": "Risk management system",
  "Art. 10": "Data and data governance",
  "Art. 11": "Technical documentation",
  "Art. 12": "Record-keeping",
  "Art. 13": "Transparency and provision of information to deployers",
  "Art. 14": "Human oversight",
  "Art. 15": "Accuracy, robustness and cybersecurity",
  "Art. 17": "Quality management system",
  "Art. 26": "Obligations of deployers",
  "Art. 50": "Transparency obligations",
  "Art. 72": "Post-market monitoring",
};

export function owaspName(code: string): string {
  return OWASP_LLM_2025.find((c) => c.code === code)?.name ?? code;
}

export function euArticleName(article: string): string {
  return EU_AI_ACT_ARTICLES[article] ?? article;
}

export function frameworkLabel(id: FrameworkId): string {
  return FRAMEWORKS.find((f) => f.id === id)?.label ?? id;
}

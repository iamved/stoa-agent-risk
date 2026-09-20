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

/** OWASP Top 10 for LLM Applications, 2025 edition, with a one-sentence description of each class. */
export const OWASP_LLM_2025: { code: string; name: string; description: string }[] = [
  { code: "LLM01", name: "Prompt Injection", description: "User or third-party input alters the model's behavior or output in unintended ways." },
  { code: "LLM02", name: "Sensitive Information Disclosure", description: "The model or its outputs expose personal data, credentials, or confidential business information." },
  { code: "LLM03", name: "Supply Chain", description: "Vulnerabilities arise from compromised third-party components, external datasets, or pretrained models." },
  { code: "LLM04", name: "Data and Model Poisoning", description: "Training, fine-tuning, or retrieval data is manipulated to introduce backdoors, bias, or degraded behavior." },
  { code: "LLM05", name: "Improper Output Handling", description: "Model output is passed to other systems without validation, enabling code execution, injection, or privilege escalation." },
  { code: "LLM06", name: "Excessive Agency", description: "The system is granted more functionality, permissions, or autonomy than its task requires." },
  { code: "LLM07", name: "System Prompt Leakage", description: "Instructions or secrets held in the system prompt are exposed and can be used to bypass controls." },
  { code: "LLM08", name: "Vector and Embedding Weaknesses", description: "Weaknesses in how embeddings and vector stores are generated, stored, or retrieved lead to leakage or manipulation." },
  { code: "LLM09", name: "Misinformation", description: "The model produces false or misleading content that is presented as reliable." },
  { code: "LLM10", name: "Unbounded Consumption", description: "Excessive or uncontrolled use leads to denial of service, runaway cost, or model theft." },
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

/** One-sentence description of each article's obligation, for readers who do not know the Act. */
export const EU_AI_ACT_DESCRIPTIONS: Record<string, string> = {
  "Art. 9": "Providers must run a continuous risk management process across the system's lifecycle.",
  "Art. 10": "Training, validation, and test data must meet quality and governance criteria.",
  "Art. 11": "Technical documentation must be kept up to date and sufficient to show compliance.",
  "Art. 12": "The system must automatically log events so its operation can be traced.",
  "Art. 13": "The system must be transparent enough for deployers to interpret and use its output appropriately.",
  "Art. 14": "The system must be designed so people can oversee it and intervene.",
  "Art. 15": "The system must achieve appropriate accuracy, robustness, and cybersecurity throughout its lifecycle.",
  "Art. 17": "Providers must operate a quality management system covering design, development, and monitoring.",
  "Art. 26": "Deployers must use the system as instructed, with oversight, monitoring, and record-keeping.",
  "Art. 50": "People must be told when they interact with an AI system or see AI-generated content.",
  "Art. 72": "Providers must monitor the system after it is placed on the market and act on what they learn.",
};

export function owaspName(code: string): string {
  return OWASP_LLM_2025.find((c) => c.code === code)?.name ?? code;
}

export function euArticleName(article: string): string {
  return EU_AI_ACT_ARTICLES[article] ?? article;
}

export function owaspDescription(code: string): string {
  return OWASP_LLM_2025.find((c) => c.code === code)?.description ?? "";
}

export function euArticleDescription(article: string): string {
  return EU_AI_ACT_DESCRIPTIONS[article] ?? "";
}

export function frameworkLabel(id: FrameworkId): string {
  return FRAMEWORKS.find((f) => f.id === id)?.label ?? id;
}

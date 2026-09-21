import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { expect, test } from "@playwright/test";
import { dashboardPath } from "./global-setup";

function fileUrl(name: string, hash = ""): string {
  return pathToFileURL(dashboardPath(name)).href + hash;
}

function envelope(name: string) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8"));
}

test.describe("findings", () => {
  test("URL filters drive the table and survive reload", async ({ page }) => {
    const env = envelope("meridian-pay");
    await page.goto(fileUrl("meridian-pay", "#/findings?severity=critical"));
    const table = page.getByRole("table", { name: "Findings" });
    await expect(table).toHaveAttribute("aria-rowcount", String(env.registry.summary.findings.critical));
    await page.getByRole("button", { name: /^High\s+\d+$/ }).click();
    await expect.poll(() => page.evaluate(() => window.location.hash)).toContain("severity=critical%2Chigh");
    await page.reload();
    await expect(table).toHaveAttribute("aria-rowcount", String(env.registry.summary.findings.critical + env.registry.summary.findings.high));
  });

  test("a deep link opens the finding drawer with What / Why / Fix", async ({ page }) => {
    const env = envelope("meridian-pay");
    const finding = env.registry.agents.flatMap((a: { findings: { fingerprint: string; rule_id: string }[] }) => a.findings).find((f: { rule_id: string }) => f.rule_id === "AI008");
    await page.goto(fileUrl("meridian-pay", `#/findings/${finding.fingerprint}`));
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("What this check does")).toBeVisible();
    await expect(dialog.getByText("Why it matters")).toBeVisible();
    await expect(dialog.getByText("How to fix")).toBeVisible();
    await expect(dialog.getByText(/^OWASP LLM\d\d: /)).toBeVisible();
    await expect(dialog.getByText("Vulnerabilities arise from compromised third-party components, external datasets, or pretrained models.").or(dialog.getByText(/The system is granted more functionality|Model output is passed to other systems|Excessive or uncontrolled use/))).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    expect(await page.evaluate(() => window.location.hash)).toBe("#/findings");
  });

  test("hostile snippet renders as inert text inside the drawer", async ({ page }) => {
    const env = envelope("hostile");
    const finding = env.registry.agents.flatMap((a: { findings: { snippet: string }[] }) => a.findings).find((f: { snippet: string }) => f.snippet.includes("</script><script>alert(1)</script>"));
    const dialogs: string[] = [];
    page.on("dialog", async (d) => { dialogs.push(d.message()); await d.dismiss(); });
    await page.goto(fileUrl("hostile", `#/findings/${finding.fingerprint}`));
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("pre")).toContainText("</script><script>alert(1)</script>");
    expect(dialogs).toEqual([]);
  });

  test("5,000 findings stay virtualized", async ({ page }) => {
    await page.goto(fileUrl("large", "#/findings"));
    const table = page.getByRole("table", { name: "Findings" });
    await expect(table).toHaveAttribute("aria-rowcount", "5000");
    const rendered = await table.getByRole("row").count();
    expect(rendered).toBeLessThan(120);
    await table.evaluate((el) => { el.scrollTop = 100000; });
    await expect.poll(async () => Number(await table.getByRole("row").last().getAttribute("aria-rowindex"))).toBeGreaterThan(2000);
  });
});

test.describe("inventory", () => {
  test("agent deep link opens the drawer with declared versus scanned", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/inventory/b8f0111742fc"));
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Declared vs scanned")).toBeVisible();
    await expect(dialog.getByText("What it can do")).toBeVisible();
    await expect(dialog.locator("table")).toContainText("issue_refund");
  });

  test("category rail and authority filter", async ({ page }) => {
    const env = envelope("meridian-pay");
    await page.goto(fileUrl("meridian-pay", "#/inventory?category=tools"));
    await expect(page.getByRole("table", { name: "Tools" })).toBeVisible();
    await page.goto(fileUrl("meridian-pay", "#/inventory?authority=1"));
    const shown = Number(await page.getByRole("table", { name: "Agents" }).getAttribute("aria-rowcount"));
    expect(shown).toBeGreaterThan(0);
    expect(shown).toBeLessThan(env.registry.agents.length);
  });

  test("graph tab draws the architecture graph", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/inventory?view=graph"));
    const canvas = page.getByTestId("graph-canvas").locator("canvas").first();
    await expect(canvas).toBeVisible();
    await expect(page.getByText("Click a node or edge").first()).toBeVisible();
  });
});

test.describe("drift", () => {
  test("shows the authority increase as needing review, with both refs", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/drift"));
    await expect(page.getByRole("heading", { name: "Needs review" })).toBeVisible();
    await expect(page.getByText("payment_access").first()).toBeVisible();
    await expect(page.getByText("needs review").first()).toBeVisible();
    await expect(page.getByText("a1b2c3d")).toBeVisible();
    await expect(page.getByText("e4f5a6b").first()).toBeVisible();
  });

  test("explains how to get a baseline when there is none", async ({ page }) => {
    await page.goto(fileUrl("registry-only", "#/drift"));
    await expect(page.getByText("No baseline in this scan")).toBeVisible();
    await expect(page.getByText("--diff-against origin/main")).toBeVisible();
  });
});

test.describe("risk register", () => {
  test("rows come from the scan, edits produce a TOML snippet", async ({ page }) => {
    const env = envelope("meridian-pay");
    await page.goto(fileUrl("meridian-pay", "#/register"));
    const table = page.getByRole("table", { name: "Risk register" });
    await expect(table.locator("tbody tr")).toHaveCount(env.register.length);
    await expect(table.getByText("transfer")).toBeVisible();
    const target = env.register.find((r: { declared: { treatment: string } | null }) => r.declared?.treatment === "mitigate");
    await page.goto(fileUrl("meridian-pay", `#/register/${encodeURIComponent(target.risk_id)}`));
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Treatment").selectOption("transfer");
    await expect(dialog.getByRole("link", { name: "Prepare underwriting evidence" })).toBeVisible();
    const snippet = await dialog.getByLabel("TOML snippet").inputValue();
    expect(snippet).toContain("[[risk_register]]");
    expect(snippet).toContain(`risk_id   = "${target.risk_id}"`);
    expect(snippet).toContain('treatment = "transfer"');
  });
});

test.describe("insurance and print", () => {
  test("shows the pre-filled assessment with sources and the schedule", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await expect(page.getByRole("heading", { name: "AI Risk Insurance" })).toBeVisible();
    await expect(page.getByText("pre-filled", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("1. General information")).toBeVisible();
    await expect(page.getByText("Insurance requirements (schedule)")).toBeVisible();
    await expect(page.getByText("Policy limit (aggregate)")).toBeVisible();
    await expect(page.getByText("5. Declaration")).toBeVisible();
    await expect(page.getByRole("button", { name: "Print assessment (PDF)" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Print and sign" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Schedule a call" })).toHaveAttribute("href", "https://stoa.insure");
    await page.getByText("Show the evidence pack").click();
    await expect(page.getByRole("heading", { name: "What the agents can do" })).toBeVisible();
  });

  test("the assessment is editable and produces the config snippet", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await expect(page.locator(".assessment")).toContainText("Meridian Pay");
    await page.getByRole("button", { name: "Edit assessment" }).click();
    await page.getByLabel("Applicant company").fill("Meridian Pay Ltd");
    await page.getByLabel("Policy limit (aggregate)").fill("US$ 5,000,000");
    await page.getByRole("button", { name: "Done editing" }).click();
    await expect(page.locator(".assessment")).toContainText("Meridian Pay Ltd");
    await expect(page.locator(".assessment")).toContainText("US$ 5,000,000");
    const snippet = await page.getByLabel("Underwriting config snippet").inputValue();
    expect(snippet).toContain('company        = "Meridian Pay Ltd"');
    expect(snippet).toContain('policy_limit           = "US$ 5,000,000"');
    expect(snippet).toContain("[[performance]]");
  });

  test("print summary is one page and hides the app chrome", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/findings"));
    await page.evaluate(() => { document.documentElement.dataset.print = "summary"; });
    await page.emulateMedia({ media: "print" });
    await expect(page.locator("nav")).toBeHidden();
    await expect(page.locator(".screen-content")).toBeHidden();
    const summary = page.locator(".print-summary");
    await expect(summary).toBeVisible();
    await expect(summary).toContainText("AI agent risk summary");
    const height = await summary.evaluate((el) => el.getBoundingClientRect().height);
    expect(height).toBeLessThan(1000);
  });

  test("print assessment shows the form only", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await page.evaluate(() => { document.documentElement.dataset.print = "pack"; });
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".assessment")).toBeVisible();
    await expect(page.locator(".assessment")).toContainText("5. Declaration");
    await expect(page.locator(".screen-view").first()).toBeHidden();
    await expect(page.locator("nav")).toBeHidden();
  });
});

test.describe("loss outlook", () => {
  test("models the refund agent from the scan and the declared intake", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/loss"));
    await expect(page.getByRole("heading", { name: /A bad year could cost \$/ })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Suggested coverage limit")).toBeVisible();
    await expect(page.locator("svg[role=img]").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Where the loss could come from" })).toBeVisible();
    await expect(page.getByText("AI exclusion applies").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "What would lower it" })).toBeVisible();
    await expect(page.getByText("Not a quote, not a premium, not advice").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Declared limits" })).toBeVisible();
  });

  test("without an intake block it says so and still runs on placeholders", async ({ page }) => {
    await page.goto(fileUrl("registry-only", "#/loss"));
    await expect(page.getByText("No business context declared")).toBeVisible();
    await expect(page.getByRole("heading", { name: /A bad year could cost \$/ })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByLabel("Intake config snippet")).toHaveValue(/\[intake\]/);
  });
});

test.describe("estate and risk model screens", () => {
  test("declared scope, controls, and financial loss render from the registry", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/scope"));
    await expect(page.getByRole("heading", { name: "Declared Scope" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Contradictions" })).toHaveCount(0);
    await expect(page.getByText("Complete", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Edit business context" }).click();
    await page.getByLabel("meridian-front owner").fill("front-desk@meridian.example");
    await page.getByLabel("Release approval").fill("RELEASING.md");
    await page.getByRole("button", { name: "Done editing" }).click();
    const declared = await page.getByLabel("stoa-declared.toml contents").inputValue();
    expect(declared).toContain('owner = "front-desk@meridian.example"');
    expect(declared).toContain('release_approval = "RELEASING.md"');
    expect(declared).toContain("[[risk_register]]");
    const uw = await page.getByLabel(".stoa/underwriting.toml contents").inputValue();
    expect(uw).toContain('sector                = "fintech"');
    await page.goto(fileUrl("meridian-pay", "#/controls"));
    await expect(page.getByRole("heading", { name: "Controls & Safeguards" })).toBeVisible();
    await expect(page.getByText("Human approval").first()).toBeVisible();
    await expect(page.getByText("Kill switch").first()).toBeVisible();
    await expect(page.getByText("Pinned model")).toHaveCount(0);
    await page.goto(fileUrl("meridian-pay", "#/loss"));
    await expect(page.getByRole("heading", { name: "Estimated Financial Loss" })).toBeVisible();
    await expect(page.getByText("500 USD").first()).toBeVisible({ timeout: 30_000 });
    await page.goto(fileUrl("meridian-pay", "#/risk"));
    await expect(page.getByRole("tab", { name: /Findings/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("navigation", { name: "Screens" })).toContainText("AI Risk Insurance");
    await expect(page.getByRole("navigation", { name: "Screens" })).not.toContainText("Declared Scope");
  });
});

test.describe("reviewer", () => {
  test("the top bar shows who is reviewing and keeps the print action", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/overview"));
    const btn = page.getByRole("button", { name: /Reviewing as Priya Natarajan, Chief Risk Officer at Meridian Pay/ });
    await expect(btn).toBeVisible();
    await btn.click();
    await expect(page.getByRole("menuitem", { name: "Print summary" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Open the insurance assessment" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await page.goto(fileUrl("registry-only", "#/overview"));
    await expect(page.getByRole("button", { name: /Reviewing as Risk officer/ })).toBeVisible();
  });
});

test.describe("a customer's first scan", () => {
  test("the assessment only answers what the scan evidences", async ({ page }) => {
    await page.goto(fileUrl("first-run", "#/evidence"));
    // A lone scan cannot show drift is tracked: the answer is left to confirm.
    const drift = page.getByText("Drift mitigation", { exact: true }).locator("xpath=ancestor::*[contains(., 'To be confirmed')][1]");
    await expect(drift).toContainText("no baseline or scan history yet");
    await expect(page.getByText("in CI", { exact: false })).toHaveCount(0);
    // Nothing from a demo applicant leaks into a customer's form. (The agents
    // are named meridian-* because the fixture scans that example's code.)
    for (const leaked of ["Meridian Pay", "Priya", "meridian.example", "Harbour Street", "XYZ Fin", "Jordan Rivera", "fraud-triage"]) {
      await expect(page.getByText(leaked, { exact: false })).toHaveCount(0);
    }
    await expect(page.getByText("Acme Support").first()).toBeVisible();
  });

  test("the demo, which has a baseline, still shows drift as tracked", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await expect(page.getByText("capability drift tracked via stoa diff")).toBeVisible();
  });

  test("with no agents there is no form to sign", async ({ page }) => {
    await page.goto(fileUrl("no-agents", "#/evidence"));
    await expect(page.getByRole("heading", { name: "No agents to assess" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Print and sign" })).toHaveCount(0);
    await expect(page.getByText("Policy limit", { exact: false })).toHaveCount(0);
    await expect(page.getByText("1 file scanned").first()).toBeVisible();
  });
});

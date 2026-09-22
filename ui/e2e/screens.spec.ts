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
    // The demo's three critical records are two findings: account actions was seen in code and on AWS.
    await page.goto(fileUrl("meridian-pay", "#/findings?severity=critical"));
    await expect(page.getByText("2 of 21 shown (filtered)")).toBeVisible();
    const table = page.getByRole("table", { name: "Findings", exact: true });
    await expect(table).toHaveAttribute("aria-rowcount", "1");
    await page.getByRole("button", { name: /^High\s+\d+$/ }).click();
    await expect.poll(() => page.evaluate(() => window.location.hash)).toContain("severity=critical%2Chigh");
    await page.reload();
    await expect(page.getByText("3 of 21 shown (filtered)")).toBeVisible();
    await expect(table).toHaveAttribute("aria-rowcount", "2");
    // The High filter button carries the same count the caption reports.
    await expect(page.getByRole("button", { name: /^High\s+3$/ })).toBeVisible();
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
    await expect(dialog.locator("pre").first()).toContainText("</script><script>alert(1)</script>");
    expect(dialogs).toEqual([]);
  });

  test("5,000 findings stay virtualized", async ({ page }) => {
    await page.goto(fileUrl("large", "#/findings"));
    const table = page.getByRole("table", { name: "Findings", exact: true });
    // Collapsed, the table is one row per rule. Opened, it is every finding, and must still render a window.
    await page.getByRole("button", { name: "Expand all" }).click();
    await expect.poll(async () => Number(await table.getAttribute("aria-rowcount"))).toBeGreaterThan(2000);
    const rendered = await table.getByRole("row").count();
    expect(rendered).toBeLessThan(120);
    await table.evaluate((el) => { el.scrollTop = 100000; });
    await expect.poll(async () => Number(await table.getByRole("row").last().getAttribute("aria-rowindex"))).toBeGreaterThan(1500);
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
    await expect(page.getByRole("heading", { name: "9 of 23 answers came from your code" })).toBeVisible();
    await expect(page.getByText("8 need your confirmation. 6 are agreed with the carrier later.")).toBeVisible();
    await expect(page.getByText("1. General information")).toBeVisible();
    await expect(page.getByText("Insurance requirements (schedule)")).toBeVisible();
    await expect(page.getByText("Policy limit (aggregate)")).toBeVisible();
    await expect(page.getByText("5. Declaration")).toBeVisible();
    await page.getByRole("button", { name: "Export" }).click();
    await expect(page.getByRole("menuitem")).toHaveText(["Print assessment (PDF)", "Print summary", "Download JSON", "Copy JSON"]);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("link", { name: "Schedule a call" })).toHaveAttribute("href", "https://stoa.insure");
    await page.getByText("Show the evidence pack").click();
    await expect(page.getByRole("heading", { name: "What the agents can do" })).toBeVisible();
  });

  test("the assessment is editable and produces the config snippet", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await expect(page.locator(".assessment")).toContainText("Meridian Pay");
    await page.getByRole("button", { name: "Review 8 unconfirmed fields" }).click();
    await page.getByLabel("Applicant company").fill("Meridian Pay Ltd");
    await page.getByLabel("Policy limit (aggregate)").fill("US$ 5,000,000");
    await page.getByRole("button", { name: "Stop editing" }).click();
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
    await expect(page.getByRole("heading", { name: /A bad year could cost/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "Where the loss could come from" })).toBeVisible();
    await expect(page.getByText("AI exclusion applies").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "What would lower it" })).toBeVisible();
    // Removed on request: the exceedance curve, the four year tiles, the declared-limits table and the closing disclaimer.
    for (const gone of ["Declared limits", "Not a quote, not a premium, not advice", "Insurable loss in one year", "a severe year", "expected annual loss"]) await expect(page.getByText(gone, { exact: false })).toHaveCount(0);
    // Cases shown are US financial services only, source-backed, under a few hundred million.
    await expect(page.getByText("Lemonade")).toBeVisible();
    await expect(page.getByText("Earnest Operations")).toBeVisible();
    // Over the cap, or a hidden loss type: never shown. Other US sectors fill in when financial services has fewer than two.
    for (const gone of ["Knight Capital", "Facebook", "Zillow", "Data Loss and Corruption", "Performance Failure"]) await expect(page.getByText(gone, { exact: true })).toHaveCount(0);
    await expect(page.getByText("Amazon (Q Developer)")).toBeVisible();
    await expect(page.getByRole("heading", { name: "How the modeled loss has moved" })).toBeVisible();
    await expect(page.getByText("21 Jul 2026 · a1b2c3d")).toBeVisible();
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
    // The list omits human approval (it has the Overview's gate and tile) and sandboxing.
    const detected = page.getByRole("heading", { name: "Safeguards detected" }).locator("xpath=following::div[contains(@class,'panel')][1]");
    await expect(detected).toContainText("Kill switch");
    await expect(detected).not.toContainText("Human approval");
    await expect(detected).not.toContainText("Sandboxing");
    await expect(page.getByText("Safeguards not detected where expected")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Recommended controls to add" })).toBeVisible();
    const recs = page.getByRole("heading", { name: "Recommended controls to add" }).locator("xpath=following::ol[1]").getByRole("listitem");
    await expect(recs).toHaveCount(3);
    await expect(recs.first()).toContainText("A payment can be charged twice if a request is retried.");
    await expect(recs.first()).not.toContainText(/AI008|CTRL00|account_tools\.py/);
    await expect(page.getByText("Pinned model")).toHaveCount(0);
    await page.goto(fileUrl("meridian-pay", "#/loss"));
    await expect(page.getByRole("heading", { name: "Financial Exposure", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What would lower it" })).toBeVisible({ timeout: 60_000 });
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
    await expect(page.getByTestId("company").filter({ hasText: "Acme Billing" })).toBeVisible();
  });
});

test.describe("insurance page: one checklist, one primary button", () => {
  test("no step is checked while its fields are unconfirmed, and the button follows the next step", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    const view = page.locator("main .screen-content");
    await expect(view.locator(".btn-primary")).toHaveCount(1);
    await expect(view.locator(".btn-primary")).toHaveText("Review 8 unconfirmed fields");
    const steps = view.getByRole("listitem").filter({ hasText: /Answers pre-filled|Confirm identity|Sign the declaration|Submit through Stoa/ });
    await expect(steps).toHaveCount(4);
    await expect(steps.nth(0)).toContainText("(complete)");
    await expect(steps.nth(1)).not.toContainText("(complete)");
    await expect(steps.nth(1)).toHaveAttribute("aria-current", "step");
    await expect(steps.nth(3)).toContainText("Your Stoa advisor sends the signed assessment and evidence pack to the carrier.");

    await view.locator(".btn-primary").click();
    await page.getByRole("button", { name: "I have reviewed these fields" }).click();
    await expect(steps.nth(1)).toContainText("(complete)");
    await expect(steps.nth(2)).toHaveAttribute("aria-current", "step");
    await expect(view.locator(".btn-primary")).toHaveCount(1);
    await expect(view.locator(".btn-primary")).toHaveText("Print and sign");
  });

  test("the carrier sentence is said once, and the old wording is gone", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    const view = page.locator("main .screen-content");
    await expect(view.getByText("Stoa prepares the evidence. Munich Re prices and issues.")).toHaveCount(1);
    await expect(view.getByText(/prices? and issues?/)).toHaveCount(1);
    // The heading word is gone. ("Update / rollback readiness" is a question on the carrier's form and stays.)
    await expect(view.getByText("Readiness", { exact: true })).toHaveCount(0);
    for (const gone of ["% pre-filled", "your Munich Re aiSure contact", "Send the signed PDF"]) await expect(view.getByText(gone, { exact: false })).toHaveCount(0);
    await expect(view.getByText(".stoa/underwriting.toml", { exact: false })).toHaveCount(0);
    // Three provenance chips, plus terms settled with the carrier later.
    const chips = await view.locator(".assessment .chip").allTextContents();
    // The legend lists all four; no other provenance label exists anywhere on the form.
    expect([...new Set(chips)].sort()).toEqual(["Agreed with the carrier later", "From your code", "Needs your input", "You told us"]);
  });
});

test.describe("financial exposure explains itself", () => {
  test("what drives the estimate, by source, with declared inputs marked", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/loss"));
    const drivers = page.getByRole("region", { name: "What drives this estimate" });
    await expect(drivers).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: /A bad year could cost \$[\d.]+M/ })).toBeVisible();
    await expect(page.getByText("Modeled", { exact: true })).toBeVisible();
    await expect(drivers).toContainText("From the scan");
    await expect(drivers).toContainText("Declared by you");
    await expect(drivers).toContainText("From Stoa's loss data");
    await expect(drivers.getByText("declared", { exact: true })).toBeVisible();
    await expect(drivers).toContainText("$40M revenue");
    await expect(drivers).toContainText("Data Leakage is the largest driver");
    await expect(drivers).toContainText("Driven by your business profile and data handled, not by scan findings.");
    await expect(page.getByRole("img", { name: /Chance of exceeding a given loss/ })).toHaveCount(0);
    // The bad year here is the bad year on the Overview.
    const here = (await page.getByRole("heading", { name: /A bad year could cost/ }).textContent())!.match(/\$[\d.]+[kM]/)![0];
    await page.goto(fileUrl("meridian-pay", "#/overview"));
    await expect(page.getByRole("region", { name: "Where you stand" })).toContainText(`Modeled loss in a bad year is ${here}.`, { timeout: 60_000 });
  });
});

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
    await page.getByRole("button", { name: /high\s+\d+/ }).first().click();
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
    await expect(page.getByText("Click a node or edge")).toBeVisible();
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

test.describe("evidence and print", () => {
  test("two views of the same data", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence?view=officer"));
    await expect(page.getByRole("heading", { name: "What is wrong" })).toBeVisible();
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await expect(page.getByRole("heading", { name: "What the agents can do" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Controls: observed versus declared" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Confidence per dimension" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy JSON" })).toBeVisible();
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

  test("print evidence pack shows the underwriter view only", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/evidence"));
    await page.evaluate(() => { document.documentElement.dataset.print = "pack"; });
    await page.emulateMedia({ media: "print" });
    const pack = page.locator(".print-pack");
    await expect(pack).toBeVisible();
    await expect(pack).toContainText("AI agent evidence pack");
    await expect(pack.getByRole("heading", { name: "What the agents can do" })).toBeVisible();
    await expect(page.locator(".screen-view")).toBeHidden();
    await expect(page.locator("nav")).toBeHidden();
  });
});

test.describe("estate and risk model screens", () => {
  test("declared scope, controls, and financial loss render from the registry", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay", "#/scope"));
    await expect(page.getByRole("heading", { name: "Declared Scope" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Contradictions" })).toBeVisible();
    await page.goto(fileUrl("meridian-pay", "#/controls"));
    await expect(page.getByRole("heading", { name: "Controls & Safeguards" })).toBeVisible();
    await expect(page.getByText("Human approval").first()).toBeVisible();
    await page.goto(fileUrl("meridian-pay", "#/loss"));
    await expect(page.getByRole("heading", { name: "Estimated Financial Loss" })).toBeVisible();
    await expect(page.getByText("500 USD").first()).toBeVisible();
    await page.goto(fileUrl("meridian-pay", "#/risk"));
    await expect(page.getByRole("tab", { name: /Findings/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("navigation", { name: "Screens" })).toContainText("AI Risk Insurance");
  });
});

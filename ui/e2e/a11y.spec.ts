import { pathToFileURL } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { dashboardPath } from "./global-setup";
import { ROUTES } from "./routes";

/** WCAG 2.x A/AA automated checks on every screen and on an open drawer. No serious or critical violations. */
test.describe("accessibility", () => {
  for (const route of ROUTES) {
    test(`no serious violations on ${route}`, async ({ page }) => {
      await page.goto(pathToFileURL(dashboardPath("meridian-pay")).href + route);
      await expect(page.locator("#root")).not.toBeEmpty();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
    });
  }

  test("no serious violations on the demo banner, an opened scan, and a refused file", async ({ page }) => {
    const check = async () => {
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
    };
    await page.goto(pathToFileURL(dashboardPath("demo")).href);
    await expect(page.getByText("Demo data for a fictional company")).toBeVisible();
    await check();
    await page.locator('input[type="file"]').first().setInputFiles(dashboardPath("meridian-pay").replace("meridian-pay.html", "first-run.json"));
    await expect(page.getByText("Nothing was uploaded", { exact: false })).toBeVisible();
    await check();
    await page.locator('input[type="file"]').first().setInputFiles(dashboardPath("hostile").replace("hostile.html", "../../fixtures/meridian-pay.baseline.json"));
    await expect(page.getByRole("alert")).toBeVisible();
    await check();
  });

  test("no serious violations with a finding drawer open", async ({ page }) => {
    await page.goto(pathToFileURL(dashboardPath("meridian-pay")).href + "#/findings");
    // Row 1 is a rule that fired on several agents: it opens its list. Row 2 is then one finding.
    const table = page.getByRole("table", { name: "Findings", exact: true });
    await table.getByRole("row").nth(1).click();
    await table.getByRole("row").nth(2).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
  });

  test("keyboard: a table row opens on Enter and Escape closes the drawer", async ({ page }) => {
    await page.goto(pathToFileURL(dashboardPath("meridian-pay")).href + "#/findings");
    const table = page.getByRole("table", { name: "Findings", exact: true });
    // Enter on a rule that fired more than once opens its findings; Enter on a finding opens the drawer.
    await table.getByRole("row").nth(1).focus();
    await page.keyboard.press("Enter");
    await table.getByRole("row").nth(2).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});

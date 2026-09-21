import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { dashboardPath } from "./global-setup";
import { ROUTES } from "./routes";

function fileUrl(name: string, hash = ""): string {
  return pathToFileURL(dashboardPath(name)).href + hash;
}

/** Fail the test on any request that is not the page itself. */
function armNetworkTrap(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("file://")) seen.push(url);
  });
  return seen;
}

test.describe("dashboard over file://", () => {
  test("renders every route with zero network requests and no dialogs", async ({ page }) => {
    const requests = armNetworkTrap(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("dialog", async (dialog) => {
      errors.push(`dialog: ${dialog.message()}`);
      await dialog.dismiss();
    });
    for (const route of ROUTES) {
      await page.goto(fileUrl("meridian-pay", route));
      await expect(page.locator("#root")).not.toBeEmpty();
      await expect(page.getByText("meridian-pay").first()).toBeVisible();
    }
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("ships a hash-pinned CSP that the app runs under", async ({ page }) => {
    await page.goto(fileUrl("meridian-pay"));
    const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content");
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toMatch(/script-src 'sha256-[A-Za-z0-9+/=]+'/);
    expect(csp).not.toContain("unsafe-inline");
    await expect(page.locator("#root")).not.toBeEmpty();
  });

  test("hostile fixture renders as inert text", async ({ page }) => {
    const errors: string[] = [];
    page.on("dialog", async (dialog) => {
      errors.push(`dialog: ${dialog.message()}`);
      await dialog.dismiss();
    });
    await page.goto(fileUrl("hostile"));
    await expect(page.locator("#root")).not.toBeEmpty();
    // The template carries a fixed number of script tags; a payload that
    // escaped the JSON tag would add one.
    const html = readFileSync(dashboardPath("hostile"), "utf8");
    const templateScripts = (readFileSync(dashboardPath("meridian-pay"), "utf8").match(/<script\b/g) ?? []).length;
    expect((html.match(/<script\b/g) ?? []).length).toBe(templateScripts);
    expect(html).not.toContain("</script><script>alert(1)</script>");
    // Same template, so the live DOM must hold the same number of script
    // elements as the clean fixture's page (one template script removes
    // itself after running, so the DOM count is compared page to page).
    const hostileDom = await page.evaluate(() => document.scripts.length);
    await page.goto(fileUrl("meridian-pay"));
    await expect(page.locator("#root")).not.toBeEmpty();
    expect(hostileDom).toBe(await page.evaluate(() => document.scripts.length));
    expect(errors).toEqual([]);
  });

  // A customer's first scan has no declarations, business inputs, baseline or
  // history, and may find no agents at all. No screen may throw or go blank.
  for (const [fixture, repository] of [["first-run", "acme-support"], ["no-agents", "acme-billing"]] as const) {
    test(`${fixture}: every route renders without errors`, async ({ page }) => {
      const requests = armNetworkTrap(page);
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(String(error)));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`console: ${message.text()}`);
      });
      for (const route of ROUTES) {
        await page.goto(fileUrl(fixture, route));
        await expect(page.locator("#root")).not.toBeEmpty();
        await expect(page.getByText(repository).first()).toBeVisible();
        await expect(page.locator("main")).not.toBeEmpty();
        await expect(page.getByText(/NaN|undefined|\[object Object\]/)).toHaveCount(0);
      }
      expect(requests).toEqual([]);
      expect(errors).toEqual([]);
    });
  }

  test("large fixture loads", async ({ page }) => {
    await page.goto(fileUrl("large"));
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect(page.getByText("meridian-pay-large").first()).toBeVisible();
  });
});

import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { OUT_DIR, dashboardPath } from "./global-setup";

/** The file picker sits in the reviewer menu. */
async function pickFile(page: Page, file: string): Promise<void> {
  await page.getByRole("button", { name: /Reviewing as/ }).click();
  await page.locator('input[type="file"]').first().setInputFiles(file);
}


const demoUrl = (hash = "") => pathToFileURL(dashboardPath("demo")).href + hash;

/** Opening your own scan in a dashboard page you already have, such as the hosted demo. */
test.describe("open a scan from disk", () => {
  test("no banner on a dashboard's own scan, demo or not; the reviewer menu is the way in", async ({ page }) => {
    await page.goto(demoUrl());
    await expect(page.getByText("Demo data", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open your scan" })).toHaveCount(0);
    await page.getByRole("button", { name: /Reviewing as/ }).click();
    await expect(page.getByRole("menuitem", { name: "Open a scan file…" })).toBeVisible();
  });

  test("a customer's JSON replaces the demo, with no network request", async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (r) => { if (!r.url().startsWith("file://")) requests.push(r.url()); });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    // Start on a deep link into the demo's data, which the new scan does not have.
    await page.goto(demoUrl("#/findings?severity=critical"));
    await expect(page.getByTestId("company").filter({ hasText: "Meridian Pay" })).toBeVisible();

    await pickFile(page, resolve(OUT_DIR, "first-run.json"));
    await expect(page.getByTestId("company").filter({ hasText: "Acme Support" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("first-run.json")).toBeVisible();
    await expect(page.getByText("Nothing was uploaded", { exact: false })).toBeVisible();
    // Nothing of the demo applicant survives the switch, on any screen.
    for (const route of ["#/evidence", "#/loss", "#/inventory"]) {
      await page.goto(demoUrl(route));
      // A navigation reloads the page, so the embedded demo is back: reopen.
      await pickFile(page, resolve(OUT_DIR, "first-run.json"));
      await expect(page.getByTestId("company").filter({ hasText: "Acme Support" })).toBeVisible();
      await expect(page.getByText("Priya", { exact: false })).toHaveCount(0);
      await expect(page.getByText("Meridian Pay", { exact: false })).toHaveCount(0);
    }
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("a whole stoa-dashboard.html can be opened too", async ({ page }) => {
    await page.goto(demoUrl());
    await pickFile(page, dashboardPath("no-agents"));
    await expect(page.getByTestId("company").filter({ hasText: "Acme Billing" })).toBeVisible();
    await expect(page.getByText("no-agents.html")).toBeVisible();
  });

  test("a bad file is refused and the scan on screen stays", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    const junk = resolve(OUT_DIR, "junk.json");
    writeFileSync(junk, '{"schema":"stoa-dashboard/1.0","registry":{"schema_version":"1.0","agents":"</script><script>alert(1)</script>"}}');
    await page.goto(demoUrl());
    await pickFile(page, junk);
    await expect(page.getByRole("alert")).toContainText("could not be opened");
    await expect(page.getByRole("alert")).toContainText("registry.agents");
    await expect(page.getByTestId("company").filter({ hasText: "Meridian Pay" })).toBeVisible();

    // A raw registry gets told exactly what to run instead.
    await pickFile(page, resolve(OUT_DIR, "..", "..", "fixtures", "meridian-pay.baseline.json"));
    await expect(page.getByRole("alert")).toContainText("--json-out");
    await page.getByRole("button", { name: "Dismiss" }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("the reviewer menu offers it on every dashboard", async ({ page }) => {
    await page.goto(pathToFileURL(dashboardPath("first-run")).href);
    await page.getByRole("button", { name: /Reviewing as/ }).click();
    await expect(page.getByRole("menuitem", { name: "Open a scan file…" })).toBeVisible();
  });
});

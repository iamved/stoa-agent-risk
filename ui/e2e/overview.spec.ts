import { pathToFileURL } from "node:url";
import { expect, test } from "@playwright/test";
import { dashboardPath } from "./global-setup";

const url = (name: string, hash = "#/overview") => pathToFileURL(dashboardPath(name)).href + hash;

/** The home page: where you stand, four questions, what needs attention, what changed. */
test.describe("overview", () => {
  test("the demo reads as a briefing, and every figure links to its screen", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const standing = page.getByRole("region", { name: "Where you stand" });
    await expect(standing).toContainText("2 agents can move money on their own, and neither requires human approval.");
    await expect(standing).toContainText(/A bad year could cost \$[\d.]+M, and your cyber policy excludes AI\./);
    await expect(standing).toContainText("3 things changed since the last scan.");
    await expect(page.getByRole("button", { name: "Export board report" })).toBeVisible();
    // A local file's path means nothing to anyone else, so no share button over file://.
    await expect(page.getByRole("button", { name: "Share this view" })).toHaveCount(0);

    for (const question of ["What we have", "What is wrong", "Are we protected", "What it could cost"]) await expect(page.getByRole("heading", { name: question })).toBeVisible();
    await expect(page.getByText("2 can move money · 13 tools · 4 model providers")).toBeVisible();
    await expect(page.getByText("6 medium · 12 low · 21 in total")).toBeVisible();
    await expect(page.getByText("+1 high since last scan")).toBeVisible();
    await expect(page.getByText("0 of 2")).toBeVisible();
    await expect(page.getByText("AI losses covered today: $0")).toBeVisible();
    await expect(page.getByText(/Modelled for .+ An indication, not a quote\./)).toBeVisible();

    await page.getByRole("link", { name: "View safeguards" }).click();
    await expect(page).toHaveURL(/#\/controls/);
  });

  test("attention items are grouped, and only a registered risk offers an owner", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const list = page.getByRole("region", { name: "Needs your attention" });
    await expect(list.getByRole("listitem")).toHaveCount(4);
    const first = list.getByRole("listitem").first();
    await expect(first).toContainText("Declared autonomy does not match what the code does.");
    await expect(first).toContainText("2 agents · Mandate overreach · 1 marked for transfer to insurance");
    await expect(list.getByRole("link", { name: "Assign owner" })).toHaveCount(1);
    await first.getByRole("link", { name: "Assign owner" }).click();
    await expect(page).toHaveURL(/#\/register\/mandate-overreach/);
    await page.goBack();
    await list.getByRole("link", { name: "View evidence" }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("what changed comes from the baseline, and the sidebar flags high findings", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const changed = page.getByRole("region", { name: "What changed" });
    await expect(changed).toContainText("One more agent can now move money.");
    await expect(changed).toContainText("1 new high-severity finding.");
    await expect(changed).toContainText("No agents added or removed.");
    const nav = page.getByRole("navigation", { name: "Screens" });
    for (const label of ["Agent Inventory", "Findings", "Controls & Safeguards", "Financial Exposure", "AI Risk Insurance"]) await expect(nav).toContainText(label);
    await expect(nav).toContainText("3 high");
    await expect(page.getByText("application code, AWS and Databricks definitions")).toBeVisible();
  });

  test("a first scan claims nothing it cannot know", async ({ page }) => {
    await page.goto(url("first-run"));
    const standing = page.getByRole("region", { name: "Where you stand" });
    await expect(standing).toContainText("2 agents can move money on their own, and neither requires human approval.");
    await expect(standing).not.toContainText("bad year");
    await expect(standing).not.toContainText("changed since");
    await expect(page.getByText("Not estimated yet")).toBeVisible();
    await expect(page.getByText("$", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "What changed" })).toContainText("stoa scan . --diff-against origin/main");
    await expect(page.getByText("No baseline to compare against")).toBeVisible();
    await expect(page.getByText("No dimension is at elevated exposure in this scan.")).toBeVisible();
  });

  test("a scan with no agents says so plainly", async ({ page }) => {
    await page.goto(url("no-agents"));
    await expect(page.getByRole("region", { name: "Where you stand" })).toContainText("No AI agents were found in this scan");
    await expect(page.getByText("There are no agents to model.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Needs your attention" })).toContainText("No open findings.");
    await expect(page.getByRole("heading", { name: "Insurance assessment" })).toHaveCount(0);
  });

  test("it reads at phone width without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 800 });
    await page.goto(url("meridian-pay"));
    await expect(page.getByRole("region", { name: "Where you stand" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});

import { pathToFileURL } from "node:url";
import { expect, test } from "@playwright/test";
import { dashboardPath } from "./global-setup";

const url = (name: string, hash = "#/overview") => pathToFileURL(dashboardPath(name)).href + hash;

/** The home page: scope strip, verdict band, four tiles, two panels, three footer cards. */
test.describe("overview", () => {
  test("it holds exactly the agreed sections, and links to all five other screens", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    await expect(page.getByTestId("scope-strip")).toContainText("application code, AWS and Databricks definitions · 11 files. Static scan of code and configuration. Controls outside the scanned sources are not visible.");
    const main = page.locator("main .screen-content");
    await expect(main.getByText("What the code makes possible, not what has happened.")).toBeVisible();
    await expect(main.getByRole("region", { name: "Where you stand" })).toBeVisible();
    await expect(main.getByRole("heading", { level: 2 })).toHaveText(["What we have", "What is wrong", "Are we protected", "What it could cost", "Needs your attention", "What changed", "Where exposure is elevated", "Risk register", "Insurance assessment", "Agent Risk Flow Graph"]);
    // Removed on purpose: the elevated-agents card, the combined money-or-write card, the long findings list.
    for (const gone of ["Agents at elevated exposure", "Can move money or write to systems", "Top findings", "Findings by dimension"]) await expect(main.getByText(gone)).toHaveCount(0);
    const targets = await main.getByRole("link").evaluateAll((links) => [...new Set(links.map((a) => (a.getAttribute("href") ?? "").split(/[/?]/)[1]))]);
    for (const screen of ["inventory", "findings", "controls", "loss", "evidence", "drift", "register"]) expect(targets, screen).toContain(screen);
  });

  test("the verdict is built from the scan, in detection language", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const verdict = page.getByRole("region", { name: "Where you stand" });
    await expect(verdict).toContainText("2 agents can move money on their own, and no human approval was detected for either.");
    await expect(verdict).toContainText(/Modeled loss in a bad year is \$[\d.]+M\./);
    await expect(verdict).toContainText("3 things changed since the last scan.");
    await expect(verdict.getByRole("button")).toHaveText(["Export board report"]);
  });

  test("the four tiles answer their question with figures from the scan", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const main = page.locator("main .screen-content");
    await expect(main.getByText("2 with payment capability · 13 tools · 4 model providers")).toBeVisible();
    await expect(main.getByText("11 discovered records")).toBeVisible();
    await expect(main.getByText("6 medium · 12 low · 21 in total")).toBeVisible();
    await expect(main.getByText("+1 high since last scan")).toBeVisible();
    await expect(main.getByText("Human approval detected on 0 of 2 agents that can move money")).toBeVisible();
    await expect(main.getByText("8 of 8 tools that can move money have no guardrail detected")).toBeVisible();
    await expect(main.getByText(/Modeled\. An average year is about \$\d+k\./)).toBeVisible();
    await expect(main.getByText(/1 year in 100, for .+, the agent with the largest figure\./)).toBeVisible();
    const cover = main.getByText("Declared cover for AI losses:");
    await expect(cover).toContainText("$0");
    await expect(cover.getByText("declared", { exact: true })).toHaveAttribute("title", "From your declared insurance details. Not a reviewed policy.");
    await main.getByRole("link", { name: "View safeguards" }).click();
    await expect(page).toHaveURL(/#\/controls/);
  });

  test("attention rows give a next action, and no owner, date or assign control", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const list = page.getByRole("region", { name: "Needs your attention" });
    await expect(list).toContainText("Highest severity first. The same problem on several agents is shown once.");
    const rows = list.getByRole("listitem");
    await expect(rows).toHaveCount(4);
    await expect(rows.first()).toContainText("Declared autonomy does not match what the code does.");
    await expect(rows.first()).toContainText("2 agents · Mandate overreach · 1 marked for transfer");
    for (const row of await rows.all()) await expect(row).toContainText("Next action.");
    await expect(list.getByRole("button")).toHaveCount(0);
    // No workflow UI. (A declared owner shown as a fact, from stoa-declared.toml, is allowed.)
    await expect(page.locator("main .screen-content").getByText(/assign owner|assign to|overdue|due by|due date/i)).toHaveCount(0);
    await expect(list.getByRole("link", { name: "View all 21 findings" })).toBeVisible();
    await rows.nth(1).getByRole("link").click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("what changed comes from the baseline, capability changes first", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const changed = page.getByRole("region", { name: "What changed" });
    const lines = changed.getByRole("listitem");
    await expect(lines.nth(0)).toContainText("One more agent can now move money.");
    await expect(lines.nth(0)).toContainText("account-actions gained payment access.");
    await expect(lines.nth(1)).toContainText("1 new high-severity finding.");
    await expect(lines.nth(1)).toContainText("1 known high-severity finding now has a second evidence location.");
    await expect(lines.nth(2)).toContainText("2 of 5 agents are now elevated.");
    await expect(lines.nth(3)).toContainText("No agents added or removed.");
    await expect(changed).not.toContainText(/reopened|because|follow from/i);
    await changed.getByRole("link", { name: "Open the change log" }).click();
    await expect(page).toHaveURL(/#\/drift/);
  });

  test("the footer cards summarize, and the sidebar carries one badge", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const elevated = page.getByRole("region", { name: "Where exposure is elevated" });
    await expect(elevated.getByRole("listitem")).toHaveCount(2);
    await expect(elevated).toContainText("Agents can do more than they are declared to do.");
    await expect(elevated).toContainText("The other 6 dimensions are low or show no findings. A finding can affect more than one dimension.");
    await expect(elevated.getByRole("link", { name: "See all 8" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Risk register" })).toContainText("1 marked for transfer · 1 being mitigated · 4 with no treatment recorded");
    const assessment = page.getByRole("region", { name: "Insurance assessment" });
    await expect(assessment).toContainText("9 of 23 answers came from your code. 8 need your confirmation.");
    await expect(assessment.getByRole("link")).toHaveText(["Continue the assessment"]);
    const nav = page.getByRole("navigation", { name: "Screens" });
    await expect(nav.getByRole("listitem")).toHaveText([/^Overview$/, /^Agent Inventory\s*5$/, /^Findings\s*3 high$/, /^Controls & Safeguards$/, /^Financial Exposure$/, /^AI Risk Insurance$/]);
    await expect(page.getByText("26", { exact: true })).toHaveCount(0);
  });

  test("a first scan claims nothing it cannot know", async ({ page }) => {
    await page.goto(url("first-run"));
    const verdict = page.getByRole("region", { name: "Where you stand" });
    await expect(verdict).toContainText("2 agents can move money on their own, and no human approval was detected for either.");
    await expect(verdict).not.toContainText("Modeled");
    await expect(verdict).not.toContainText("changed since");
    await expect(page.getByText("Not estimated yet")).toBeVisible();
    await expect(page.locator("main").getByText("$", { exact: false })).toHaveCount(0);
    // No declaration file, so nothing links the two Databricks endpoints to their code: 7 agents, 11 records.
    await expect(page.locator("main .screen-content").getByText("11 discovered records")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Screens" })).toContainText("Agent Inventory7");
    await expect(page.getByRole("region", { name: "What changed" })).toContainText("stoa scan . --diff-against origin/main");
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

  test("the flow graph draws each unique agent's path and opens a box's details", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const flow = page.getByRole("region", { name: "Agent Risk Flow Graph" });
    await flow.scrollIntoViewIfNeeded();
    const picker = flow.getByRole("group", { name: "Agents" });
    await expect(picker.getByRole("button")).toHaveCount(5);
    await expect(picker.getByRole("button", { pressed: true })).toHaveText(/account-actions/);
    const diagram = flow.getByRole("group", { name: "Risk path for account-actions" });
    await expect(diagram).toBeVisible();
    for (const lane of ["Request arrives", "Agent decides", "Approval gate", "Tools it can call", "What it can touch"]) await expect(diagram).toContainText(lane);
    await expect(diagram.getByRole("button")).toHaveCount(1 + 3 + 1 + 4 + 1 + 6 + 6);
    await expect(flow).toContainText("Defined in code · Deployed on AWS");
    await expect(flow).toContainText("account-actions: 6 tools, 6 of them money-moving or high impact with no guardrail detected; 3 safeguards detected; 6 findings.");

    await diagram.getByRole("button", { name: /^Human approval, no human approval detected/ }).click();
    await expect(flow).toContainText("No human approval detected. 6 money-moving or high-impact tools can run without a person confirming.");
    await expect(flow).toContainText("Declared autonomy does not match what the code does.");
    await flow.getByRole("button", { name: "Back to agent overview" }).click();
    await expect(flow).toContainText("Risk intensity, by dimension (0 to 100)");

    await picker.getByRole("button", { name: /meridian-escalation/ }).click();
    await expect(flow.getByRole("group", { name: "Risk path for meridian-escalation" })).toContainText("No tool definitions detected");
    // Keyboard: a box opens on Enter.
    await flow.getByRole("group", { name: "Risk path for meridian-escalation" }).getByRole("button", { name: /^Incoming request/ }).focus();
    await page.keyboard.press("Enter");
    await expect(flow).toContainText("Everything the agent does starts here.");
    await expect(flow.getByText(/assign|owner .*due|overdue/i)).toHaveCount(0);
  });

  test("the flow graph follows a first scan and is absent with no agents", async ({ page }) => {
    await page.goto(url("first-run"));
    const flow = page.getByRole("region", { name: "Agent Risk Flow Graph" });
    await expect(flow.getByRole("group", { name: "Agents" }).getByRole("button")).toHaveCount(7);
    await page.goto(url("no-agents"));
    await expect(page.getByRole("heading", { name: "Agent Risk Flow Graph" })).toHaveCount(0);
  });
});

import { pathToFileURL } from "node:url";
import { expect, test } from "@playwright/test";
import { dashboardPath } from "./global-setup";

const url = (name: string, hash = "#/overview") => pathToFileURL(dashboardPath(name)).href + hash;

/** The home page: scope strip, verdict band, four tiles, two panels, three footer cards. */
test.describe("overview", () => {
  test("it holds exactly the agreed sections, and links to the other screens", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    // The header names the company from the setup details; the repository name stays in its tooltip.
    await expect(page.getByTestId("company")).toHaveText("Meridian Pay");
    await expect(page.getByTestId("company")).toHaveAttribute("title", "meridian-pay");
    const main = page.locator("main .screen-content");
    await expect(main.getByText("Static scan of code and configuration", { exact: false })).toHaveCount(0);
    await expect(main.getByText("What the code makes possible, not what has happened.")).toHaveCount(0);
    await expect(main.getByRole("region", { name: "Where you stand" })).toBeVisible();
    await expect(main.getByRole("heading", { level: 2 })).toHaveText(["Agent Inventory", "Risk Mapping", "Estimated Failures Cost", "Needs your attention", "What changed", "Insurance assessment", "Agent Risk Flow Graph"]);
    // Removed on purpose: the elevated-agents card, the combined money-or-write card, the long findings list.
    for (const gone of ["Agents at elevated exposure", "Can move money or write to systems", "Top findings", "Findings by dimension", "Where exposure is elevated", "Risk register", "risks recorded"]) await expect(main.getByText(gone)).toHaveCount(0);
    const targets = await main.getByRole("link").evaluateAll((links) => [...new Set(links.map((a) => (a.getAttribute("href") ?? "").split(/[/?]/)[1]))]);
    for (const screen of ["inventory", "findings", "loss", "evidence", "drift"]) expect(targets, screen).toContain(screen);
  });

  test("the verdict is built from the scan, in detection language", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const verdict = page.getByRole("region", { name: "Where you stand" });
    await expect(verdict.getByRole("paragraph")).toHaveText(/^Modeled loss in a bad year has risen from \$3\.4M to \$[\d.]+M in two months, driven by one push in September: meridian-support went live\.$/);
    await expect(verdict.getByRole("button")).toHaveText(["Export board report"]);
  });

  test("the four tiles answer their question with figures from the scan", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const main = page.locator("main .screen-content");
    // Agent Inventory: who the agents serve, what they can do, and the newest one.
    await expect(main.getByText("3 customer-facing, 2 internal")).toBeVisible();
    await expect(main.getByText("2 can move money · 7 tools · 4 model providers")).toBeVisible();
    await expect(main.getByText("discovered records")).toHaveCount(0);
    const inventory = main.getByRole("heading", { name: "Agent Inventory" }).locator("xpath=ancestor::section[1]");
    await expect(inventory).toContainText("Newest: meridian-support, added 15 Sep, moves money with no approval detected.");
    // Risk Mapping: every agent on a low-to-high line, the new support agent at the high end.
    const mapping = main.getByRole("heading", { name: "Risk Mapping" }).locator("xpath=ancestor::section[1]");
    await expect(mapping.getByRole("link")).toHaveText(["meridian-support", "account-actions", "meridian-escalation", "meridian-front", "meridian-knowledge", /View findings/]);
    expect(await mapping.getByRole("img").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")))).toEqual(["high", "high", "low", "low", "low"]);
    await expect(mapping).toContainText("LowMediumHigh");
    await expect(mapping).toContainText("meridian-supportnew");
    await expect(mapping).not.toContainText(/high-severity|idempotency|×/);
    await expect(mapping.getByRole("link", { name: "View findings" })).toHaveAttribute("href", "#/findings");
    // No Protection Level tile.
    await expect(main.getByText("Protection Level")).toHaveCount(0);
    // Estimated Failures Cost: the figure and a plot by month against the declared risk capacity, nothing else written.
    const cost = main.getByRole("heading", { name: "Estimated Failures Cost" }).locator("xpath=ancestor::section[1]");
    await expect(cost).toContainText(/\$[\d.]+Min a bad year/);
    await expect(cost.getByRole("img", { name: /^Modeled bad-year loss by month: \$3\.4M in Jul, \$3\.5M in Aug, \$[\d.]+M in Sep\. Risk capacity \$4M, exceeded$/ })).toBeVisible();
    await expect(cost.getByRole("img")).toContainText("Risk capacity $4M");
    await expect(cost).not.toContainText(/Cyber policy|Modeled\.|Up from|1 year in 100/);
    await expect(cost.getByRole("paragraph")).toHaveCount(0);
    await main.getByRole("link", { name: "View financial exposure" }).click();
    await expect(page).toHaveURL(/#\/loss/);
  });

  test("attention rows name the agents and say what was seen, why it matters and the fix, with no workflow controls", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const list = page.getByRole("region", { name: "Needs your attention" });
    await expect(list).toContainText("Highest severity first. The same problem on several agents is one item.");
    const rows = list.getByRole("listitem");
    await expect(rows).toHaveCount(3);
    await expect(list).not.toContainText(/idempotency|\[agents\.|DECL00|AI008|Mandate overreach|Control coverage gap/);
    await expect(rows.first()).toContainText("account-actions and meridian-support: declared autonomy does not match what the code does.");
    await expect(rows.first().getByRole("term")).toHaveText(["What the scan saw", "Why it matters", "Fix"]);
    await expect(rows.first()).toContainText("Declared: acts after human approval. In the code: acts on its own, with 4 tools that can move money and no approval step detected.");
    await expect(rows.first()).toContainText("The approval your policy relies on is not there.");
    await expect(rows.first()).toContainText("Add the approval step, or correct the declaration. · 1 marked for transfer · 1 being mitigated");
    await expect(rows.nth(1)).toContainText("issue_refund is retried on failure with no unique reference per request, in tools/account_tools.py, line 17. Both agents call it.");
    for (const row of await rows.all()) await expect(row.getByRole("term")).toHaveCount(3);
    await expect(list.getByRole("button")).toHaveCount(0);
    // No workflow UI. (A declared owner shown as a fact, from stoa-declared.toml, is allowed.)
    await expect(page.locator("main .screen-content").getByText(/assign owner|assign to|overdue|due by|due date/i)).toHaveCount(0);
    await expect(list.getByRole("link", { name: "View all 13 findings" })).toBeVisible();
    await rows.nth(1).getByRole("link").click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("what changed tells the push in three lines: who arrived, what came off, what it cost", async ({ page }) => {
    await page.goto(url("meridian-pay"));
    const changed = page.getByRole("region", { name: "What changed" });
    const lines = changed.getByRole("listitem");
    await expect(lines).toHaveCount(3);
    await expect(lines.nth(0)).toContainText("1 agent added: meridian-support.");
    await expect(lines.nth(0)).toContainText("meridian-support can move money.");
    await expect(lines.nth(1)).toContainText("account-actions lost its amount cap.");
    await expect(lines.nth(1)).toContainText("Every action was limited in code; now the only limit is the $500 written in the system prompt.");
    await expect(lines.nth(2)).toContainText(/Modeled loss in a bad year: \$3\.5M to \$[\d.]+M\./);
    await expect(lines.nth(2)).toContainText("1 new high-severity finding. 2 of 5 agents are elevated.");
    await expect(changed).not.toContainText(/reopened|because|follow from/i);
    await changed.getByRole("link", { name: "Open the change log" }).click();
    await expect(page).toHaveURL(/#\/drift/);
  });

  test("the footer cards summarize, and the sidebar carries one badge", async ({ page }) => {
    await page.goto(url("meridian-pay"));
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
    await expect(verdict).toContainText("2 agents can move money on their own, and no human approval was detected on either.");
    await expect(verdict).not.toContainText("Modeled");
    await expect(verdict).not.toContainText("changed since");
    await expect(page.getByText("Not estimated yet")).toBeVisible();
    await expect(page.locator("main").getByText("$", { exact: false })).toHaveCount(0);
    // No declaration file: nothing about who the agents serve, and no newest agent without a baseline.
    await expect(page.locator("main .screen-content").getByText(/customer-facing|Newest:/)).toHaveCount(0);
    await expect(page.locator("main .screen-content").getByText("No baseline to compare against")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Screens" })).toContainText("Agent Inventory5");
    await expect(page.getByRole("region", { name: "What changed" })).toContainText("stoa scan . --diff-against origin/main");
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
    await expect(diagram.getByRole("button")).toHaveCount(1 + 3 + 1 + 2 + 1 + 6 + 1);
    await expect(flow).toContainText("account-actions: 6 tools, 4 of them money-moving or high impact with no guardrail detected; 3 safeguards detected; 6 findings.");

    // No side panel: a selected box explains itself in one line under the diagram.
    await expect(flow.getByText("Risk intensity, by dimension")).toHaveCount(0);
    await diagram.getByRole("button", { name: /^Human approval, no human approval detected/ }).click();
    await expect(flow).toContainText("No human approval detected. 4 money-moving or high-impact tools can run without a person confirming.");
    await expect(flow).toContainText("Declared autonomy does not match what the code does.");
    await flow.getByRole("button", { name: "Clear" }).click();
    await expect(flow).toContainText("account-actions: 6 tools");

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
    await expect(flow.getByRole("group", { name: "Agents" }).getByRole("button")).toHaveCount(5);
    await page.goto(url("no-agents"));
    await expect(page.getByRole("heading", { name: "Agent Risk Flow Graph" })).toHaveCount(0);
  });
});

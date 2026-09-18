import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { pathToFileURL } from "node:url";
const [,, file, hash] = process.argv;
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
await page.goto(pathToFileURL(file).href + hash);
await page.waitForTimeout(300);
const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
for (const v of r.violations) {
  console.log(`${v.impact} ${v.id}: ${v.help}`);
  for (const n of v.nodes.slice(0, 12)) console.log("   ", n.target.join(" "), "|", (n.failureSummary || "").split("\n").slice(1, 2).join("").slice(0, 160));
}
await browser.close();

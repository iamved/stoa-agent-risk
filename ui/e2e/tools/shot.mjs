import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
const [,, file, hash, out, width, full] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(width), height: 900 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(file).href + hash);
await page.waitForTimeout(300);
await page.screenshot({ path: out, fullPage: full === "full" });
await browser.close();

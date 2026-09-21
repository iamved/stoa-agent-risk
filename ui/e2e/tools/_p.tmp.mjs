import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
const [dir, ...shots] = process.argv.slice(2);
const browser = await chromium.launch();
for (const shot of shots) {
  const [name, route, w = "1360"] = shot.split("|");
  const page = await browser.newPage({ viewport: { width: Number(w), height: 900 } });
  const errors = []; page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(pathToFileURL(`${dir}/${name}.html`).href + route);
  await page.waitForTimeout(600);
  const file = `${dir}/${name}-${route.replace(/[^a-z]/gi, "_")}-${w}.png`;
  await page.screenshot({ path: file, fullPage: true });
  console.log(file.split("/").pop(), "errors:", errors.length, errors[0] ?? "");
  await page.close();
}
await browser.close();

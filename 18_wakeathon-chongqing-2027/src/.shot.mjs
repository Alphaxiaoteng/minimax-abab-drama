// 一次性视觉验证：两阵营（three / css）各截三态（常态夜景 / 复合意图引爆 / 黎明）。
import { chromium } from "playwright";
import { createServer } from "vite";

const server = await createServer({ root: process.cwd(), server: { port: 5200 }, logLevel: "warn" });
await server.listen();
const url = server.resolvedUrls.local[0];

const browser = await chromium.launch({ headless: true, args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
const errs = [];
page.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errs.push("CONSOLE: " + m.text()); });

await page.goto(url, { waitUntil: "load" });
await page.waitForTimeout(2500);

const snap = async (name) => { await page.screenshot({ path: `.verify/shot-${name}.png` }); };

// 读取当前引擎实际样本能量，证明 WebGL 真的在跑（不是空白 canvas）
const sampleNow = () => page.evaluate(() => window.__wakeShow?.sample?.() ?? null);

// ---- three 阵营 ----
await page.evaluate(() => window.__wakeShow?.setEngine("three"));
await page.waitForTimeout(1200);
await snap("three-night");
console.log("three-night sample:", JSON.stringify(await sampleNow()));

await page.evaluate(() => {
  const b = (action, intensity) => window.__wakeShow.apply({ action, intensity });
  b("skyline", 1); b("laser", 1); b("drone", 1); b("fireworks", 1); b("shatter", 1);
});
await page.waitForTimeout(400);
await snap("three-hype");
console.log("three-hype sample:", JSON.stringify(await sampleNow()));

await page.evaluate(() => { const b = (a, i) => window.__wakeShow.apply({ action: a, intensity: i }); b("dawn", 1); b("fireworks", 1); b("confetti", 1); });
await page.waitForTimeout(1800);
await snap("three-dawn");
console.log("three-dawn sample:", JSON.stringify(await sampleNow()));

// ---- css 阵营 ----
await page.evaluate(() => window.__wakeShow?.setEngine("css"));
await page.waitForTimeout(1200);
await snap("css-night");
console.log("css-night sample:", JSON.stringify(await sampleNow()));

await page.evaluate(() => { const b = (a, i) => window.__wakeShow.apply({ action: a, intensity: i }); b("laser", 1); b("mascot", 1); b("drone", 1); b("fireworks", 1); });
await page.waitForTimeout(400);
await snap("css-hype");
console.log("css-hype sample:", JSON.stringify(await sampleNow()));

await page.evaluate(() => { const b = (a, i) => window.__wakeShow.apply({ action: a, intensity: i }); b("dawn", 1); b("confetti", 1); });
await page.waitForTimeout(1800);
await snap("css-dawn");
console.log("css-dawn sample:", JSON.stringify(await sampleNow()));

console.log("errors:", errs.length ? errs.slice(0, 10).join("\n") : "none");
await browser.close();
await server.close();
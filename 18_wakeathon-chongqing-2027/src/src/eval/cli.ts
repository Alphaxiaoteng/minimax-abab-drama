/**
 * 评测 CLI —— 在真实浏览器（Playwright）里跑 12 条用例，输出：
 *   .verify/eval-report.json   机器可读明细
 *   .verify/eval-report.html   可直接投屏/截图的可视化报告
 *   docs/REPORT.md             提交材料用的评测结论
 *
 * 用法（在 src/ 下）：npx tsx src/eval/cli.ts [--only id1,id2] [--dt 16.7] [--headed]
 *
 * 为什么用浏览器：two/css 两阵营都需要真实 WebGL / 真实 DOM 尺寸，
 * jsdom 下 canvas 与 WebGL 均为空壳，任何帧率与观感结论都不可信。
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const VERIFY_DIR = resolve(ROOT, ".verify");
const DOCS_DIR = resolve(ROOT, "../docs");

interface CliArgs {
  only?: string[];
  dt: number;
  headed: boolean;
}

function parseArgs(argv: readonly string[]): CliArgs {
  const args: CliArgs = { dt: 16.7, headed: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--only") args.only = (argv[++i] ?? "").split(",").filter(Boolean);
    else if (a === "--dt") args.dt = Number(argv[++i] ?? 16.7);
    else if (a === "--headed") args.headed = true;
  }
  return args;
}

export interface CliReport {
  generatedAt: string;
  dt: number;
  engines: Array<{ kind: string; available: boolean; note: string }>;
  outcomes: Array<{
    id: string;
    title: string;
    category: string;
    renderer: string;
    total: number;
    grade: string;
    coverage: number;
    coupling: number;
    determinism: number;
    robustness: number;
    frames: number;
    assertions: Array<{ note: string; action: string; pass: boolean; observed: number; required: number }>;
    caps: string[];
    verdict: string;
    peaks: Record<string, number>;
    rhythm: Array<{ cue: number; peak: number; mean: number }>;
  }>;
  summary: { mean: number; best: string; worst: string; passed: number; failed: number };
}

const main = async (): Promise<void> => {
  const args = parseArgs(process.argv.slice(2));
  mkdirSync(VERIFY_DIR, { recursive: true });
  mkdirSync(DOCS_DIR, { recursive: true });

  const server = await createServer({ root: ROOT, server: { port: 5199, strictPort: false }, logLevel: "warn" });
  await server.listen();
  const url = server.resolvedUrls?.local[0] ?? "http://localhost:5199/";

  const browser = await chromium.launch({
    headless: !args.headed,
    args: ["--use-angle=metal", "--enable-webgl", "--enable-unsafe-webgl"],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  await page.goto(`${url}?eval=1`, { waitUntil: "load" });
  await page.waitForFunction(() => Boolean((window as unknown as { __wakeEval?: unknown }).__wakeEval), null, {
    timeout: 15000,
  });

  const report = (await page.evaluate(
    async ({ dt, only }) => {
      const mod = (window as unknown as { __wakeEval: WakeEvalBridge }).__wakeEval;
      return mod.runAll({ dt, only });
    },
    { dt: args.dt, only: args.only ?? null },
  )) as CliReport;

  report.generatedAt = new Date().toISOString();

  writeFileSync(resolve(VERIFY_DIR, "eval-report.json"), JSON.stringify(report, null, 2), "utf8");
  writeFileSync(resolve(VERIFY_DIR, "eval-report.html"), renderHtml(report), "utf8");
  writeFileSync(resolve(DOCS_DIR, "REPORT.md"), renderMarkdown(report, consoleErrors), "utf8");

  await browser.close();
  await server.close();

  const line = report.outcomes
    .map((o) => `${o.renderer.padEnd(5)} ${o.grade} ${String(o.total).padStart(5)}  ${o.id}`)
    .join("\n");
  process.stdout.write(
    `\n=== 雾醒山城 · 原型评测（dt=${report.dt}ms）===\n${line}\n\n均值 ${report.summary.mean}｜通过 ${report.summary.passed}｜未通过 ${report.summary.failed}\n报告：.verify/eval-report.{json,html}  docs/REPORT.md\n控制台错误 ${consoleErrors.length} 条\n`,
  );
  process.exit(report.summary.failed > 0 ? 1 : 0);
};

/** 页面内注入的桥接对象（由 src/eval/bridge.ts 挂到 window.__wakeEval） */
interface WakeEvalBridge {
  runAll(options: { dt: number; only: string[] | null }): Promise<CliReport>;
}

const esc = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function bar(value: number): string {
  const pct = Math.round(value * 100);
  const hue = pct >= 85 ? "var(--ok)" : pct >= 65 ? "var(--warn)" : "var(--bad)";
  return `<div class="bar"><span style="width:${pct}%;background:${hue}"></span></div>`;
}

function renderHtml(report: CliReport): string {
  const rows = report.outcomes
    .map(
      (o) => `<tr>
      <td class="mono">${esc(o.renderer)}</td>
      <td>${esc(o.title)}<div class="sub">${esc(o.id)} · ${o.frames} 帧</div></td>
      <td class="grade g-${o.grade}">${o.grade}</td>
      <td class="num mono">${o.total}</td>
      <td>${bar(o.coverage)}<span class="sub">覆盖 ${(o.coverage * 100).toFixed(0)}%</span></td>
      <td>${bar(o.coupling)}<span class="sub">耦合 ${(o.coupling * 100).toFixed(0)}%</span></td>
      <td>${bar(o.determinism)}<span class="sub">确定 ${(o.determinism * 100).toFixed(0)}%</span></td>
      <td class="verdict">${esc(o.verdict)}${o.caps.map((c) => `<div class="cap">⚠ ${esc(c)}</div>`).join("")}</td>
    </tr>`,
    )
    .join("\n");

  const failures = report.outcomes
    .flatMap((o) => o.assertions.filter((a) => !a.pass).map((a) => ({ id: o.id, ...a })))
    .map(
      (a) =>
        `<li><b>${esc(a.id)}</b> · ${esc(a.action)} 期望 ≥ ${a.required.toFixed(2)}，实测 ${a.observed.toFixed(2)} —— ${esc(a.note)}</li>`,
    )
    .join("\n");

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" /><title>雾醒山城 · 原型评测报告</title>
<style>
  :root { --bg:#070b16; --panel:rgba(18,26,44,.72); --edge:rgba(120,180,255,.22); --ink:#eaf2ff;
          --ok:#4dd2ff; --warn:#ffb300; --bad:#ff2079; }
  * { box-sizing:border-box; }
  body { margin:0; padding:32px; background:var(--bg); color:var(--ink);
         font-family:"PingFang SC","Noto Sans SC",system-ui,sans-serif; }
  h1 { font-size:28px; letter-spacing:.14em; margin:0 0 4px;
       background:linear-gradient(100deg,#00e5ff,#9ad8ff 40%,#ff2079);
       -webkit-background-clip:text; background-clip:text; color:transparent; }
  .meta { color:rgba(234,242,255,.55); font-size:13px; margin-bottom:24px; }
  .kpis { display:flex; gap:14px; margin-bottom:24px; flex-wrap:wrap; }
  .kpi { background:var(--panel); border:1px solid var(--edge); border-radius:14px; padding:14px 20px; min-width:150px; }
  .kpi b { display:block; font-size:26px; color:var(--ok); font-variant-numeric:tabular-nums; }
  .kpi span { font-size:12px; color:rgba(234,242,255,.55); letter-spacing:.1em; }
  table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--edge); border-radius:14px; overflow:hidden; }
  th,td { text-align:left; padding:12px 14px; font-size:13px; border-bottom:1px solid rgba(120,180,255,.1); vertical-align:top; }
  th { font-size:11px; letter-spacing:.2em; color:rgba(234,242,255,.5); }
  .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .num { font-size:18px; font-weight:700; color:var(--ok); }
  .sub { display:block; font-size:11px; color:rgba(234,242,255,.45); margin-top:4px; }
  .grade { font-weight:800; font-size:20px; }
  .g-S { color:#69f0ae; } .g-A { color:#4dd2ff; } .g-B { color:#ffb300; } .g-C,.g-D { color:#ff2079; }
  .bar { width:120px; height:8px; border-radius:99px; background:rgba(255,255,255,.08); overflow:hidden; }
  .bar span { display:block; height:100%; border-radius:99px; }
  .cap { color:var(--warn); font-size:11px; margin-top:4px; }
  .verdict { max-width:420px; color:rgba(234,242,255,.8); }
  ul { padding-left:20px; line-height:1.9; }
  section { margin-top:28px; }
  h2 { font-size:16px; letter-spacing:.18em; color:rgba(234,242,255,.7); }
</style></head>
<body>
  <h1>雾醒山城 · 原型评测报告</h1>
  <div class="meta">生成于 ${esc(report.generatedAt)} · 步长 ${report.dt}ms · 阵营 ${report.engines
    .map((e) => `${e.kind}${e.available ? "" : "(不可用)"}`)
    .join(" / ")}</div>
  <div class="kpis">
    <div class="kpi"><b>${report.summary.mean}</b><span>加权均分</span></div>
    <div class="kpi"><b>${report.summary.passed}/${report.outcomes.length}</b><span>用例通过</span></div>
    <div class="kpi"><b>${esc(report.summary.best || "-")}</b><span>最佳用例</span></div>
    <div class="kpi"><b>${esc(report.summary.worst || "-")}</b><span>待改用例</span></div>
  </div>
  <table><thead><tr><th>阵营</th><th>用例</th><th>评级</th><th>总分</th><th>覆盖率</th><th>耦合度</th><th>确定度</th><th>结论</th></tr></thead>
  <tbody>${rows}</tbody></table>
  <section><h2>未通过断言</h2>${failures ? `<ul>${failures}</ul>` : "<p>无 —— 全部断言通过。</p>"}</section>
</body></html>`;
}

function renderMarkdown(report: CliReport, consoleErrors: readonly string[]): string {
  const table = report.outcomes
    .map(
      (o) =>
        `| ${o.renderer} | ${o.title} | ${o.grade} | ${o.total} | ${(o.coverage * 100).toFixed(0)}% | ${(o.coupling * 100).toFixed(0)}% | ${(o.determinism * 100).toFixed(0)}% | ${o.verdict} |`,
    )
    .join("\n");
  const failures = report.outcomes
    .flatMap((o) => o.assertions.filter((a) => !a.pass).map((a) => `- \`${o.id}\` · \`${a.action}\` 期望 ≥ ${a.required.toFixed(2)}，实测 ${a.observed.toFixed(2)} —— ${a.note}`))
    .join("\n");
  return `# 雾醒山城 · 自动化评测报告

> 生成于 ${report.generatedAt}｜帧步长 ${report.dt}ms｜用例 ${report.outcomes.length} 条｜加权均分 **${report.summary.mean}**

## 一、总览

| 阵营 | 用例 | 评级 | 总分 | 覆盖率 | 耦合度 | 确定度 | 结论 |
| --- | --- | :--: | --: | --: | --: | --: | --- |
${table}

## 二、五维评分定义

| 维度 | 权重 | 客观口径 |
| --- | --: | --- |
| 视觉覆盖率 | 0.25 | 用例预期动作真正亮起的比例（峰值覆盖加权 35%） |
| 编排耦合度 | 0.20 | 同一时刻多路效果共现的 Jaccard 均值，衡量「编排」而非「轮播」 |
| 节奏曲线 | 0.20 | 峰值位置（越靠后越好）+ 起伏度 + 首幕铺垫 |
| 确定度 | 0.15 | 同 dt 序列两次重放，逐帧读数最大差值取反 |
| 鲁棒性 | 0.20 | 异常/乱码/超长意图下无异常、无 NaN 的帧占比 |

封顶规则：引擎异常 → 59；重放不一致 → 74；覆盖率 < 0.5 → 69；任一断言未过 → 79。

## 三、未通过断言

${failures || "全部断言通过。"}

## 四、运行时错误

${consoleErrors.length === 0 ? "浏览器控制台无 error。" : consoleErrors.map((e) => `- \`${e}\``).join("\n")}

## 五、复现方式

\`\`\`bash
cd src
npm run eval          # 全量（two / css 两阵营）
npx tsx src/eval/cli.ts --only zero-peak --headed   # 单用例带界面
\`\`\`
`;
}

void main().catch((error: unknown) => {
  process.stderr.write(`评测失败：${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`);
  process.exit(1);
});

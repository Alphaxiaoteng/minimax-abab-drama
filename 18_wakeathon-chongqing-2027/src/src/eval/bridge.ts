/**
 * 浏览器内评测桥 —— 把评测引擎挂到 `window.__wakeEval`，供 Playwright 驱动的 CLI 调用。
 *
 * 只在 URL 带 `?eval=1` 时安装，正常演示不受影响。
 * 两个阵营的 driver 工厂在这里注入：这是全项目唯一知道
 * 「three 引擎与 css 引擎各自怎么创建」的地方。
 */
import type { EngineKind, HarnessDriver } from "../core/contract";
import { createThreeDriver } from "../visual/driver";
import { createCssDriver } from "../css/driver";
import { judgeReport, type JudgeResult } from "./judge";
import { runScenario, SCENARIOS, type AttemptResult, type DriverFactory } from "./harness";
import type { MetricReport } from "./metrics";

interface EngineStatus {
  kind: EngineKind;
  available: boolean;
  note: string;
}

interface Outcome {
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
  assertions: JudgeResult["assertions"];
  caps: string[];
  verdict: string;
  peaks: Record<string, number>;
  rhythm: Array<{ cue: number; peak: number; mean: number }>;
}

export interface RunSummary {
  generatedAt: string;
  dt: number;
  engines: EngineStatus[];
  outcomes: Outcome[];
  summary: { mean: number; best: string; worst: string; passed: number; failed: number };
}

const mountProbe = (): HTMLElement => {
  const existing = document.getElementById("eval-mount");
  if (existing) return existing;
  const node = document.createElement("div");
  node.id = "eval-mount";
  node.style.cssText = "position:absolute;left:-9999px;top:0;width:1280px;height:720px;";
  document.body.appendChild(node);
  return node;
};

export function installEvalBridge(): void {
  const mount = mountProbe();

  const factory: DriverFactory = (kind: EngineKind): HarnessDriver => {
    if (kind === "three") return createThreeDriver(mount);
    return createCssDriver(mount);
  };

  const runAll = async (options: { dt: number; only: string[] | null }): Promise<RunSummary> => {
    const engines: EngineStatus[] = [];
    const kinds: EngineKind[] = ["three", "css"];
    for (const kind of kinds) {
      try {
        const probe = kind === "three" ? createThreeDriver(mount) : createCssDriver(mount);
        probe.dispose();
        engines.push({ kind, available: true, note: "driver 创建成功" });
      } catch (error) {
        engines.push({
          kind,
          available: false,
          note: error instanceof Error ? error.message : String(error),
        });
      }
    }

    const selected = options.only ? SCENARIOS.filter((s) => options.only!.includes(s.id)) : SCENARIOS;
    const outcomes: Outcome[] = [];

    for (const kind of kinds) {
      if (!engines.find((e) => e.kind === kind)?.available) continue;
      for (const scenario of selected) {
        const { report } = await safeRun(scenario, factory, kind, options.dt);
        const judgement = judgeReport(report, scenario);
        outcomes.push({
          id: scenario.id,
          title: scenario.title,
          category: scenario.category,
          renderer: kind,
          total: judgement.total,
          grade: judgement.grade,
          coverage: report.coverage,
          coupling: report.coupling,
          determinism: report.determinism,
          robustness: report.robustness,
          frames: report.frames,
          assertions: judgement.assertions,
          caps: judgement.caps,
          verdict: judgement.verdict,
          peaks: report.peaks,
          rhythm: report.rhythm.map((r) => ({ cue: r.cue, peak: r.peak, mean: r.mean })),
        });
      }
    }

    const totals = outcomes.map((o) => o.total);
    const mean = totals.length === 0 ? 0 : Math.round((totals.reduce((s, v) => s + v, 0) / totals.length) * 10) / 10;
    const sorted = [...outcomes].sort((a, b) => b.total - a.total);
    return {
      generatedAt: new Date().toISOString(),
      dt: options.dt,
      engines,
      outcomes,
      summary: {
        mean,
        best: sorted[0]?.id ?? "",
        worst: sorted[sorted.length - 1]?.id ?? "",
        passed: outcomes.filter((o) => o.caps.length === 0).length,
        failed: outcomes.filter((o) => o.caps.length > 0).length,
      },
    };
  };

  (window as unknown as { __wakeEval: unknown }).__wakeEval = { runAll, scenarios: SCENARIOS };
}

async function safeRun(
  scenario: Parameters<typeof runScenario>[0],
  factory: DriverFactory,
  kind: EngineKind,
  dt: number,
): Promise<{ report: MetricReport; attempts: AttemptResult[] }> {
  try {
    return await runScenario(scenario, factory, kind, { dt, twoPass: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      report: {
        id: scenario.id,
        title: scenario.title,
        category: scenario.category,
        renderer: kind,
        series: {},
        coverage: 0,
        peakCoverage: 0,
        coupling: 0,
        determinism: 0,
        robustness: 0,
        rhythm: [],
        frames: 0,
        ok: false,
        error: message,
        delivered: [],
        peaks: {},
      },
      attempts: [],
    };
  }
}
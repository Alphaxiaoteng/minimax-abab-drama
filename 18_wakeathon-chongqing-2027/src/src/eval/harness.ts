/**
 * 评测引擎 —— 把「渲染阵营 + 用例 + 指标」串成一次可复现的跑分。
 *
 * 关键设计：渲染阵营通过 HarnessDriver 抽象注入（three / css 同签名），
 * 因此同一份用例可以在两个阵营各跑一遍并直接对比 —— 这是本项目的技评核心。
 */
import type { ActionName, EngineKind, HarnessDriver } from "../core/contract";
import { buildTimeline, type CueStep } from "../core/timeline";
import { createIntentPath } from "./intent-path";
import {
  ACTION_NAMES,
  couplingOf,
  coverageOf,
  peakCoverageOf,
  peakOf,
  seriesOf,
  type MetricReport,
  type SampleRow,
  type Scenario,
} from "./metrics";
import { resetSampler, type AssertionResult, type JudgeResult } from "./judge";
import scenariosJson from "./scenarios.json";

export const SCENARIOS: Scenario[] = (scenariosJson as { scenarios: Scenario[] }).scenarios;

/** driver 工厂：由调用方注入，避免评测层静态 import 具体阵营（浏览器/Node 双双可用） */
export type DriverFactory = (kind: EngineKind) => HarnessDriver;

export interface RunOptions {
  driverFactory: DriverFactory;
  dt?: number;
  only?: string[];
}

export interface ScenarioOutcome {
  scenario: Scenario;
  report: MetricReport;
  judgement: JudgeResult;
}

/** 固定步长重放：同 dt 序列必须产生同读数（确定度由此可测） */
async function framesFor(
  driver: HarnessDriver,
  steps: readonly CueStep[],
  durationMs: number,
  dt: number,
  speed: number,
  intents: readonly string[],
): Promise<{ rows: SampleRow[]; nanHits: number; delivered: ActionName[]; fired: number }> {
  const rows: SampleRow[] = [];
  const delivered: ActionName[] = [];
  const intentPath = createIntentPath();
  const intentGap = 900;
  let nanHits = 0;
  let fired = 0;
  const pending = [...steps];

  for (let i = 0; i < Math.ceil(durationMs / dt); i++) {
    const t = i * dt;
    const showT = t * speed;
    while (pending.length > 0 && pending[0].at <= showT) {
      const step = pending.shift()!;
      driver.renderer.apply(step.effect);
      delivered.push(step.effect.action);
      for (const accent of step.accents) {
        driver.renderer.apply(accent);
        delivered.push(accent.action);
      }
    }
    while (fired < intents.length && t >= 400 + fired * intentGap) {
      // 真实链路：自然语言 → parseIntent → SceneEffect，再交给同一渲染阵营
      const reply = await intentPath.send(intents[fired]);
      for (const effect of [...reply.commands, ...reply.sounds]) {
        driver.renderer.apply(effect);
        delivered.push(effect.action);
      }
      fired += 1;
    }
    driver.advance(dt / 1000);
    const raw = driver.sample();
    const values: Record<string, number> = {};
    for (const action of ACTION_NAMES) {
      const v = raw[action];
      if (typeof v !== "number" || !Number.isFinite(v)) {
        if (v !== undefined) nanHits += 1;
        values[action] = 0;
      } else {
        values[action] = Math.max(0, Math.min(1, v));
      }
    }
    rows.push({ t: Math.round(t), values });
  }
  return { rows, nanHits, delivered, fired };
}

function seriesFrom(rows: readonly SampleRow[]): Record<string, Array<[number, number]>> {
  const series: Record<string, Array<[number, number]>> = {};
  for (const action of ACTION_NAMES) series[action] = seriesOf(rows, action);
  return series;
}

export function determinismBetween(a: readonly SampleRow[], b: readonly SampleRow[]): number {
  const n = Math.min(a.length, b.length);
  if (n === 0) return 0;
  let worst = 0;
  for (let i = 0; i < n; i++) {
    for (const action of ACTION_NAMES) {
      worst = Math.max(worst, Math.abs(a[i].values[action] - b[i].values[action]));
    }
  }
  return Math.max(0, 1 - worst);
}

export function rhythmFor(rows: readonly SampleRow[], steps: readonly CueStep[]): MetricReport["rhythm"] {
  return steps.map((step, cue) => {
    const next = steps[cue + 1];
    const to = next ? next.at : step.at + 2400;
    let peak = 0;
    let sum = 0;
    let n = 0;
    for (const row of rows) {
      if (row.t < step.at || row.t > to) continue;
      let local = 0;
      for (const action of ACTION_NAMES) local = Math.max(local, row.values[action]);
      peak = Math.max(peak, local);
      sum += local;
      n += 1;
    }
    return { cue, planIndex: step.planIndex, peak, mean: n === 0 ? 0 : sum / n, holdMs: to - step.at };
  });
}

export interface AttemptResult {
  rows: SampleRow[];
  nanHits: number;
  delivered: ActionName[];
  error?: string;
}

/** 跑一遍用例（不判分）：twoPass = true 时用第二个 driver 再跑一遍测确定度 */
export async function runScenario(
  scenario: Scenario,
  factory: DriverFactory,
  kind: EngineKind,
  options: { dt?: number; twoPass?: boolean } = {},
): Promise<{ report: MetricReport; attempts: AttemptResult[] }> {
  const dt = options.dt ?? 16.7;
  const speed = scenario.speed ?? 1;
  const steps = buildTimeline(
    undefined,
    scenario.plan !== undefined ? { only: scenario.plan } : {},
  );
  const intents = scenario.intents ?? [];
  const duration = scenario.durationMs ?? (steps.length === 0 ? 3000 : steps[steps.length - 1].at / speed + 2500);

  const attempts: AttemptResult[] = [];
  const passes = options.twoPass ? 2 : 1;

  for (let p = 0; p < passes; p++) {
    const driver = factory(kind);
    try {
      resetSampler(kind);
      const out = await framesFor(driver, steps, duration, dt, speed, intents);
      attempts.push(out);
    } catch (error) {
      attempts.push({
        rows: [],
        nanHits: 0,
        delivered: [],
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      try {
        driver.dispose();
      } catch {
        // 释放失败不影响评测结论
      }
    }
  }

  const primary = attempts[0];
  const rows = primary.rows;
  // 覆盖率只统计「必须出现」的动作：notAction 与地板值断言（minPeak/minMean ≤ 0）
  // 考的是「应保持暗/在场」，把它们计入分母会惩罚正确行为（如开场不许放烟花）。
  const expected = scenario.assertions
    .filter((a) => !a.notAction && a.action && ((a.minPeak ?? 0) > 0 || (a.minMean ?? 0) > 0))
    .map((a) => a.action!) as ActionName[];
  const peaks: Record<string, number> = {};
  for (const action of ACTION_NAMES) peaks[action] = peakOf(rows, action);

  const report: MetricReport = {
    id: scenario.id,
    title: scenario.title,
    category: scenario.category,
    renderer: kind,
    series: seriesFrom(rows),
    coverage: coverageOf(rows, expected),
    peakCoverage: peakCoverageOf(rows),
    coupling: couplingOf(rows),
    determinism: attempts[1] ? determinismBetween(primary.rows, attempts[1].rows) : 1,
    robustness:
      primary.error === undefined && primary.nanHits === 0 && rows.length > 0
        ? Math.max(0, 1 - primary.nanHits / Math.max(1, rows.length))
        : 0,
    rhythm: rhythmFor(rows, steps),
    frames: rows.length,
    ok: primary.error === undefined,
    error: primary.error,
    delivered: primary.delivered,
    peaks,
  };

  return { report, attempts };
}

export { rowsFromSeries } from "./judge";
export type { AssertionResult, JudgeResult };

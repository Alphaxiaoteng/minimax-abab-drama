/**
 * 评测报告输出（SLICE D / eval）。
 *
 * 契约：
 * 1. toJson 稳定键序 —— 手工构造有序对象，不依赖运行时遍历顺序。
 * 2. toMarkdown 中文表格，覆盖每一维度，并高亮不达标/失败项。
 * 3. writeReport 落盘到 outDir（默认 process.cwd()/artifacts/），目录缺失自动创建。
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { EvalReport, RubricDimension } from '../core/contracts.js';
import { RUBRIC_SPEC } from './rubric.js';

const THRESHOLD_BY_ID = new Map<string, number>(RUBRIC_SPEC.map((s) => [s.id, s.threshold]));

const pct = (v: number): string => `${(v * 100).toFixed(1)}%`;

/** 维度是否达标：优先用维度自带 threshold（若为 ScoredDimension），否则回落到 RUBRIC_SPEC。 */
function dimensionThreshold(dimension: RubricDimension): number | null {
  const withThreshold = dimension as { readonly threshold?: number };
  if (typeof withThreshold.threshold === 'number') return withThreshold.threshold;
  return THRESHOLD_BY_ID.get(dimension.id) ?? null;
}

/** 生成稳定键序的 JSON 字符串（缩进 2）。 */
export function toJson(report: EvalReport): string {
  const ordered = {
    suiteName: report.suiteName,
    startedAt: report.startedAt,
    durationMs: report.durationMs,
    overall: Number(report.overall.toFixed(6)),
    passed: report.passed,
    dimensions: report.dimensions.map((d) => ({
      id: d.id,
      name: d.name,
      weight: d.weight,
      score: Number(d.score.toFixed(6)),
      threshold: dimensionThreshold(d),
      detail: d.detail,
    })),
    cases: report.cases.map((c) => ({
      id: c.id,
      passed: c.passed,
      score: Number(c.score.toFixed(6)),
      expected: c.expected,
      actual: c.actual,
      ...(c.note !== undefined ? { note: c.note } : {}),
    })),
    degradations: [...report.degradations],
  };
  return JSON.stringify(ordered, null, 2);
}

const mdCell = (raw: string): string => raw.replace(/\|/g, '\\|').replace(/\n/g, ' ');

/** 生成中文 Markdown 报告。 */
export function toMarkdown(report: EvalReport): string {
  const lines: string[] = [];

  lines.push(`# 评测报告：${report.suiteName}`);
  lines.push('');
  lines.push(`- **总体得分**：${pct(report.overall)}`);
  lines.push(`- **结论**：${report.passed ? '✅ 通过' : '❌ 未通过'}`);
  lines.push(`- **开始时间戳**：${report.startedAt}`);
  lines.push(`- **耗时**：${report.durationMs} ms`);
  lines.push('');

  lines.push('## 维度得分');
  lines.push('');
  lines.push('| 维度 | 权重 | 得分 | 阈值 | 结论 |');
  lines.push('| --- | --- | --- | --- | --- |');
  for (const d of report.dimensions) {
    const threshold = dimensionThreshold(d);
    const passed = threshold === null ? d.score >= 0.75 : d.score >= threshold;
    const conclusion = passed ? '✅ 达标' : '❌ 不达标';
    const thresholdText = threshold === null ? '-' : pct(threshold);
    lines.push(
      `| ${mdCell(`${d.name}（${d.id}）`)} | ${pct(d.weight)} | ${pct(d.score)} | ${thresholdText} | ${conclusion} |`,
    );
  }
  lines.push('');

  lines.push('## 用例明细');
  lines.push('');
  lines.push('| 用例 | 结果 | 得分 | 期望 | 实际 | 备注 |');
  lines.push('| --- | --- | --- | --- | --- | --- |');
  for (const c of report.cases) {
    const result = c.passed ? '✅ 通过' : '❌ 失败';
    lines.push(
      `| ${mdCell(c.id)} | ${result} | ${pct(c.score)} | ${mdCell(c.expected)} | ${mdCell(c.actual)} | ${mdCell(c.note ?? '-')} |`,
    );
  }
  lines.push('');

  lines.push('## 降级记录');
  lines.push('');
  if (report.degradations.length === 0) {
    lines.push('（无降级发生）');
  } else {
    for (const deg of report.degradations) {
      lines.push(`- ⚠️ ${mdCell(deg)}`);
    }
  }
  lines.push('');

  return lines.join('\n');
}

export interface WrittenReport {
  readonly jsonPath: string;
  readonly mdPath: string;
}

/** 把报告写入 outDir（默认 process.cwd()/artifacts/），返回两个文件路径。 */
export async function writeReport(report: EvalReport, outDir?: string): Promise<WrittenReport> {
  const dir = outDir ?? resolve(process.cwd(), 'artifacts');
  await mkdir(dir, { recursive: true });
  const jsonPath = resolve(dir, 'eval-report.json');
  const mdPath = resolve(dir, 'eval-report.md');
  await writeFile(jsonPath, toJson(report), 'utf8');
  await writeFile(mdPath, toMarkdown(report), 'utf8');
  return { jsonPath, mdPath };
}
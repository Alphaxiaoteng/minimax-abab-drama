/**
 * 评测入口：跑完整评测套件，打印 Markdown 报告并落盘到 artifacts/。
 * 用法：npx tsx src/cli/evaluate.ts
 * 依赖 eval 切片导出的 runEvalSuite / toMarkdown / writeReport（经根 barrel）。
 */

import { runEvalSuite, toMarkdown, writeReport } from '../index.js';

async function main(): Promise<void> {
  console.log('开始评测（全程离线 mock，结果可复现）…');
  const report = await runEvalSuite();
  console.log(toMarkdown(report));
  const paths = await writeReport(report);
  const pct = (report.overall * 100).toFixed(1);
  console.log(`综合得分：${pct} · ${report.passed ? '达标' : '未达标'}`);
  console.log('报告已写入：');
  console.log(`  JSON: ${paths.jsonPath}`);
  console.log(`  Markdown: ${paths.mdPath}`);
}

main().catch((err) => {
  console.error(`评测失败：${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
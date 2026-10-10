/**
 * 评测入口 —— 在 `src/main.tsx` 顶部 `?eval=1` 时条件加载。
 * 单独成文件是为了让演示路径的依赖图不受评测代码影响（tree-shaking 友好）。
 */
export { installEvalBridge } from "./bridge";
export { SCENARIOS } from "./harness";
export { judge, judgeReport } from "./judge";
export { ACTION_NAMES, couplingOf, coverageOf, peakCoverageOf } from "./metrics";
export type { MetricReport, Scenario, SampleRow } from "./metrics";
export { buildTimeline, SHOW_PLANS } from "../core/timeline";

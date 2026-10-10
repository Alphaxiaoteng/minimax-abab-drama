/**
 * 时间轴 —— 12 幕大秀的单一事实来源。
 *
 * 设计：整场演出由「分镜脚本（剧本）」驱动，时间轴负责把剧本翻译成
 * 命令队列（t=0 起算的绝对时间），这样评测引擎可以用固定 dt 步进重放，
 * 判定与渲染相互独立、完全确定。
 */
import type { ActionName, SceneEffect, ScenePlan } from "./contract";
import { utteranceMs } from "./events";

/** 12 幕分镜脚本：雾醒山城 · 从入夜到 2027 第一缕光 */
export const SHOW_PLANS: readonly ScenePlan[] = [
  {
    id: "lamplight",
    title: "灯火初上",
    caption: "两江四岸点亮，洪崖洞先醒",
    effect: { action: "skyline", intensity: 0.85 },
    sounds: [{ action: "laser", intensity: 0.4 }],
    tone: "calm",
    line: "雾都入夜，先把两江四岸的灯点起来——这是重庆的待机画面。",
    note: "skyline 脉冲能量先起来，标定「常态夜景」基线",
  },
  {
    id: "riverfog",
    title: "平流雾起",
    caption: "嘉陵江雾气漫过解放碑与千厮门",
    effect: { action: "fog", intensity: 0.9 },
    sounds: [{ action: "laser", intensity: 0.3 }],
    tone: "poetic",
    line: "水汽从江面爬上来，把解放碑的碑尖泡成一支浮在雾里的光笔。",
    note: "fog 场能量验证：雾浓而不盖灯，保留霓虹可读性",
  },
  {
    id: "lightcliff",
    title: "洪崖流光",
    caption: "吊脚楼灯带顺坡而下，十一层一起闪",
    effect: { action: "laser", intensity: 1 },
    sounds: [{ action: "laser", intensity: 0.8 }],
    tone: "hype",
    line: "十一层坡坎灯带同时俯冲，洪崖洞今晚是悬在崖壁上的一挂瀑布。",
    note: "laser 激光扇面 + 灯带脉冲，检验几何一致性",
  },
  {
    id: "cruise",
    title: "两江游轮",
    caption: "朝天门航线，船灯划开黑色江面",
    effect: { action: "drone", intensity: 0.9 },
    sounds: [{ action: "laser", intensity: 0.45 }],
    tone: "calm",
    line: "游轮的探照灯切开江面，黑水被划出一道会合拢的伤口。",
    note: "drone 编队沿江心航线巡游，考相机跟随",
  },
  {
    id: "cableway",
    title: "长江索道",
    caption: "两台缆车在雾中擦肩而过",
    effect: { action: "spotlight", intensity: 0.9 },
    sounds: [{ action: "laser", intensity: 0.5 }],
    tone: "poetic",
    line: "索道轿厢擦肩的那一秒，雾里两盏灯互相点了个头。",
    note: "spotlight 追光横向掠过，光源沿索道轨道插值",
  },
  {
    id: "hotpot",
    title: "火锅烟火",
    caption: "九宫格翻涌，蒸汽与辣味一起上头",
    effect: { action: "mascot", intensity: 1 },
    sounds: [{ action: "shatter", intensity: 0.5 }],
    tone: "hype",
    line: "九宫格红汤翻涌，我把整条街的辣度调到「重庆」这一档。",
    note: "mascot 火锅图腾 + 蒸汽粒子，验证吉祥物图层",
  },
  {
    id: "dronewa",
    title: "无人机矩阵",
    caption: "千机阵列在夜空排字：WAKE",
    effect: { action: "drone", intensity: 1 },
    sounds: [{ action: "shatter", intensity: 0.7 }],
    tone: "hype",
    line: "千机矩阵收拢队形——今夜的第一句标语，写在解放碑正上方的天顶。",
    note: "drone 阵型切换（散射 → WAKE 字形），考姿态插值",
  },
  {
    id: "countdown",
    title: "十秒倒数",
    caption: "全场屏息：十、九、八……",
    effect: { action: "spotlight", intensity: 1 },
    sounds: [{ action: "laser", intensity: 1 }, { action: "laser", intensity: 1 }],
    tone: "warn",
    line: "屏息——十、九、八——把心跳交给倒计时，山城和我同时蓄力。",
    note: "spotlight 聚光收束 + 双激光节拍，紧张度读数拉满",
  },
  {
    id: "zero",
    title: "零点引爆",
    caption: "烟花、激光、汽笛、欢呼同时炸开",
    effect: { action: "fireworks", intensity: 1 },
    sounds: [
      { action: "fireworks", intensity: 1 },
      { action: "shatter", intensity: 1 },
      { action: "laser", intensity: 1 },
    ],
    tone: "hype",
    line: "零点——！2027 落在山城头顶，整条江面都被点亮了。",
    note: "峰值帧：fireworks + shatter + laser 三路并发，采样全场最大值",
  },
  {
    id: "wake",
    title: "WAKE UP",
    caption: "雾散，晨光爬上南山背脊",
    effect: { action: "dawn", intensity: 1 },
    sounds: [{ action: "mascot", intensity: 0.6 }],
    tone: "poetic",
    line: "雾开始退，南山背后那道光正在爬上背脊——WAKE UP，醒来的是整座城市。",
    note: "dawn 色温迁移，与零点形成冷暖对照",
  },
  {
    id: "morning",
    title: "两江晨光",
    caption: "江面泛白，轻轨载着新一年穿楼而过",
    effect: { action: "dawn", intensity: 0.55 },
    sounds: [{ action: "glitch", intensity: 0.4 }],
    tone: "calm",
    line: "轻轨穿楼而过，车窗里全是刚睡醒的脸——新一年的第一批乘客。",
    note: "daylight 白昼色温兜底，配 glitch 做列车数据质感",
  },
  {
    id: "fireworks_return",
    title: "雾醒山城 · 谢幕",
    caption: "最后一个字落回江里：2027，山城早安",
    effect: { action: "confetti", intensity: 0.7 },
    sounds: [
      { action: "fireworks", intensity: 0.9 },
      { action: "mascot", intensity: 0.5 },
    ],
    tone: "hype",
    line: "WAKE UP WITH AI——2027，重庆睡醒的那一刻，就是全场爆发的那一刻。",
    note: "谢幕帧：confetti + 收尾烟花，留给镜头最后一秒",
  },
];

export interface CueStep {
  /** 相对大秀开始的绝对时间（ms） */
  at: number;
  planIndex: number;
  effect: SceneEffect;
  /** 音效 / 副效果，与主 effect 同时下发 */
  accents: SceneEffect[];
  line: string;
  tone: ScenePlan["tone"];
}

export interface TimelineBuildOptions {
  /** 只放某一幕（分镜跳转） */
  only?: number;
  /** 单幕停留时长，默认按台词长度估算 */
  holdMs?: (plan: ScenePlan, index: number) => number;
}

/** 构建命令队列：t=0 起算，台词播完即切换下一幕 */
export function buildTimeline(
  plans: readonly ScenePlan[] = SHOW_PLANS,
  options: TimelineBuildOptions = {},
): CueStep[] {
  const hold = options.holdMs ?? ((plan: ScenePlan) => utteranceMs(plan.line) + 700);
  const steps: CueStep[] = [];
  let t = 0;
  plans.forEach((plan, index) => {
    if (options.only !== undefined && options.only !== index) return;
    steps.push({
      at: t,
      planIndex: index,
      effect: plan.effect,
      accents: plan.sounds,
      line: plan.line,
      tone: plan.tone,
    });
    t += hold(plan, index);
  });
  return steps;
}

export function showDuration(steps: readonly CueStep[]): number {
  if (steps.length === 0) return 0;
  const last = steps[steps.length - 1];
  return last.at + utteranceMs(last.line) + 700;
}

/** 触发过哪些动作（评测用：覆盖率测点；Set 用于动态去重，非静态查表） */
export function actionsIn(steps: readonly CueStep[], from = 0): Set<ActionName> {
  const seen = new Set<ActionName>();
  for (const step of steps) {
    if (step.at < from) continue;
    seen.add(step.effect.action);
    step.accents.forEach((a) => seen.add(a.action));
  }
  return seen;
}

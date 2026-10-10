// 意图解析：纯函数、无副作用、可反复评测。不读 Date/Math.random。
import type { ActionName, AgentTone, SceneEffect } from "../core/contract";

/** 一条原始文本解析出的结构化意图 */
export interface ParsedIntent {
  commands: SceneEffect[]; // 视觉命令，按 INTENT_ACTIONS 稳定顺序
  sounds: SceneEffect[]; // 音效/副能量，与命令一一对应
  text: string; // 台词（复合意图为串联句）
  tone: AgentTone;
  matched: ActionName[]; // 命中的动作（覆盖率统计用）
  intensity: number; // 全局强度词结果
}

// 稳定动作顺序：复合意图输出顺序由此决定，保证可复现
export const INTENT_ACTIONS: ActionName[] = [
  "fog",
  "skyline",
  "dawn",
  "fireworks",
  "laser",
  "drone",
  "mascot",
  "spotlight",
  "confetti",
  "glitch",
  "shatter",
];

// 中英关键词，英文一律小写（raw 匹配前会 toLowerCase，中文不受影响）
const ALIASES: Record<ActionName, string[]> = {
  fog: ["雾", "江雾", "浓雾", "雾气", "雾都", "fog", "mist", "haze"],
  skyline: ["天际线", "楼", "洪崖洞", "解放碑", "霓虹", "山城", "skyline", "building", "city"],
  dawn: ["黎明", "日出", "天亮", "清晨", "醒来", "唤醒", "dawn", "sunrise", "wake"],
  fireworks: ["烟花", "焰火", "礼花", "爆竹", "firework", "fireworks"],
  laser: ["激光", "光束", "光瀑", "laser", "beam"],
  drone: ["无人机", "千机", "编队", "drone", "drones", "uav"],
  mascot: ["火锅", "蒸汽", "沸腾", "九宫格", "辣", "hotpot", "steam"],
  spotlight: ["追光", "聚光", "聚光灯", "spotlight"],
  confetti: ["彩纸", "纸屑", "撒花", "confetti"],
  glitch: ["故障", "撕裂", "雪花屏", "噪点", "glitch"],
  shatter: ["爆破", "震撼", "爆炸", "碎裂", "音浪", "shatter", "boom"],
};

// 台词库：每个动作 ≥2 条，重庆方言腔调 + 赛博感；tone 与情绪一致
const LINES: Record<ActionName, { text: string; tone: AgentTone }[]> = {
  fog: [
    { text: "两江的水汽被我揉成灯影，今晚的雾是山城给跨年留的白。", tone: "poetic" },
    { text: "雾浓一点没关系，霓虹穿得过来——这才是重庆的待机画面。", tone: "calm" },
  ],
  skyline: [
    { text: "十七层坡坎上的楼群一起应声，每次霓虹脉冲都是重庆的心跳。", tone: "hype" },
    { text: "洪崖洞亮到解放碑，天际线是我手里那串会发光的糖。", tone: "poetic" },
  ],
  dawn: [
    { text: "2027 第一缕光从南山背爬上来，整座城正在被我轻轻叫醒。", tone: "calm" },
    { text: "雾开始退，晨光落在江面——醒来的是山城，也是我。", tone: "poetic" },
  ],
  fireworks: [
    { text: "收到！洪崖顶的焰色全调高两档，护好你的视网膜。", tone: "hype" },
    { text: "零点交给天上——每朵烟花都是一句没说完的晚安变早安。", tone: "hype" },
  ],
  laser: [
    { text: "激光扇面顺崖壁俯冲，洪崖洞今晚是一挂会呼吸的光瀑。", tone: "hype" },
    { text: "光束切开雾，笔直到能听见风声——这是山城的几何课。", tone: "calm" },
  ],
  drone: [
    { text: "千机收拢队形，第一句标语写在解放碑正上方的天顶。", tone: "hype" },
    { text: "无人机沿江心列队，像一串会飞的标点。", tone: "poetic" },
  ],
  mascot: [
    { text: "九宫格红汤翻涌，我把整条街的辣度调到「重庆」这一档。", tone: "hype" },
    { text: "蒸汽顶开锅盖，这是山城市的开机特效——烫，但醒脑。", tone: "hype" },
  ],
  spotlight: [
    { text: "追光掠过索道，轿厢擦肩那一秒，雾里两盏灯互相点了个头。", tone: "poetic" },
    { text: "聚光收束到钟楼，全场屏息——心跳交给这一束。", tone: "warn" },
  ],
  confetti: [
    { text: "彩纸落下如雨，2027 的第一场雪是山城给你放的。", tone: "hype" },
    { text: "把欢呼撕成碎片抛上天——这才叫谢幕。", tone: "hype" },
  ],
  glitch: [
    { text: "信号被雾咬了一口，霓虹闪成雪花屏——故障也是这座城的美学。", tone: "warn" },
    { text: "撕裂一点没关系，山城的夜本来就带噪点。", tone: "hype" },
  ],
  shatter: [
    { text: "爆破！音浪撞在江面，涟漪替我们把响度传下去。", tone: "hype" },
    { text: "震撼值拉满，玻璃幕墙集体共振——别慌，这是跨年的鼓点。", tone: "warn" },
  ],
};

// 音效副能量：动作 → 用于 sounds 的动作与系数
const SOUND_ACCENT: Record<ActionName, { action: ActionName; factor: number }> = {
  fog: { action: "laser", factor: 0.5 },
  skyline: { action: "laser", factor: 0.5 },
  dawn: { action: "mascot", factor: 0.6 },
  fireworks: { action: "shatter", factor: 0.8 },
  laser: { action: "laser", factor: 0.4 },
  drone: { action: "laser", factor: 0.5 },
  mascot: { action: "shatter", factor: 0.5 },
  spotlight: { action: "laser", factor: 0.6 },
  confetti: { action: "fireworks", factor: 0.7 },
  glitch: { action: "shatter", factor: 0.5 },
  shatter: { action: "fireworks", factor: 0.8 },
};

const GENERIC_LINE = { text: "这句话我记下了——跨年夜它会准时爬上霓虹。", tone: "calm" as AgentTone };
const TONE_RANK: Record<AgentTone, number> = { calm: 0, poetic: 1, warn: 2, hype: 3 };

// 确定性字符散列（无随机），用于在台词库中轮换，避免重复堆砌
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h + s.charCodeAt(i)) >>> 0;
  return h;
}

// 强度词：极端优先，其次软化，再次加强，最后默认
function pickIntensity(lowered: string): number {
  const max = ["全部", "拉满", "到极致", "最高", "最大", "满档", "full", "max", "maximum"];
  const soft = ["一点", "一点点", "稍微", "略有", "淡", "轻", "some", "slight", "slightly"];
  const strong = ["很", "非常", "再", "更", "超", "加大", "加强", "拉高", "来点"];
  if (max.some((w) => lowered.includes(w))) return 1;
  if (soft.some((w) => lowered.includes(w))) return 0.4;
  if (strong.some((w) => lowered.includes(w))) return 0.75;
  return 0.6;
}

// 判别式联合需逐分支构造，故用穷举 switch（无 default 亦覆盖全 union）
export function makeEffect(action: ActionName, intensity: number): SceneEffect {
  const v = Math.max(0, Math.min(1, intensity));
  switch (action) {
    case "fog":
      return { action: "fog", intensity: v };
    case "skyline":
      return { action: "skyline", intensity: v };
    case "dawn":
      return { action: "dawn", intensity: v };
    case "fireworks":
      return { action: "fireworks", intensity: v };
    case "laser":
      return { action: "laser", intensity: v };
    case "drone":
      return { action: "drone", intensity: v };
    case "mascot":
      return { action: "mascot", intensity: v };
    case "spotlight":
      return { action: "spotlight", intensity: v };
    case "confetti":
      return { action: "confetti", intensity: v };
    case "glitch":
      return { action: "glitch", intensity: v };
    case "shatter":
      return { action: "shatter", intensity: v };
  }
}

function dominantTone(tones: AgentTone[]): AgentTone {
  let best = tones[0];
  for (const t of tones) if (TONE_RANK[t] > TONE_RANK[best]) best = t;
  return best;
}

export function parseIntent(raw: string): ParsedIntent {
  const lowered = raw.toLowerCase();
  const matched = INTENT_ACTIONS.filter((a) => ALIASES[a].some((al) => lowered.includes(al)));
  const intensity = pickIntensity(lowered);

  // 未命中：2 条通用命令 skyline + fog
  if (matched.length === 0) {
    const fogV = Math.max(0, Math.min(1, intensity * 0.8));
    return {
      commands: [makeEffect("skyline", intensity), makeEffect("fog", fogV)],
      sounds: [
        makeEffect(SOUND_ACCENT.skyline.action, intensity * SOUND_ACCENT.skyline.factor),
        makeEffect(SOUND_ACCENT.fog.action, intensity * SOUND_ACCENT.fog.factor),
      ],
      text: GENERIC_LINE.text,
      tone: GENERIC_LINE.tone,
      matched: [],
      intensity,
    };
  }

  const commands = matched.map((a) => makeEffect(a, intensity));
  const sounds = matched.map((a) => {
    const acc = SOUND_ACCENT[a];
    return makeEffect(acc.action, intensity * acc.factor);
  });

  // 复合意图：串联句，各动作按散列在库中确定性取一条
  const picked = matched.map((a) => LINES[a][hash(lowered + a) % LINES[a].length]);
  return {
    commands,
    sounds,
    text: picked.map((p) => p.text).join(" "),
    tone: dominantTone(picked.map((p) => p.tone)),
    matched,
    intensity,
  };
}
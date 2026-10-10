/**
 * A/B 盲评（SLICE D / eval）。
 *
 * 契约：
 * 1. 裁判完全确定性、无外部模型——仅用语言学启发式（口头禅密度、情绪标记、句长合规、无禁忌词）。
 * 2. 同分按 id 字典序裁决，保证可复现。
 * 3. 并列不判负：胜率汇总中，平局不折损任一方胜率，单列 tie 计数。
 */

/** 候选文本，id 必须全局唯一。 */
export interface AbCandidate {
  readonly id: string;
  readonly text: string;
}

/** 一对盲评候选。 */
export interface AbPair {
  readonly pairId: string;
  readonly leftId: string;
  readonly rightId: string;
  readonly leftText: string;
  readonly rightText: string;
}

/** 单对裁决结果。 */
export interface AbVerdict {
  readonly leftId: string;
  readonly rightId: string;
  readonly winnerId: string; // 平局时为字典序较小的 id
  readonly margin: number; // 得分差绝对值
  readonly rationale: string; // 中文解释
  readonly leftScore: number;
  readonly rightScore: number;
  readonly tied: boolean;
}

/** 胜率排名汇总。 */
export interface AbStanding {
  readonly id: string;
  readonly wins: number;
  readonly ties: number;
  readonly losses: number;
  readonly winRate: number;
}

export interface AbReport {
  readonly standings: readonly AbStanding[];
  readonly verdicts: readonly AbVerdict[];
  readonly bestId: string | null;
}

const clamp01 = (v: number): number => Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0));

function codepointLength(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** 情绪标记密度：命中常见情绪词的比例。 */
const EMOTION_MARKERS = ['开心', '难过', '愤怒', '紧张', '害怕', '怀疑', '温柔', '平静', '激动', '担心'];
function emotionDensity(text: string): number {
  const present = EMOTION_MARKERS.filter((m) => text.includes(m)).length;
  return clamp01(present / 3);
}

/** 口头禅密度：给定口头禅在文本中的覆盖率。 */
function catchphraseDensity(text: string, catchphrases: readonly string[]): number {
  if (catchphrases.length === 0) return 0;
  const present = catchphrases.filter((cp) => cp.length > 0 && text.includes(cp)).length;
  return clamp01(present / Math.min(catchphrases.length, 3));
}

/** 句长合规：长度落在 [min,max] 记 1，否则按超出幅度衰减。 */
function lengthCompliance(text: string, min: number, max: number): number {
  const len = codepointLength(text);
  if (len === 0) return 0;
  if (len >= min && len <= max) return 1;
  const distance = len < min ? min - len : len - max;
  return clamp01(1 - distance / max);
}

/**
 * 默认语言学启发式配置。真实评测可通过参数注入 persona 相关阈值，
 * 但为保持盲评「不看来源、只看文本」，此处使用固定经验参数。
 */
export interface HeuristicProfile {
  readonly catchphrases: readonly string[];
  readonly tabooWords: readonly string[];
  readonly minLen: number;
  readonly maxLen: number;
}

export const DEFAULT_AB_PROFILE: HeuristicProfile = {
  catchphrases: ['有意思', '让我们', '真相', '线索'],
  tabooWords: ['脏话', '去死'],
  minLen: 10,
  maxLen: 60,
};

/** 给单条文本打 0–1 分（越高越好），并返回命中禁忌词与否。 */
export function scoreText(text: string, profile: HeuristicProfile = DEFAULT_AB_PROFILE): number {
  const hasTaboo = profile.tabooWords.some((w) => w.length > 0 && text.includes(w));
  if (hasTaboo) return 0; // 禁忌词一票否决
  const catchScore = catchphraseDensity(text, profile.catchphrases);
  const emoScore = emotionDensity(text);
  const lenScore = lengthCompliance(text, profile.minLen, profile.maxLen);
  return clamp01(0.4 * catchScore + 0.3 * emoScore + 0.3 * lenScore);
}

/** 仅配对不同 id 的候选，按 id 排序后两两组合，去重且顺序稳定。 */
export function buildPairs(candidates: readonly AbCandidate[]): readonly AbPair[] {
  const uniq = [...candidates].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const seen = new Set(uniq.map((c) => c.id));
  if (seen.size !== uniq.length) {
    throw new Error('A/B 候选存在重复 id');
  }
  const pairs: AbPair[] = [];
  for (let i = 0; i < uniq.length; i += 1) {
    for (let j = i + 1; j < uniq.length; j += 1) {
      const left = uniq[i]!;
      const right = uniq[j]!;
      pairs.push({
        pairId: `${left.id}__${right.id}`,
        leftId: left.id,
        rightId: right.id,
        leftText: left.text,
        rightText: right.text,
      });
    }
  }
  return pairs;
}

/** 裁决一对，确定性：同分按 id 字典序取较小者获胜，tied=true。 */
export function judgePair(pair: AbPair, profile: HeuristicProfile = DEFAULT_AB_PROFILE): AbVerdict {
  const leftScore = scoreText(pair.leftText, profile);
  const rightScore = scoreText(pair.rightText, profile);
  const margin = Math.abs(leftScore - rightScore);
  const tied = margin < 1e-9;
  const winnerId = tied
    ? pair.leftId < pair.rightId
      ? pair.leftId
      : pair.rightId
    : leftScore > rightScore
      ? pair.leftId
      : pair.rightId;
  const rationale = tied
    ? `两侧得分同为 ${leftScore.toFixed(3)}，按 id 字典序裁决：${winnerId} 胜出`
    : `${winnerId} 得分更高（${Math.max(leftScore, rightScore).toFixed(3)} vs ${Math.min(leftScore, rightScore).toFixed(3)}），差值 ${margin.toFixed(3)}`;
  return { leftId: pair.leftId, rightId: pair.rightId, winnerId, margin, rationale, leftScore, rightScore, tied };
}

/**
 * 跑全套 A/B，汇总胜率排名。
 * 并列不判负规则：tied 时双方各记一次 tie，不计入 loss；
 * winRate = wins / (wins + losses)，无胜负场次时记 0 分母安全。
 */
export function runAbJudge(
  candidates: readonly AbCandidate[],
  profile: HeuristicProfile = DEFAULT_AB_PROFILE,
): AbReport {
  const pairs = buildPairs(candidates);
  const verdicts = pairs.map((p) => judgePair(p, profile));

  const tally = new Map<string, { wins: number; ties: number; losses: number }>();
  for (const c of candidates) tally.set(c.id, { wins: 0, ties: 0, losses: 0 });

  for (const v of verdicts) {
    const left = tally.get(v.leftId)!;
    const right = tally.get(v.rightId)!;
    if (v.tied) {
      left.ties += 1;
      right.ties += 1;
    } else if (v.winnerId === v.leftId) {
      left.wins += 1;
      right.losses += 1;
    } else {
      right.wins += 1;
      left.losses += 1;
    }
  }

  const standings: AbStanding[] = [...tally.entries()].map(([id, t]) => {
    const decisive = t.wins + t.losses;
    return { id, wins: t.wins, ties: t.ties, losses: t.losses, winRate: decisive > 0 ? t.wins / decisive : 0 };
  });

  // 稳定排序：胜率高优先，其次 tie 多，最后 id 字典序
  standings.sort((a, b) => {
    if (b.winRate !== a.winRate) return b.winRate - a.winRate;
    if (b.ties !== a.ties) return b.ties - a.ties;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  const bestId = standings.length > 0 ? standings[0]!.id : null;
  return { standings, verdicts, bestId };
}
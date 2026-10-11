/**
 * contradiction.ts - 证人证言逻辑矛盾求解器、五大多结局判定树与音色克隆状态机。
 *
 * 为 MiniMax abab 剧本杀推理互动剧提供：
 * 1. 确定性时空与物证矛盾检测求解器 (ContradictionSolver)。
 * 2. 商业级 5 大支线结局归宿判定引擎 (EndingEvaluator)。
 * 3. MiniMax 角色语音克隆与音色情感流转状态机 (VoiceCloneStateMachine)。
 */

export interface TestimonyFact {
  id: string;
  speaker: string;
  timeMinute: number; // 当晚分钟数，例如 1260 代表 21:00
  location: string;
  claimedAction: string;
  involvesObject?: string;
  statement: string;
}

export interface ContradictionResult {
  hasContradiction: boolean;
  type: 'SPATIOTEMPORAL_CONFLICT' | 'OBJECT_COLLISION' | 'NONE';
  description?: string;
  conflictingFactIds: string[];
  challengePrompt: string;
}

export class ContradictionSolver {
  /**
   * 检测证词列表中的逻辑冲突与伪证破绽
   */
  static analyze(facts: TestimonyFact[]): ContradictionResult[] {
    const results: ContradictionResult[] = [];

    // 1. 同一人时空分身矛盾（在相同或极近时间出现在不同地点）
    for (let i = 0; i < facts.length; i++) {
      for (let j = i + 1; j < facts.length; j++) {
        const a = facts[i];
        const b = facts[j];

        if (a.speaker === b.speaker && Math.abs(a.timeMinute - b.timeMinute) <= 5 && a.location !== b.location) {
          results.push({
            hasContradiction: true,
            type: 'SPATIOTEMPORAL_CONFLICT',
            description: `${a.speaker} 在短时间内不可能同时出现在 [${a.location}] 与 [${b.location}]`,
            conflictingFactIds: [a.id, b.id],
            challengePrompt: `你在 ${a.timeMinute} 分自称在 ${a.location}，但又声称在 ${b.location}，你在隐瞒什么？`
          });
        }

        // 2. 关键物证排他性占有冲突（两人在同一时刻均声称独占某物证）
        if (
          a.involvesObject &&
          b.involvesObject &&
          a.involvesObject === b.involvesObject &&
          a.speaker !== b.speaker &&
          Math.abs(a.timeMinute - b.timeMinute) <= 15
        ) {
          results.push({
            hasContradiction: true,
            type: 'OBJECT_COLLISION',
            description: `${a.speaker} 与 ${b.speaker} 在同一时间段均声称持有物证 [${a.involvesObject}]`,
            conflictingFactIds: [a.id, b.id],
            challengePrompt: `关于关键物证 ${a.involvesObject}，你和 ${b.speaker} 的供述完全矛盾！`
          });
        }
      }
    }

    return results;
  }
}

export enum StoryEndingType {
  TRUE_CULPRIT_CONVICTED = 'TRUE_CULPRIT_CONVICTED', // 真凶伏法：完美证据链
  WRONGFUL_ACCUSATION = 'WRONGFUL_ACCUSATION',       // 误捕替罪羊：错认凶手
  COLD_CASE_ESCAPED = 'COLD_CASE_ESCAPED',           // 悬案潜逃：回合耗尽打草惊蛇
  DARK_CONSPIRACY_UNVEILED = 'DARK_CONSPIRACY_UNVEILED', // 黑暗阴谋反转：揭开双重谋杀
  MUTUAL_DESTRUCTION = 'MUTUAL_DESTRUCTION'          // 玉石俱焚：侦探遭灭口暗算
}

export interface CaseDeductionContext {
  accusedSuspectId: string;
  actualCulpritId: string;
  unlockedCluesCount: number;
  totalCluesCount: number;
  solvedContradictionsCount: number;
  detectiveDangerScore: number; // 0 - 100
  turnsUsed: number;
  maxTurns: number;
}

export interface EndingVerdict {
  ending: StoryEndingType;
  title: string;
  summary: string;
  score: number; // 0 - 100 综合侦探段位分
}

export class EndingEvaluator {
  static evaluate(ctx: CaseDeductionContext): EndingVerdict {
    const isCorrectSuspect = ctx.accusedSuspectId === ctx.actualCulpritId;
    const clueCoverage = ctx.totalCluesCount > 0 ? ctx.unlockedCluesCount / ctx.totalCluesCount : 0;

    // 1. 危险值过高且打草惊蛇 -> 玉石俱焚
    if (ctx.detectiveDangerScore >= 85) {
      return {
        ending: StoryEndingType.MUTUAL_DESTRUCTION,
        title: '【终局·玉石俱焚】暗室反噬',
        summary: '你的步步紧逼激怒了绝望的凶徒，在搜证现场遭遇暗算伏击，真相随风而逝。',
        score: 45
      };
    }

    // 2. 超出最大回合仍未确证 -> 悬案潜逃
    if (ctx.turnsUsed >= ctx.maxTurns && (!isCorrectSuspect || clueCoverage < 0.5)) {
      return {
        ending: StoryEndingType.COLD_CASE_ESCAPED,
        title: '【终局·凶手潜逃】迷雾漫漫',
        summary: '调查时间耗尽，狡猾的真凶已订好离境航班，只留下一宗未破悬案。',
        score: 55
      };
    }

    // 3. 指认错误 -> 冤假错案
    if (!isCorrectSuspect) {
      return {
        ending: StoryEndingType.WRONGFUL_ACCUSATION,
        title: '【终局·误捕替罪】移花接木',
        summary: '你锁定了被伪造证据陷害的替罪羊，真凶在庭审席冷眼旁观，逍遥法外。',
        score: 60
      };
    }

    // 4. 指认正确且揭开所有矛盾与深层线索 (>= 90%) -> 黑暗阴谋反转
    if (clueCoverage >= 0.85 && ctx.solvedContradictionsCount >= 2) {
      return {
        ending: StoryEndingType.DARK_CONSPIRACY_UNVEILED,
        title: '【神级结局·幕后黑手】黑金落幕',
        summary: '你不仅攻破真凶的所有伪证，更顺藤摸瓜端出了潜藏在豪门背后的洗钱阴谋！',
        score: 100
      };
    }

    // 5. 指认正确普通结案 -> 真凶伏法
    return {
      ending: StoryEndingType.TRUE_CULPRIT_CONVICTED,
      title: '【正义结局·真凶伏法】铁证如山',
      summary: '在无可辩驳的证据链前，真凶低头认罪，正义得到伸张。',
      score: 85
    };
  }
}

export type VoiceStatus = 'IDLE' | 'CLONING' | 'READY' | 'SYNTHESIZING' | 'ERROR';

export class VoiceCloneStateMachine {
  private status: VoiceStatus = 'IDLE';
  private voiceId: string | null = null;
  private emotion: string = 'neutral';

  getStatus(): VoiceStatus {
    return this.status;
  }

  getVoiceId(): string | null {
    return this.voiceId;
  }

  setEmotion(e: 'neutral' | 'fear' | 'arrogant' | 'panic'): void {
    this.emotion = e;
  }

  getEmotion(): string {
    return this.emotion;
  }

  startClone(sampleUri: string): void {
    if (!sampleUri) throw new Error('sampleUri 不能为空');
    this.status = 'CLONING';
  }

  completeClone(assignedVoiceId: string): void {
    if (!assignedVoiceId) throw new Error('assignedVoiceId 不能为空');
    this.voiceId = assignedVoiceId;
    this.status = 'READY';
  }

  startSynthesize(): void {
    if (this.status !== 'READY') throw new Error(`状态为 ${this.status}，无法合成语音`);
    this.status = 'SYNTHESIZING';
  }

  finishSynthesize(): void {
    if (this.status !== 'SYNTHESIZING') return;
    this.status = 'READY';
  }

  fail(err: string): void {
    this.status = 'ERROR';
  }
}

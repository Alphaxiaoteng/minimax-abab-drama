/**
 * psychology.ts - 审讯心理状态机与动态心率/防卫阻抗追踪器。
 *
 * 为 MiniMax 沉浸式互动剧提供真实心理学博弈机制：
 * 1. 嫌疑人三维心理向量：紧张度 (Nervousness 0-100)、防卫心 (Defensiveness 0-100)、崩溃概率 (BreakdownRisk)。
 * 2. 审讯策略算子 (Interrogation Tactics):
 *    - 施压质问 (PRESSURE): 激化紧张度，但推高阻抗防御
 *    - 心理共情 (EMPATHY): 瓦解防卫心，建立沟通倾诉通道
 *    - 铁证突袭 (EVIDENCE_SLAM): 瞬间引爆心理防线，在谎言证据确凿时引发破防认罪 (CONFESSION_PENDING)
 */

export type InterrogationTactic = 'PRESSURE' | 'EMPATHY' | 'EVIDENCE_SLAM';

export type SuspectMentalState = 'CALM' | 'ON_GUARD' | 'AGITATED' | 'BREAKDOWN';

export interface InterrogationFeedback {
  currentState: SuspectMentalState;
  nervousness: number;
  defensiveness: number;
  heartRateBpm: number;
  unlockedTestimony?: string;
  reactionSpeech: string;
}

export class InterrogationPsychologyEngine {
  private nervousness: number = 20;
  private defensiveness: number = 70;
  private isConfessed: boolean = false;

  constructor(initialNervousness = 20, initialDefensiveness = 70) {
    this.nervousness = Math.min(100, Math.max(0, initialNervousness));
    this.defensiveness = Math.min(100, Math.max(0, initialDefensiveness));
  }

  getNervousness(): number {
    return this.nervousness;
  }

  getDefensiveness(): number {
    return this.defensiveness;
  }

  getHeartRate(): number {
    // 基础静息心率 72 + 紧张度线性加权 (最高达 155 bpm)
    return Math.round(72 + (this.nervousness / 100.0) * 83);
  }

  getState(): SuspectMentalState {
    if (this.nervousness >= 80 && this.defensiveness <= 35) {
      return 'BREAKDOWN';
    }
    if (this.nervousness >= 60) {
      return 'AGITATED';
    }
    if (this.defensiveness >= 50) {
      return 'ON_GUARD';
    }
    return 'CALM';
  }

  applyTactic(
    tactic: InterrogationTactic,
    evidenceStrength: number = 0.5 // 0.0 - 1.0
  ): InterrogationFeedback {
    let reaction = '';
    let unlocked: string | undefined;

    switch (tactic) {
      case 'PRESSURE':
        this.nervousness = Math.min(100, this.nervousness + 18);
        this.defensiveness = Math.min(100, this.defensiveness + 8);
        reaction = '（眼神闪烁，双拳紧握）“警官，你没有证据就不能无端指控我！”';
        break;

      case 'EMPATHY':
        this.defensiveness = Math.max(0, this.defensiveness - 22);
        this.nervousness = Math.max(0, this.nervousness - 6);
        reaction = '（低下头，长长叹了一口气）“其实那天晚上，我也有身不由己的苦衷……”';
        break;

      case 'EVIDENCE_SLAM':
        const impact = Math.round(30 * evidenceStrength);
        this.nervousness = Math.min(100, this.nervousness + impact);
        this.defensiveness = Math.max(0, this.defensiveness - impact * 1.5);

        if (this.nervousness >= 80 && this.defensiveness <= 35) {
          this.isConfessed = true;
          reaction = '（脸色惨白，瘫坐在椅子上）“……别说了。是我做的。所有细节我都交代。”';
          unlocked = '【绝密口供】嫌疑人交代了作案凶器丢弃在后花园人工湖底的具体位置。';
        } else {
          reaction = '（瞳孔骤缩，呼吸急促）“这……这不可能！你们怎么会拿到这个东西？！”';
        }
        break;
    }

    return {
      currentState: this.getState(),
      nervousness: this.nervousness,
      defensiveness: this.defensiveness,
      heartRateBpm: this.getHeartRate(),
      unlockedTestimony: unlocked,
      reactionSpeech: reaction,
    };
  }
}

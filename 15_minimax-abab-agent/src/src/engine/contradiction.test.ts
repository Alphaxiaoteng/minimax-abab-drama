import { describe, it, expect } from 'vitest';
import {
  ContradictionSolver,
  EndingEvaluator,
  StoryEndingType,
  VoiceCloneStateMachine,
  TestimonyFact,
  CaseDeductionContext,
} from './contradiction';

describe('contradiction engine test suite', () => {
  it('ContradictionSolver: 检出时空分身矛盾', () => {
    const facts: TestimonyFact[] = [
      {
        id: 'f1',
        speaker: '李管家',
        timeMinute: 1260, // 21:00
        location: '一楼厨房',
        claimedAction: '煮咖啡',
        statement: '我一直在厨房烧水煮咖啡'
      },
      {
        id: 'f2',
        speaker: '李管家',
        timeMinute: 1262, // 21:02
        location: '三楼书房',
        claimedAction: '整理账目',
        statement: '我当时在书房拿钥匙'
      }
    ];

    const results = ContradictionSolver.analyze(facts);
    expect(results.length).toBe(1);
    expect(results[0].type).toBe('SPATIOTEMPORAL_CONFLICT');
    expect(results[0].conflictingFactIds).toContain('f1');
    expect(results[0].conflictingFactIds).toContain('f2');
  });

  it('ContradictionSolver: 检出物证归属冲突', () => {
    const facts: TestimonyFact[] = [
      {
        id: 'o1',
        speaker: '张合伙人',
        timeMinute: 1260,
        location: '走廊',
        claimedAction: '持有保险柜钥匙',
        involvesObject: '保险柜黄铜钥匙',
        statement: '钥匙一直由我贴身保管'
      },
      {
        id: 'o2',
        speaker: '王律师',
        timeMinute: 1265,
        location: '客房',
        claimedAction: '用钥匙开箱',
        involvesObject: '保险柜黄铜钥匙',
        statement: '钥匙当时在我抽屉里'
      }
    ];

    const results = ContradictionSolver.analyze(facts);
    expect(results.length).toBe(1);
    expect(results[0].type).toBe('OBJECT_COLLISION');
  });

  it('EndingEvaluator: 5 支线结局判定逻辑覆盖', () => {
    // 1. 玉石俱焚
    const v1 = EndingEvaluator.evaluate({
      accusedSuspectId: 'culprit_a',
      actualCulpritId: 'culprit_a',
      unlockedCluesCount: 10,
      totalCluesCount: 10,
      solvedContradictionsCount: 2,
      detectiveDangerScore: 90,
      turnsUsed: 5,
      maxTurns: 15
    });
    expect(v1.ending).toBe(StoryEndingType.MUTUAL_DESTRUCTION);

    // 2. 凶手潜逃
    const v2 = EndingEvaluator.evaluate({
      accusedSuspectId: 'culprit_b',
      actualCulpritId: 'culprit_a',
      unlockedCluesCount: 2,
      totalCluesCount: 10,
      solvedContradictionsCount: 0,
      detectiveDangerScore: 20,
      turnsUsed: 15,
      maxTurns: 15
    });
    expect(v2.ending).toBe(StoryEndingType.COLD_CASE_ESCAPED);

    // 3. 误判替罪羊
    const v3 = EndingEvaluator.evaluate({
      accusedSuspectId: 'innocent_c',
      actualCulpritId: 'culprit_a',
      unlockedCluesCount: 6,
      totalCluesCount: 10,
      solvedContradictionsCount: 1,
      detectiveDangerScore: 10,
      turnsUsed: 8,
      maxTurns: 15
    });
    expect(v3.ending).toBe(StoryEndingType.WRONGFUL_ACCUSATION);

    // 4. 揭秘黑幕反转神级结局 (>=85% 线索 + >=2 矛盾)
    const v4 = EndingEvaluator.evaluate({
      accusedSuspectId: 'culprit_a',
      actualCulpritId: 'culprit_a',
      unlockedCluesCount: 9,
      totalCluesCount: 10,
      solvedContradictionsCount: 2,
      detectiveDangerScore: 30,
      turnsUsed: 8,
      maxTurns: 15
    });
    expect(v4.ending).toBe(StoryEndingType.DARK_CONSPIRACY_UNVEILED);
    expect(v4.score).toBe(100);

    // 5. 正义真凶伏法
    const v5 = EndingEvaluator.evaluate({
      accusedSuspectId: 'culprit_a',
      actualCulpritId: 'culprit_a',
      unlockedCluesCount: 6,
      totalCluesCount: 10,
      solvedContradictionsCount: 1,
      detectiveDangerScore: 30,
      turnsUsed: 8,
      maxTurns: 15
    });
    expect(v5.ending).toBe(StoryEndingType.TRUE_CULPRIT_CONVICTED);
  });

  it('VoiceCloneStateMachine: 音色克隆与合成流转', () => {
    const sm = new VoiceCloneStateMachine();
    expect(sm.getStatus()).toBe('IDLE');

    sm.startClone('https://sample.wav');
    expect(sm.getStatus()).toBe('CLONING');

    sm.completeClone('voice_minimax_007');
    expect(sm.getStatus()).toBe('READY');
    expect(sm.getVoiceId()).toBe('voice_minimax_007');

    sm.setEmotion('panic');
    expect(sm.getEmotion()).toBe('panic');

    sm.startSynthesize();
    expect(sm.getStatus()).toBe('SYNTHESIZING');

    sm.finishSynthesize();
    expect(sm.getStatus()).toBe('READY');
  });
});

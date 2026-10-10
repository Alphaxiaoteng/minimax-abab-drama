/**
 * 人格库与剧本库的契约测试：
 * 人格一致性（口头禅无交集）、语音参数合法性、剧本状态机闸值递增、事实与线索交叉命中。
 */
import { describe, expect, it } from 'vitest';
import { ConfigError } from '../core/errors.js';
import { VOICE_RANGES } from '../core/constants.js';
import type { Persona, VoiceSettings } from '../core/types.js';
import { EMOTIONS, SCENE_PHASES } from '../core/types.js';
import { defaultScreenplay, screenplayRegistry } from '../engine/screenplay.js';
import { ShenYan } from './shen-yan.js';
import { LinXiaoman } from './lin-xiaoman.js';
import { HeJinglan } from './he-jinglan.js';
import { defaultPersona, loadAllPersonas, personaRegistry } from './index.js';

const PERSONAS: readonly Persona[] = [ShenYan, LinXiaoman, HeJinglan];

/** 数值是否落在 VOICE_RANGES 规定区间内 */
function inRange(key: 'speed' | 'vol' | 'pitch', value: number): boolean {
  const [min, max] = VOICE_RANGES[key];
  return value >= min && value <= max;
}

function settingsFields(s: VoiceSettings): Array<'speed' | 'vol' | 'pitch'> {
  return ['speed', 'vol', 'pitch'];
}

describe('人格：必填字段与具体内容', () => {
  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s 所有字段非空且有真实内容', (_id, persona) => {
    expect(persona.id.length).toBeGreaterThan(0);
    expect(persona.name.length).toBeGreaterThan(0);
    expect(persona.tagline.length).toBeGreaterThan(0);
    expect(persona.openingLine.length).toBeGreaterThan(0);
    expect(persona.emotionalRange.length).toBeGreaterThanOrEqual(5);
    expect(persona.emotionalRange.every((e) => EMOTIONS.includes(e))).toBe(true);
  });

  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s biography 与 speechStyle 均为 ≥60 字的具体中文描述', (_id, persona) => {
    expect(persona.biography.length).toBeGreaterThanOrEqual(60);
    expect(persona.speechStyle.length).toBeGreaterThanOrEqual(60);
    expect(/[，。；]/.test(persona.biography)).toBe(true);
    expect(/[，。；]/.test(persona.speechStyle)).toBe(true);
  });
});

describe('人格：口头禅与禁忌的量化约束', () => {
  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s catchphrases ≥4 且 taboos ≥3', (_id, persona) => {
    expect(persona.catchphrases.length).toBeGreaterThanOrEqual(4);
    expect(persona.taboos.length).toBeGreaterThanOrEqual(3);
    expect(new Set(persona.catchphrases).size).toBe(persona.catchphrases.length);
  });

  it('三个人物之间的 catchphrases 两两无交集（人格一致性的量化依据）', () => {
    const sets = PERSONAS.map((p) => new Set(p.catchphrases));
    for (let i = 0; i < sets.length; i += 1) {
      for (let j = i + 1; j < sets.length; j += 1) {
        const overlap = [...(sets[i] as Set<string>)].filter((c) => (sets[j] as Set<string>).has(c));
        expect(overlap).toEqual([]);
      }
    }
  });
});

describe('人格：语音方案合法', () => {
  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s voice.base 与 perEmotion 覆盖项都落在 VOICE_RANGES 内', (_id, persona) => {
    for (const field of settingsFields(persona.voice.base)) {
      expect(inRange(field, persona.voice.base[field])).toBe(true);
    }
    for (const override of Object.values(persona.voice.perEmotion)) {
      for (const field of ['speed', 'vol', 'pitch'] as const) {
        const value = override[field];
        if (value !== undefined) expect(inRange(field, value)).toBe(true);
      }
    }
  });

  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s emotionalRange 是 voice.perEmotion 键的超集', (_id, persona) => {
    for (const emotion of Object.keys(persona.voice.perEmotion)) {
      expect(persona.emotionalRange.includes(emotion as never)).toBe(true);
    }
  });

  it('三个人的 voice.base.voiceId 互不相同', () => {
    const voiceIds = PERSONAS.map((p) => p.voice.base.voiceId);
    expect(new Set(voiceIds).size).toBe(voiceIds.length);
    expect(voiceIds).toEqual(['male-qn-jingying', 'female-shaonv', 'female-yujie']);
  });
});

describe('人格：facts 关键事实', () => {
  it.each(PERSONAS.map((p) => [p.id, p] as const))('%s facts ≥4 条中文键值对且包含「不在场证明」类事实', (_id, persona) => {
    const entries = Object.entries(persona.facts);
    expect(entries.length).toBeGreaterThanOrEqual(4);
    expect(entries.every(([key, value]) => key.length > 0 && value.length > 0)).toBe(true);
    expect(entries.some(([key]) => key.includes('不在场证明'))).toBe(true);
  });
});

describe('personas/index：注册表', () => {
  it('loadAllPersonas 固定顺序 shen-yan → lin-xiaoman → he-jinglan', () => {
    expect(loadAllPersonas().map((p) => p.id)).toEqual(['shen-yan', 'lin-xiaoman', 'he-jinglan']);
  });

  it('defaultPersona 返回沈砚', () => {
    expect(defaultPersona().id).toBe('shen-yan');
  });

  it('personaRegistry 的 all/byId/ids 一致', () => {
    expect(personaRegistry.all).toBe(loadAllPersonas());
    expect(personaRegistry.ids()).toEqual(['shen-yan', 'lin-xiaoman', 'he-jinglan']);
    expect(personaRegistry.byId('lin-xiaoman')).toBe(LinXiaoman);
    expect(personaRegistry.byId('he-jinglan')).toBe(HeJinglan);
  });

  it('byId 未知 id 抛 ConfigError', () => {
    expect(() => personaRegistry.byId('ghost')).toThrow(ConfigError);
    expect(() => personaRegistry.byId('ghost')).toThrow(/未知的人格 id/);
  });
});

describe('engine/screenplay：1024 号案', () => {
  it('id 与中文标题/梗概（≥80 字）合规', () => {
    expect(defaultScreenplay.id).toBe('case-1024-mirror');
    expect(defaultScreenplay.title.length).toBeGreaterThan(0);
    expect(defaultScreenplay.synopsis.length).toBeGreaterThanOrEqual(80);
  });

  it('phases 使用全部 SCENE_PHASES', () => {
    expect(defaultScreenplay.phases).toEqual([...SCENE_PHASES]);
  });

  it('clues ≥6，标题/detail 为中文且 detail ≥30 字，requiredTrust 严格递增且在 0–100', () => {
    expect(defaultScreenplay.clues.length).toBeGreaterThanOrEqual(6);
    let previous = -1;
    for (const clue of defaultScreenplay.clues) {
      expect(clue.title.length).toBeGreaterThan(0);
      expect(clue.detail.length).toBeGreaterThanOrEqual(30);
      expect(clue.requiredTrust).toBeGreaterThan(previous);
      expect(clue.requiredTrust).toBeGreaterThanOrEqual(0);
      expect(clue.requiredTrust).toBeLessThanOrEqual(100);
      previous = clue.requiredTrust;
    }
  });

  it('每条线索 implicates 都指向合法嫌疑人 id', () => {
    const suspectIds = new Set(defaultScreenplay.suspects.map((s) => s.id));
    for (const clue of defaultScreenplay.clues) {
      expect(suspectIds.has(clue.implicates)).toBe(true);
    }
  });

  it('恰好一个 isCulprit: true，且 culpritId 与该嫌疑人一致', () => {
    const culprits = defaultScreenplay.suspects.filter((s) => s.isCulprit);
    expect(culprits.length).toBe(1);
    expect(defaultScreenplay.culpritId).toBe(culprits[0]?.id);
  });

  it('suspects 恰好 3 名且 motive 为具体中文句子', () => {
    expect(defaultScreenplay.suspects.length).toBe(3);
    for (const suspect of defaultScreenplay.suspects) {
      expect(suspect.motive.length).toBeGreaterThanOrEqual(20);
      expect(/[，。；]/.test(suspect.motive)).toBe(true);
    }
  });

  it('phaseGates 覆盖全部五个阶段，严格递增且 intro 为 0', () => {
    expect(SCENE_PHASES.every((phase) => phase in defaultScreenplay.phaseGates)).toBe(true);
    expect(defaultScreenplay.phaseGates.intro).toBe(0);
    let previous = -1;
    for (const phase of SCENE_PHASES) {
      const gate = defaultScreenplay.phaseGates[phase];
      expect(gate).toBeGreaterThan(previous);
      expect(gate).toBeGreaterThanOrEqual(0);
      expect(gate).toBeLessThanOrEqual(100);
      previous = gate;
    }
  });

  it('screenplayRegistry 可按 id 取回默认剧本', () => {
    expect(screenplayRegistry['case-1024-mirror']).toBe(defaultScreenplay);
  });
});

describe('人格 facts ↔ 剧本线索 交叉呼应', () => {
  it('至少 3 条人物事实在线索 detail 中找到关键词呼应', () => {
    // 呼应关系：(人格 facts 关键词, 线索 detail 关键词)
    const pairs: ReadonlyArray<readonly [string, string]> = [
      ['死亡时间', '死亡时间'],
      ['丝绒布', '丝绒布'],
      ['洗笔', '洗笔'],
      ['消防通道', '消防通道'],
      ['不在场证明', '刷卡落锁'],
    ];
    const clueText = defaultScreenplay.clues.map((c) => c.detail).join('\n');
    const factText = PERSONAS.map((p) => Object.values(p.facts).join('\n')).join('\n');
    const hits = pairs.filter(([factKw, clueKw]) => factText.includes(factKw) && clueText.includes(clueKw));
    expect(hits.length).toBeGreaterThanOrEqual(3);
  });
});
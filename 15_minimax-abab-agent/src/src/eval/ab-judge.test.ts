/**
 * ab-judge.ts 的确定性测试。
 */

import { describe, expect, it } from 'vitest';
import {
  DEFAULT_AB_PROFILE,
  buildPairs,
  judgePair,
  runAbJudge,
  scoreText,
} from './ab-judge.js';
import type { AbCandidate } from './ab-judge.js';

const candidates: AbCandidate[] = [
  { id: 'b-cand', text: '有意思，让我们看看这条线索，真相就在眼前，我感到很激动。' },
  { id: 'a-cand', text: '随便说点什么，内容很平，没有任何标记。' },
  { id: 'c-cand', text: '让我们追查真相，线索指向嫌疑人，我怀疑他，很紧张。' },
];

describe('buildPairs', () => {
  it('仅配对不同 id，数量 = C(n,2)，顺序稳定', () => {
    const pairs = buildPairs(candidates);
    expect(pairs.length).toBe(3); // C(3,2)
    // 按 id 排序后 a__b, a__c, b__c
    expect(pairs.map((p) => p.pairId)).toEqual(['a-cand__b-cand', 'a-cand__c-cand', 'b-cand__c-cand']);
  });

  it('输入乱序也产出相同的稳定顺序', () => {
    const shuffled = [candidates[2]!, candidates[0]!, candidates[1]!];
    expect(buildPairs(shuffled).map((p) => p.pairId)).toEqual(buildPairs(candidates).map((p) => p.pairId));
  });

  it('重复 id 抛错', () => {
    expect(() => buildPairs([{ id: 'x', text: 'a' }, { id: 'x', text: 'b' }])).toThrow();
  });
});

describe('scoreText', () => {
  it('命中禁忌词一票否决为 0', () => {
    expect(scoreText('这里有脏话出现', DEFAULT_AB_PROFILE)).toBe(0);
  });
  it('更丰富的文本得分更高', () => {
    const rich = scoreText('有意思，让我们追查真相和线索，我感到激动又紧张。', DEFAULT_AB_PROFILE);
    const plain = scoreText('嗯。', DEFAULT_AB_PROFILE);
    expect(rich).toBeGreaterThan(plain);
  });
  it('得分范围 0–1', () => {
    for (const t of ['', '有意思', '有意思，让我们看看这条线索的真相到底是什么呢我觉得很紧张']) {
      const s = scoreText(t, DEFAULT_AB_PROFILE);
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(1);
    }
  });
});

describe('judgePair', () => {
  it('选出得分更高的一侧并给出中文 rationale', () => {
    const pair = buildPairs(candidates)[0]!;
    const v = judgePair(pair);
    expect(v.rationale.length).toBeGreaterThan(0);
    expect([v.leftId, v.rightId]).toContain(v.winnerId);
  });

  it('同分按 id 字典序裁决（可复现）', () => {
    const pair = {
      pairId: 'p',
      leftId: 'zzz',
      rightId: 'aaa',
      leftText: '同样平庸的短句',
      rightText: '同样平庸的短句',
    };
    const v = judgePair(pair);
    expect(v.tied).toBe(true);
    expect(v.winnerId).toBe('aaa'); // 字典序小者胜
    expect(v.margin).toBe(0);
  });

  it('多次裁决同一对结果一致', () => {
    const pair = buildPairs(candidates)[2]!;
    const a = judgePair(pair);
    const b = judgePair(pair);
    expect(a.winnerId).toBe(b.winnerId);
    expect(a.margin).toBe(b.margin);
  });
});

describe('runAbJudge', () => {
  it('汇总胜率排名，bestId 是胜率最高者', () => {
    const report = runAbJudge(candidates);
    expect(report.standings.length).toBe(3);
    expect(report.bestId).not.toBeNull();
    const top = report.standings[0]!;
    for (const s of report.standings) expect(top.winRate).toBeGreaterThanOrEqual(s.winRate);
  });

  it('并列不判负：全同候选双方各记一次 tie，无 loss', () => {
    const same = [
      { id: 'a', text: '完全一样的文本内容' },
      { id: 'b', text: '完全一样的文本内容' },
    ];
    const report = runAbJudge(same);
    const a = report.standings.find((s) => s.id === 'a')!;
    const b = report.standings.find((s) => s.id === 'b')!;
    expect(a.losses).toBe(0);
    expect(b.losses).toBe(0);
    expect(a.ties).toBe(1);
    expect(b.ties).toBe(1);
  });

  it('结果是确定的，重跑一致', () => {
    expect(runAbJudge(candidates).standings.map((s) => `${s.id}:${s.wins}`)).toEqual(
      runAbJudge(candidates).standings.map((s) => `${s.id}:${s.wins}`),
    );
  });

  it('verdicts 数量与配对数量一致', () => {
    expect(runAbJudge(candidates).verdicts.length).toBe(3);
  });
});
/**
 * 集成验证：跨切片端到端闭环。
 * 这是「离线确定性」的总闸门——不依赖网络、不依赖凭证，必须永远可复现。
 */

import { describe, expect, it } from 'vitest';
import {
  APP_ID,
  DramaEngine,
  MiniMaxClient,
  loadAllPersonas,
  loadConfig,
  defaultScreenplay,
  resolveVoiceSettings,
  personaRegistry,
} from './index.js';

const offlineConfig = () => loadConfig({ MINIMAX_API_KEY: '' }, { forceOffline: true });

describe('集成：富媒体互动 Agent 端到端', () => {
  it('人物库与剧本库可用且互相自洽', () => {
    const personas = loadAllPersonas();
    expect(personas.length).toBe(3);
    expect(personaRegistry.ids()).toEqual(personas.map((p) => p.id));

    const culpritIds = defaultScreenplay.suspects.filter((s) => s.isCulprit).map((s) => s.id);
    expect(culpritIds).toEqual([defaultScreenplay.culpritId]);

    for (const persona of personas) {
      for (const emotion of persona.emotionalRange) {
        const settings = resolveVoiceSettings(persona.voice, emotion);
        expect(settings.speed).toBeGreaterThanOrEqual(0.5);
        expect(settings.speed).toBeLessThanOrEqual(2);
        expect(settings.vol).toBeLessThanOrEqual(10);
        expect(settings.pitch).toBeGreaterThanOrEqual(-12);
        expect(settings.pitch).toBeLessThanOrEqual(12);
      }
    }
  });

  it('离线模式下 6 轮对话全闭环：文本 + 语音 + 状态推进', async () => {
    const persona = personaRegistry.byId('shen-yan');
    const client = new MiniMaxClient({ config: offlineConfig() });
    const engine = new DramaEngine({ persona, screenplay: defaultScreenplay, client, now: () => 0 });

    const opening = await engine.start();
    expect(opening.speech.audio.byteLength).toBeGreaterThan(44);
    expect(opening.state.turns.length).toBeGreaterThan(0);

    const inputs = [
      '你是谁？为什么会出现在这桩案子里',
      '我信任你，把你知道的都告诉我',
      '你在撒谎，这和你之前说的对不上',
      '那晚十一点你究竟在哪里',
      '还有谁有动机',
      '我想看看那幅画背面的东西',
    ];

    let last = opening.state;
    for (const text of inputs) {
      const res = await engine.send({ sessionId: last.sessionId, userText: text });
      expect(res.turn.role).toBe('persona');
      expect(res.turn.text.length).toBeGreaterThan(0);
      expect(res.speech.audio.byteLength).toBeGreaterThan(44);
      expect(res.state.trust).toBeGreaterThanOrEqual(0);
      expect(res.state.trust).toBeLessThanOrEqual(100);
      expect(res.state.tension).toBeLessThanOrEqual(100);
      last = res.state;
    }

    expect(last.turns.length).toBeGreaterThanOrEqual(13);
    expect(last.revealedClueIds.length).toBeGreaterThan(0);
    // 离线模式必然记录降级，但绝不能抛出异常
    expect(client.degradations().length).toBeGreaterThan(0);
    expect(client.mode).toBe('mock');
  });

  it('同 seed 同输入 → 逐字节可复现（这是评测系统的地基）', async () => {
    const run = async () => {
      const persona = personaRegistry.byId('he-jinglan');
      const engine = new DramaEngine({
        persona,
        screenplay: defaultScreenplay,
        client: new MiniMaxClient({ config: offlineConfig() }),
        now: () => 0,
        seed: 4242,
      });
      await engine.start();
      const { sessionId } = engine.state;
      const out: string[] = [];
      for (const text of ['你手上那幅画是谁的', '别用隐喻，直接说', '我需要真相']) {
        const res = await engine.send({ sessionId, userText: text });
        out.push(`${res.turn.text}|${res.speech.audio.byteLength}|${res.speech.durationMs}`);
      }
      return out.join('\n');
    };

    expect(await run()).toBe(await run());
  });

  it('APP_ID 与赛事标识保持稳定（防止误改）', () => {
    expect(APP_ID).toBe('immersive-drama-agent');
  });
});

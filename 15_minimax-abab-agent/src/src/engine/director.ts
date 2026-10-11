/**
 * 导演状态机：DramaEngine。
 * 状态纯函数式更新——每次变更生成新的冻结 DramaState，旧引用永不改写。
 * trust/tension 夹紧 0–100；阶段只沿 SCENE_PHASE_ORDER 前进；resolution 即落幕。
 */

import { SCENE_PHASE_ORDER } from '../core/contracts.js';
import type {
  DialogueRequest,
  DialogueResponse,
  DramaEngineLike,
  EngineOptions,
  MiniMaxClientLike,
  SuspectStress,
  StoryNode,
} from '../core/contracts.js';
import { DeterministicRandom, hashText } from '../core/deterministic.js';
import { ValidationError } from '../core/errors.js';
import { classifyIntent, mockStageDirection } from '../minimax/mock-corpus.js';
import type { IntentBucket } from '../minimax/mock-corpus.js';
import { stripEmotionMarkers } from '../minimax/emotion-parser.js';
import { clampRange, resolveVoiceSettings } from '../core/types.js';
import type {
  ChatMessage,
  DialogueTurn,
  DramaEvent,
  DramaState,
  Emotion,
  Persona,
  ScenePhase,
  Screenplay,
} from '../core/types.js';
import { buildSystemPrompt } from './prompt.js';

interface Reaction {
  readonly trustDelta: number;
  readonly tensionDelta: number;
  readonly emotion: Emotion;
}

/** trust/tension → 情绪/增减 的固定映射表 */
const REACTION_TABLE: Readonly<Record<IntentBucket, Reaction>> = {
  identity: { trustDelta: 2, tensionDelta: 1, emotion: 'calm' },
  evidence: { trustDelta: 4, tensionDelta: 3, emotion: 'suspicious' },
  trust: { trustDelta: 10, tensionDelta: -3, emotion: 'tender' },
  hostility: { trustDelta: -6, tensionDelta: 8, emotion: 'tense' },
  suspects: { trustDelta: 3, tensionDelta: 4, emotion: 'suspicious' },
  smalltalk: { trustDelta: 1, tensionDelta: 0, emotion: 'calm' },
};

function nextPhaseOf(phase: ScenePhase): ScenePhase | null {
  const idx = SCENE_PHASE_ORDER.indexOf(phase);
  if (idx < 0 || idx >= SCENE_PHASE_ORDER.length - 1) return null;
  return SCENE_PHASE_ORDER[idx + 1] ?? null;
}

/** 把期望情绪收进人格允许的情绪集合；落空优先 calm，再取范围首项 */
function fitEmotion(range: readonly Emotion[], candidate: Emotion): Emotion {
  if (range.includes(candidate)) return candidate;
  if (range.includes('calm')) return 'calm';
  return range[0] ?? 'calm';
}

export class DramaEngine implements DramaEngineLike {
  readonly #persona: Persona;
  readonly #screenplay: Screenplay;
  readonly #client: MiniMaxClientLike;
  readonly #now: () => number;
  readonly #seed: number;
  #state: DramaState;
  readonly #events: DramaEvent[] = [];

  constructor(options: EngineOptions) {
    this.#persona = options.persona;
    this.#screenplay = options.screenplay;
    this.#client = options.client;
    this.#now = options.now ?? (() => Date.now());
    this.#seed = options.seed ?? hashText(options.persona.id);

    const sessionId = `session-${DeterministicRandom
      .from(this.#seed, 'session')
      .nextInt(0x100000000)
      .toString(16)
      .padStart(8, '0')}`;

    // 初始化嫌疑人心理压力状态
    const initialStresses = new Map<string, SuspectStress>();
    for (const suspect of this.#screenplay.suspects) {
      initialStresses.set(suspect.id, {
        suspectId: suspect.id,
        stressLevel: 0,
        breakingPoint: 80,
        unlockedConfessions: [],
        evidenceExposed: [],
      });
    }

    // 生成剧情分支节点树
    const storyNodes: StoryNode[] = this.#generateStoryTree();

    this.#state = Object.freeze({
      sessionId,
      personaId: options.persona.id,
      screenplayId: this.#screenplay.id,
      phase: 'intro',
      trust: 10,
      tension: 5,
      revealedClueIds: Object.freeze([]),
      turns: Object.freeze([]),
      ended: false,
      suspectStresses: Object.freeze(initialStresses),
      storyNodes,
    });
  }

  /** 生成剧情分支全景图节点 */
  #generateStoryTree(): StoryNode[] {
    const nodes: StoryNode[] = [];
    let nodeId = 0;

    // 主流程线：每个阶段一个节点
    this.#screenplay.phases.forEach((phase, idx) => {
      nodes.push({
        nodeId: `node-${nodeId++}`,
        label: this.#getPhaseLabel(phase),
        phase,
        trustRequirement: this.#screenplay.phaseGates[phase],
        isUnlocked: false,
      });
    });

    // 真相结局节点
    nodes.push({
      nodeId: `node-${nodeId++}`,
      label: '真相对白',
      phase: 'resolution',
      endingType: 'true',
      isUnlocked: false,
    });

    // 失败结局节点（信任度 < 20）
    nodes.push({
      nodeId: `node-${nodeId++}`,
      label: '对话破裂',
      phase: 'cross-examination',
      endingType: 'bad',
      isUnlocked: false,
    });

    return nodes;
  }

  #getPhaseLabel(phase: ScenePhase): string {
    const labels: Record<ScenePhase, string> = {
      intro: '序幕：案发回溯',
      exploration: '探索：线索收集',
      'cross-examination': '对峙：疑点质询',
      confrontation: '高潮：正面交锋',
      resolution: '终局：真相大白',
    };
    return labels[phase];
  }

  get state(): DramaState {
    return this.#state;
  }

  async start(): Promise<DialogueResponse> {
    const at = this.#now();
    const baseEmotion = fitEmotion(this.#persona.emotionalRange, this.#persona.voice.base.emotion);
    const narratorTurn: DialogueTurn = Object.freeze({
      id: `${this.#state.sessionId}-t0`,
      role: 'narrator',
      text: mockStageDirection('intro'),
      emotion: null,
      at,
    });
    const personaTurn: DialogueTurn = Object.freeze({
      id: `${this.#state.sessionId}-t1`,
      role: 'persona',
      text: stripEmotionMarkers(this.#persona.openingLine),
      emotion: baseEmotion,
      at,
    });

    const before = this.#client.degradations().length;
    const settings = resolveVoiceSettings(this.#persona.voice, baseEmotion);
    const speech = await this.#client.speech(personaTurn.text, settings);
    const degraded = this.#client.degradations().length > before;

    this.#replaceState({ turns: Object.freeze([narratorTurn, personaTurn]) });
    this.#pushEvent('session_started', {
      sessionId: this.#state.sessionId,
      personaId: this.#persona.id,
      screenplayId: this.#screenplay.id,
      phase: this.#state.phase,
    });
    this.#pushEvent('turn_appended', { turnId: narratorTurn.id, role: narratorTurn.role });
    this.#pushEvent('turn_appended', { turnId: personaTurn.id, role: personaTurn.role });
    if (degraded) this.#pushEvent('degraded', { source: 'start' });

    return { turn: personaTurn, speech, state: this.#state, events: this.events(), degraded };
  }

  async send(input: DialogueRequest): Promise<DialogueResponse> {
    if (input.sessionId !== this.#state.sessionId) {
      throw new ValidationError(`会话 ID 不匹配：期望 ${this.#state.sessionId}，收到 ${input.sessionId}`);
    }
    if (this.#state.ended) {
      throw new ValidationError('本局已经落幕，无法继续追问');
    }

    const at = this.#now();
    const count = this.#state.turns.length;
    const userTurn: DialogueTurn = Object.freeze({
      id: `${this.#state.sessionId}-t${count}`,
      role: 'user',
      text: input.userText,
      emotion: null,
      at,
    });

    const bucket = classifyIntent(input.userText);
    const reaction = REACTION_TABLE[bucket];
    const nextTrust = clampRange(this.#state.trust + reaction.trustDelta, 0, 100);
    const nextTension = clampRange(this.#state.tension + reaction.tensionDelta, 0, 100);
    const expectedEmotion = fitEmotion(
      this.#persona.emotionalRange,
      bucket === 'hostility' && nextTension >= 60 ? 'furious' : reaction.emotion,
    );

    const history: ChatMessage[] = [{
      role: 'system',
      content: buildSystemPrompt(this.#persona, this.#screenplay, this.#state, this.#seed),
    }];
    for (const t of this.#state.turns) {
      if (t.role === 'user') history.push({ role: 'user', content: t.text });
      else if (t.role === 'persona') history.push({ role: 'assistant', content: t.text });
    }
    history.push({ role: 'user', content: input.userText });

    const before = this.#client.degradations().length;
    const textResult = await this.#client.chat(history, expectedEmotion);
    const emotion = fitEmotion(this.#persona.emotionalRange, textResult.emotion);
    const personaTurn: DialogueTurn = Object.freeze({
      id: `${this.#state.sessionId}-t${count + 1}`,
      role: 'persona',
      text: stripEmotionMarkers(textResult.text),
      emotion,
      at: this.#now(),
    });
    const settings = resolveVoiceSettings(this.#persona.voice, emotion);
    const speech = await this.#client.speech(personaTurn.text, settings);
    const degraded = this.#client.degradations().length > before;

    this.#replaceState({
      trust: nextTrust,
      tension: nextTension,
      turns: Object.freeze([...this.#state.turns, userTurn, personaTurn]),
    });
    this.#pushEvent('turn_appended', { turnId: userTurn.id, role: userTurn.role, bucket });
    this.#pushEvent('turn_appended', { turnId: personaTurn.id, role: personaTurn.role, emotion });

    const revealed: string[] = [];
    for (const clue of this.#screenplay.clues) {
      if (!this.#state.revealedClueIds.includes(clue.id) && nextTrust >= clue.requiredTrust) {
        revealed.push(clue.id);
      }
    }
    if (revealed.length > 0) {
      this.#replaceState({
        revealedClueIds: Object.freeze([...this.#state.revealedClueIds, ...revealed]),
      });
      for (const id of revealed) {
        const clue = this.#screenplay.clues.find((c) => c.id === id);
        this.#pushEvent('clue_revealed', { clueId: id, title: clue?.title ?? id });
      }
    }

    let phase = this.#state.phase;
    for (;;) {
      const next = nextPhaseOf(phase);
      if (next === null || nextTrust < this.#screenplay.phaseGates[next]) break;
      phase = next;
      this.#replaceState({ phase });
      this.#pushEvent('phase_advanced', { phase });
      const direction = mockStageDirection(phase);
      this.#pushEvent('stage_direction', { phase, text: direction });
      if (phase === 'resolution') {
        this.#replaceState({ ended: true });
        this.#pushEvent('session_ended', { culpritId: this.#screenplay.culpritId });
        break;
      }
    }

    if (degraded) this.#pushEvent('degraded', { source: 'chat' });

    return {
      turn: personaTurn,
      speech,
      state: this.#state,
      events: this.events(),
      degraded,
    };
  }

  events(): readonly DramaEvent[] {
    return [...this.#events];
  }

  #replaceState(patch: Partial<DramaState>): void {
    this.#state = Object.freeze({ ...this.#state, ...patch });
  }

  #pushEvent(type: DramaEvent['type'], payload: Record<string, unknown>): void {
    this.#events.push(Object.freeze({ type, at: this.#now(), payload: Object.freeze(payload) }));
  }

  /* ==================== 可视化增强功能 ==================== */

  /** 审讯模式：向指定嫌疑人出示证据，增加心理压力 */
  exposeEvidence(suspectId: string, evidenceId: string): { stressDelta: number; broke?: boolean } {
    const stress = this.#state.suspectStresses.get(suspectId);
    if (!stress) {
      throw new ValidationError(`未知嫌疑人 ID: ${suspectId}`);
    }

    const existingIdx = stress.evidenceExposed.indexOf(evidenceId);
    if (existingIdx >= 0) {
      return { stressDelta: 0 }; // 已出示过，不重复增加压力
    }

    // 计算压力增量（基础 + 线索关键度）
    const clue = this.#screenplay.clues.find((c) => c.id === evidenceId);
    const baseDelta = 15;
    const keynessDelta = clue?.implicates === suspectId ? 20 : 0;
    const stressDelta = Math.min(35, baseDelta + keynessDelta);

    const newStressLevel = clampRange(stress.stressLevel + stressDelta, 0, 100);
    const broke = newStressLevel >= (stress.breakingPoint ?? 80);

    // 更新应力状态
    const updatedStress: SuspectStress = {
      ...stress,
      stressLevel: newStressLevel,
      evidenceExposed: [...stress.evidenceExposed, evidenceId],
    };

    // 破防后解锁隐藏证词
    if (broke && !stress.unlockedConfessions.includes('confession-core')) {
      updatedStress.unlockedConfessions = [...updatedStress.unlockedConfessions, 'confession-core'];
    }

    this.#replaceState({
      suspectStresses: new Map(this.#state.suspectStresses).set(suspectId, updatedStress),
    });

    return { stressDelta, broke };
  }

  /** 获取嫌疑人审讯状态 */
  getInterrogationStatus(suspectId: string): SuspectStress | undefined {
    return this.#state.suspectStresses.get(suspectId);
  }

  /** 设置当前选中的证据（用于红绳墙展示连线） */
  selectEvidence(evidenceId?: string): void {
    this.#replaceState({ selectedEvidenceId: evidenceId });
  }

  /** 设置当前审讯的嫌疑人 */
  setInterrogationTarget(suspectId?: string): void {
    this.#replaceState({ currentInterrogationSuspectId: suspectId });
  }

  /** 获取剧情分支树状态 */
  getStoryTree(): readonly StoryNode[] {
    return this.#state.storyNodes;
  }

  /** 更新故事节点解锁状态（根据 trust/tension） */
  updateStoryProgression(): void {
    const newNodes = this.#state.storyNodes.map((node) => {
      let unlocked = node.isUnlocked;
      if (node.trustRequirement !== undefined && this.#state.trust >= node.trustRequirement) {
        unlocked = true;
      }
      if (node.tensionRequirement !== undefined && this.#state.tension >= node.tensionRequirement) {
        unlocked = true;
      }
      if (this.#state.phase === node.phase) {
        unlocked = true;
      }
      return unlocked ? { ...node, isUnlocked: true } : node;
    });

    if (newNodes.some((n, i) => n.isUnlocked !== this.#state.storyNodes[i].isUnlocked)) {
      this.#replaceState({ storyNodes: newNodes });
    }
  }

  /** 获取所有嫌疑人概览 */
  getAllSuspects(): Readonly<{ id: string; name: string; stress: SuspectStress }>[] {
    return this.#screenplay.suspects.map((s) => ({
      id: s.id,
      name: s.name,
      stress: this.#state.suspectStresses.get(s.id)!,
    }));
  }
}
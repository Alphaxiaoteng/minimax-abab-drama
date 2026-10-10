/**
 * 离线确定性语料引擎：「真实失败 → mock 兜底」这条路径的唯一文本来源。
 *
 * 组织方式：Emotion × 玩家意图关键词桶（6 类）。取交集选句，
 * 再拼接 persona 口头禅形成人格指纹，句尾固定输出 `（语气：X）` 情绪标记，
 * 供 emotion-parser 在 live/mock 两条路径上用同一套逻辑解析。
 *
 * 全部选择由 MOCK_SEED + persona + userText 指纹 + turnIndex 派生，
 * 禁止 Date/Math.random，因此同输入必得同文本（逐字节可复现）。
 */

import { MOCK_SEED } from '../core/constants.js';
import { DeterministicRandom, hashText } from '../core/deterministic.js';
import { EMOTION_LABELS } from '../core/types.js';
import type { Emotion, ScenePhase } from '../core/types.js';


/** mock 语料只消费人格的身份与口头禅两项，故接受最小投影 */
export interface MockPersona {
  readonly id: string;
  readonly catchphrases: readonly string[];
}

/** client 从系统提示词反解析出来的最小人格投影 */
export function personaFromSystemMessages(
  messages: readonly { role: string; content: string }[],
): MockPersona {
  const system = messages.find((m) => m.role === 'system');
  const content = system?.content ?? '';
  const idMatch = content.match(/（id：([^）]+)）/);
  const catchMatch = content.match(/口头禅：([^\n]+)/);
  const catchphrases = catchMatch?.[1]
    ? catchMatch[1].split('、').map((s) => s.trim()).filter((s) => s.length > 0)
    : [];
  return { id: idMatch?.[1] ?? 'anonymous', catchphrases };
}


export const INTENT_BUCKETS = [
  'identity',
  'evidence',
  'trust',
  'hostility',
  'suspects',
  'smalltalk',
] as const;

export type IntentBucket = (typeof INTENT_BUCKETS)[number];

/** 意图桶 → 中文标签，供评测报告展示「玩家这句话被归为哪类」 */
export const INTENT_LABELS: Readonly<Record<IntentBucket, string>> = {
  identity: '询问身份',
  evidence: '追问证据',
  trust: '表达信任',
  hostility: '表达敌意',
  suspects: '讨论其他嫌疑人',
  smalltalk: '闲聊寒暄',
};

/** 意图桶关键词表：按 INTENT_BUCKETS 顺序首个命中即采纳 */
const INTENT_KEYWORDS: Readonly<Record<Exclude<IntentBucket, 'smalltalk'>, readonly string[]>> = {
  identity: ['你到底是谁', '到底是谁', '是谁', '你是谁', '你是什么人', '你算什么', '什么身份', '介绍一下自己', '你是干什么', '你凭什么', '你又是谁'],
  evidence: ['证据', '尸检', '记录', '时间线', '监控', '合同', '几点', '在哪里', '在哪', '痕迹', '检材', '回放', '指纹'],
  trust: ['我信', '信任', '说实话', '告诉我', '拜托', '别瞒', '帮帮我', '我需要真相', '我需要你'],
  hostility: ['撒谎', '说谎', '骗', '胡说', '对不上', '你在狡辩', '闭嘴', '滚', '别装', '可疑', '你在躲'],
  suspects: ['还有谁', '别人', '其他人', '她', '他', '谁有动机', '谁的', '嫌疑人', '保安', '合伙人', '赞助人'],
};

/**
 * 语料库：8 种情绪 × 6 个意图桶，每桶 2 句手写推理剧台词。
 * 语境统一为「镜澜画廊闭馆夜」案：句子可单独成立，不含占位模板。
 */
export const MOCK_CORPUS: Readonly<Record<Emotion, Readonly<Record<IntentBucket, readonly string[]>>>> = {
  calm: {
    identity: [
      '我只陈述能核对的部分，其余留给时间。',
      '你可以慢慢问，但别指望我用猜测填空。',
    ],
    evidence: [
      '把带时间戳的东西摆上桌，其他的先放一边。',
      '记录不会脸红，它只会前后矛盾。',
    ],
    trust: [
      '你愿意听，我就愿意讲，顺序别弄反。',
      '信不信我，取决于你手上还剩多少疑问。',
    ],
    hostility: [
      '你可以激动，我只负责把话留在原地。',
      '冲我提高音量，不会让事实改变形状。',
    ],
    suspects: [
      '每个人都有钟点，我只报我亲眼看到的那一格。',
      '先别急着指谁，把所有人的时间线摊平了再比。',
    ],
    smalltalk: [
      '灯灭过一次又亮了，这件事本身就是线索。',
      '夜里的展厅比白天坦白，你感觉到了吧。',
    ],
  },
  joyful: {
    identity: [
      '难得有人问到点子上，我心情不错，多说两句。',
      '你这个问题问得漂亮，我一直喜欢会问的人。',
    ],
    evidence: [
      '这条对上了，像画布落下最后一笔，痛快。',
      '有意思，细节开始往同一个方向聚了。',
    ],
    trust: [
      '你肯信我一次，我就把剩下的都交给你。',
      '合作最怕揣着明白装糊涂，我们不是。',
    ],
    hostility: [
      '生气也正常，我等得起，证据更等得起。',
      '你急你的，我这边好消息还多着呢。',
    ],
    suspects: [
      '这出戏里谁都不清白，也谁都不绝对坏。',
      '有意思的是，每个人都在替别人遮掩一点什么。',
    ],
    smalltalk: [
      '好久没遇到能聊两句的人了，闭馆后的画廊真安静。',
      '今晚月色不错，适合把旧事翻出来晒晒。',
    ],
  },
  tense: {
    identity: [
      '别这样盯着我，我只是恰好知道一点点。',
      '你可以怀疑我，但请快些，时间不站在任何人那边。',
    ],
    evidence: [
      '那份记录我看过两遍，第二遍开始手抖。',
      '细节我都记得，只是说出来需要点勇气。',
    ],
    trust: [
      '你到底站哪边，先把话说明白。',
      '我现在只敢信还愿意听我讲完的人。',
    ],
    hostility: [
      '你这样质问，我只能把话咽回去。',
      '再逼近一步，我就得开始考虑自保了。',
    ],
    suspects: [
      '别人几点走的，我看得清清楚楚，可我不敢先开口。',
      '提到东偏厅我就发紧，那一格少了一盏灯。',
    ],
    smalltalk: [
      '走廊又黑了，这种安静让人心里发毛。',
      '你听到了吗，楼上刚才有动静。',
    ],
  },
  sorrowful: {
    identity: [
      '我认识他十年，最后连一句道别都没赶上。',
      '别问我算什么，我只是没救成合伙人的幸存者。',
    ],
    evidence: [
      '那块布上的水还没干，我的眼眶先干了。',
      '他留给我最后一份合同，名字被水渍晕开了。',
    ],
    trust: [
      '你肯听，我就把这十年慢慢讲完。',
      '这些话压了太久，今天只说给你一个人。',
    ],
    hostility: [
      '要怪就怪我，别绕着圈子折磨旁人。',
      '你尽可以冲我来，该疼的地方早就疼过了。',
    ],
    suspects: [
      '他生前最怕让身边人难堪，我不替他丢这个人。',
      '她那晚鞋是湿的，我看见了，却说不出口。',
    ],
    smalltalk: [
      '闭馆以后我总在这儿坐一会儿，灯灭得像送客。',
      '画可以重画，人没法再展一次。',
    ],
  },
  furious: {
    identity: [
      '我是谁不重要，重要的是谁在装无辜。',
      '少拿身份压我，我在自己的馆里还没被人审过。',
    ],
    evidence: [
      '合同就在那儿，谁改过日期，自己心里清楚。',
      '藏证据的人，比烧证据的人更可恨。',
    ],
    trust: [
      '我信过一次，代价是一条命，别再让我赌。',
      '要我信你，先把隐瞒的那半句交出来。',
    ],
    hostility: [
      '荒唐，你竟然有脸坐在这儿讲条件。',
      '拍桌子没用，有种把那晚的记录拿出来。',
    ],
    suspects: [
      '谁在闭馆后还留在二层，问他自己。',
      '有人把湿布塞进垃圾桶，以为没人看见。',
    ],
    smalltalk: [
      '这地方今天每一面镜子都让我来气。',
      '开馆十年，第一次觉得满墙展品都是赃物。',
    ],
  },
  fearful: {
    identity: [
      '我只是一个还没想好怎么说的人，别逼我。',
      '你再问下去，我会出事，真的。',
    ],
    evidence: [
      '那份借展单我不敢碰，上面有不该出现的字。',
      '我录过一段音，到现在不敢听完第二遍。',
    ],
    trust: [
      '你要是肯说一句实话，我就敢跟你走这一趟。',
      '我现在只敢把话交给一个还没被吓退的人。',
    ],
    hostility: [
      '别过来，先把那只手放下，我们慢慢说。',
      '你这么问，我很怕你会把我说成什么。',
    ],
    suspects: [
      '那个人走得很急，我没敢跟上去看清脸。',
      '我只知道电梯在二十三点差一分停过。',
    ],
    smalltalk: [
      '灯又要灭了，每次都是这个钟点。',
      '咱们说话轻一点，这馆里有回声。',
    ],
  },
  suspicious: {
    identity: [
      '你的开场白和上一个记者一模一样，我不太放心。',
      '你说你是来查案的，谁能证明你两点后没离开。',
    ],
    evidence: [
      '时间差得太小，我不信这是巧合。',
      '这段记录被人改过，改得很急，破绽在右下角。',
    ],
    trust: [
      '我先把疑问列完，再谈信不信的事。',
      '你可以继续说，我会逐条对。',
    ],
    hostility: [
      '你急什么，急着转移话题的人才该被问。',
      '同一套口径背了三遍，你不累吗。',
    ],
    suspects: [
      '她说是打翻了洗笔水，可那天洗笔区根本没开。',
      '有人二十三点前就走了，监控只拍到一半。',
    ],
    smalltalk: [
      '你注意到没有，今晚保安换了张面孔。',
      '镜厅的灯灭过一次，时间刚好卡在门房换班。',
    ],
  },
  tender: {
    identity: [
      '别怕，我只是站得离你近了一点的那个人。',
      '你可以慢慢说，我这儿不急。',
    ],
    evidence: [
      '我们不着急，先看这条最轻的线索。',
      '手给我，这部分我替你念，你听着就好。',
    ],
    trust: [
      '我信你，从你肯来这儿开始就信了。',
      '放心，你说的每一句我都记着，不外传。',
    ],
    hostility: [
      '我知道你不是针对我，这地方谁都容易被吓着。',
      '气话我接着，你别伤了嗓子。',
    ],
    suspects: [
      '她也不是故意的，那晚她只是太慌张了。',
      '每个人都在护着点什么，我们轻声一点谈。',
    ],
    smalltalk: [
      '夜比白昼诚实，你愿意陪我待一会儿吗。',
      '落地灯给你留着，剩下交给黑暗就好。',
    ],
  },
};

/** 五个阶段的舞台指示（旁白用），每阶段两句，按 phase 指纹确定性择一 */
const STAGE_DIRECTIONS: Readonly<Record<ScenePhase, readonly string[]>> = {
  intro: [
    '灯光压到两成，只剩展签的反光；玩家被允许说出第一句话。',
    '保安走向三号门查监控，脚步声渐远，镜厅里只剩两个人。',
  ],
  exploration: [
    '某盏落地灯闪了一下，没人去修；灰尘在光柱里慢慢落定。',
    '长桌上的丝绒布被掀开一角，底下压着一张被水洇过的借展单。',
  ],
  'cross-examination': [
    '墙上的挂钟被拨慢了两分钟，没有人指出；时间线开始互相摩擦。',
    '门房换班的记录摊在两人之间，缺了最要紧的那一行。',
  ],
  confrontation: [
    '湿透的丝绒布被放在长桌正中，展厅温度仿佛降了两度。',
    '所有人同时沉默了三秒，镜面把三种表情一起收进画面。',
  ],
  resolution: [
    '最后一盏灯熄灭前，镜子替所有人记住了此刻的姿势。',
    '借展合同被收进证物袋，画廊的广播响起闭馆提示音。',
  ],
};

/** 情绪标记句尾，emotion-parser 的第一优先级格式 */
function emotionMarker(emotion: Emotion): string {
  return `（语气：${EMOTION_LABELS[emotion]}）`;
}

/** 玩家文本 → 意图桶；按优先级顺序首个命中，全落空为 smalltalk */
export function classifyIntent(userText: string): IntentBucket {
  for (const bucket of INTENT_BUCKETS) {
    if (bucket === 'smalltalk') continue;
    const words = INTENT_KEYWORDS[bucket];
    for (const word of words) {
      if (userText.includes(word)) return bucket;
    }
  }
  return 'smalltalk';
}

/**
 * 意图桶与情绪桶的交集选句：这是「按 Emotion × 关键词桶组织」的字面实现。
 * 交集为空（理论上不会发生）时逐级回落到情绪桶其他桶，保证永不抛错。
 */
function linesFor(emotion: Emotion, bucket: IntentBucket): readonly string[] {
  const byEmotion = MOCK_CORPUS[emotion];
  const direct = byEmotion[bucket];
  if (direct && direct.length > 0) return direct;
  for (const candidate of INTENT_BUCKETS) {
    const fallback = byEmotion[candidate];
    if (fallback && fallback.length > 0) return fallback;
  }
  return ['这件事我需要一点时间才能回答。'];
}

const MAX_TOTAL_CODEPOINTS = 120;
const MIN_BODY_CODEPOINTS = 12;

/** 把任意码点数压进上限：优先保留口头禅与情绪标记，从句子尾部裁剪 */
function fitLength(sentence: string, decoration: string, marker: string): string {
  const budget = MAX_TOTAL_CODEPOINTS - [...decoration].length - [...marker].length;
  const codepoints = [...sentence];
  if (codepoints.length <= budget) return sentence;
  return `${codepoints.slice(0, Math.max(6, budget - 1)).join('')}…`;
}

export interface MockReplyInput {
  readonly persona: MockPersona;
  readonly emotion: Emotion;
  readonly userText: string;
  readonly turnIndex: number;
  readonly screenplayTag?: string;
  /**
   * 全量 messages 指纹（role+content，顺序敏感，由 MiniMaxClient 计算）。
   * engine 的 seed 会经系统提示词进入该指纹，因此不同 seed 的会话必然产出不同文本。
   */
  readonly messageFingerprint?: number;
}

/**
 * 组装一条确定性 mock 回复。
 * 派生键：MOCK_SEED ^ hashText(persona.id) ^ messageFingerprint，step 为
 * `userText:turnIndex:screenplayTag`；输出保证含 ≥1 条口头禅与句尾情绪标记。
 */
export function composeMockReply(input: MockReplyInput): string {
  const { persona, emotion, userText, turnIndex } = input;
  const seed = (MOCK_SEED ^ hashText(persona.id) ^ (input.messageFingerprint ?? 0)) >>> 0;
  const rng = DeterministicRandom.from(seed, `${userText}:${turnIndex}:${input.screenplayTag ?? ''}`);

  const bucket = classifyIntent(userText);
  const sentence = rng.pick(linesFor(emotion, bucket));

  const catchphrasePool = persona.catchphrases.length > 0 ? persona.catchphrases : [''];
  const catchphrase = rng.pick(catchphrasePool) as string;
  const connector = rng.pick(['——', '。', '；', '，']) as string;
  const decoration = catchphrase.length > 0 ? `${connector}${catchphrase}` : '';

  const marker = emotionMarker(emotion);
  let body = fitLength(sentence, decoration, marker);
  // 下限保障：过短则从同桶追加第二句，确保信息量与 20 字下界
  if ([...body].length < MIN_BODY_CODEPOINTS) {
    const extra = rng.pick(linesFor(emotion, bucket));
    body = fitLength(`${body}　${extra}`, decoration, marker);
  }
  return `${body}${decoration}${marker}`;
}

/** 舞台指示：每个阶段一句中文旁白，由 phase 指纹确定性选择 */
export function mockStageDirection(phase: ScenePhase): string {
  const rng = DeterministicRandom.from(MOCK_SEED ^ hashText(phase), phase);
  return rng.pick(STAGE_DIRECTIONS[phase]) as string;
}
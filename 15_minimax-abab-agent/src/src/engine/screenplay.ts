/**
 * 1024 号案剧本库（SLICE B / personas 归属，engine 只承载剧本数据）。
 *
 * 不变量（personas.test.ts 逐条断言，改动必须同步测试）：
 * 1. phases 使用全部 SCENE_PHASES；phaseGates 五键齐全、严格递增、intro 为 0。
 * 2. clues ≥6，detail ≥30 字，requiredTrust 严格递增且落 0–100，implicates 指向合法嫌疑人。
 * 3. suspects 恰好 3 名，motive 为具体中文句子；恰好一个 isCulprit 且与 culpritId 一致。
 * 4. facts↔clue 关键词交叉命中 ≥3：线索 detail 必须复现人物事实里的
 *    「死亡时间 / 丝绒布 / 洗笔 / 消防通道 / 刷卡落锁」。
 */

import type { Screenplay } from '../core/types.js';
import { SCENE_PHASES } from '../core/types.js';

/**
 * 默认剧本：《1024 号案：镜厅未干的倒影》。
 * 真为何静澜——画廊主理人，借展合同、湿鞋、未登记消防门共同指向她。
 */
export const defaultScreenplay: Screenplay = {
  id: 'case-1024-mirror',
  title: '1024 号案：镜厅未干的倒影',
  synopsis:
    '10 月 3 日夜，镜澜画廊闭馆后，藏家陆鸣被发现死于东偏厅的落地镜前，镜面有一道尚未登记的裂痕。' +
    '三名与这幅画有关的人——冷面法医顾问沈砚、自媒体调查记者林小满、阴郁画廊主理人何静澜——各自握着拼图的一角。' +
    '滴水的丝绒布与一扇没登记的门，正在悄悄改写所有人的说辞。',
  phases: [...SCENE_PHASES],
  culpritId: 'he-jinglan',
  suspects: [
    {
      id: 'shen-yan',
      name: '沈砚',
      motive:
        '他坚持死亡时间在闭馆之前，与门禁记录对不上；一旦时间被前移，他的鉴定结论就是本案最大变量。',
      isCulprit: false,
    },
    {
      id: 'lin-xiaoman',
      name: '林小满',
      motive:
        '她连夜剪辑的直播回放里，有一段被删掉的三分钟；那三分钟决定了画廊当晚究竟还进过谁。',
      isCulprit: false,
    },
    {
      id: 'he-jinglan',
      name: '何静澜',
      motive:
        '借展合同只有她与死者的签名，落款被水渍晕开；她既是最先发现尸体的人，也是唯一握有那扇门钥匙的人。',
      isCulprit: true,
    },
  ],
  clues: [
    {
      id: 'clue-time-of-death',
      title: '死亡时间鉴定',
      detail:
        '沈砚的初步尸检显示死亡时间应落在 23:00 前后，但画廊门禁记录何静澜在 22:40 便已刷卡落锁，两条时间线互相矛盾。',
      requiredTrust: 0,
      implicates: 'shen-yan',
    },
    {
      id: 'clue-mirror-premature-break',
      title: '先碎的镜子',
      detail:
        '落地镜的裂痕出现在死者倒影之下，玻璃碎屑却压在尚未干透的水渍上面，说明镜子先碎、水后洒。',
      requiredTrust: 30,
      implicates: 'he-jinglan',
    },
    {
      id: 'clue-live-stream-log',
      title: '直播回放的时间戳',
      detail:
        '林小满的回放里有一段缺失的三分钟，缺失片段的结尾时间恰好卡在死亡时间鉴定的争议区间内。',
      requiredTrust: 55,
      implicates: 'lin-xiaoman',
    },
    {
      id: 'clue-unsent-message',
      title: '没发出去的私信',
      detail:
        '死者的手机里有一条未发出的私信，质问何静澜借展合同的签名为何被水渍晕开，发送失败时间是 23:12。',
      requiredTrust: 70,
      implicates: 'he-jinglan',
    },
    {
      id: 'clue-wet-velvet-cloth',
      title: '滴水的丝绒布',
      detail:
        '东偏厅角落有一块仍在滴水的丝绒布，纤维上残留着洗笔水的痕迹；当日展厅并未开放洗笔区，何静澜手上的纱布正是用来擦这摊水。',
      requiredTrust: 85,
      implicates: 'he-jinglan',
    },
    {
      id: 'clue-fire-exit-lock',
      title: '没登记的那道门',
      detail:
        '门禁系统显示 22:40 由何静澜本人刷卡落锁，但东偏厅的消防通道既不在闭馆核查表上，也无人登记，是唯一一条能在落锁后仍进出的路径。',
      requiredTrust: 95,
      implicates: 'he-jinglan',
    },
  ],
  phaseGates: {
    intro: 0,
    exploration: 20,
    'cross-examination': 50,
    confrontation: 80,
    resolution: 95,
  },
};

/** 剧本注册表，按 id 取回；UI/评测从这里读剧本。 */
export const screenplayRegistry: Readonly<Record<string, Screenplay>> = {
  [defaultScreenplay.id]: defaultScreenplay,
};

export function loadScreenplayById(id: string): Screenplay {
  const found = screenplayRegistry[id];
  if (found === undefined) throw new Error(`未知剧本 id: ${id}`);
  return found;
}
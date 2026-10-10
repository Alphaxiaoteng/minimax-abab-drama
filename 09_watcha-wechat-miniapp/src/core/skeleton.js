// 骨架步骤：agent.run 首帧必须是 skeleton，先让界面出现「读结构 → 提数据 → 标风险 → 出结论」的占位，
// 再逐步把流式文本填进对应步骤，评委在慢速网络下也能看到「在动」而非白屏。

const SKELETONS = {
  quickread: ['解析文本', '一句话结论', '关键数据', '风险点', '引用依据'],
  triage: ['梳理待办', '今日必做', '可延后', '建议删除', '时间块']
};

// 步骤状态机：pending → running → done。text 为该步骤最终文本内容。
function buildSkeleton(scene) {
  const names = SKELETONS[scene] || SKELETONS.quickread;
  const steps = names.map(function (name, i) {
    return { id: 'step_' + scene + '_' + i, name: name, state: 'pending', text: '' };
  });
  return { steps: steps, progress: 0 };
}

function findStep(agent, scene, index) {
  const steps = agent.getSteps ? agent.getSteps() : (agent.steps || []);
  return steps[index] || null;
}

// 把骨架挂到 agent：agent 需实现 emit({kind,text}) 与 setSteps(steps)。
// 这里用最小侵入：installSkeleton 直接把骨架 push 进 bus，并记录到 agent._skeleton。
function installSkeleton(agent, scene) {
  const sk = buildSkeleton(scene);
  agent._skeleton = sk;
  sk.steps.forEach(function (step, i) {
    if (i === 0) step.state = 'running';
    agent.emit({ kind: 'skeleton', text: step.name, at: Date.now() });
  });
  return sk;
}

// 按步骤名把流式文本填进对应骨架槽位，找不到则追加。
function fillSkeleton(agent, kind, text) {
  const sk = agent._skeleton;
  if (!sk) return;
  const idx = SK_STEP_INDEX[kind];
  if (typeof idx !== 'number') return;
  const step = sk.steps[idx];
  if (!step) return;
  step.state = 'running';
  step.text = text;
  sk.progress = Math.round(((idx + 1) / sk.steps.length) * 100);
  agent.emit({ kind: 'step', text: step.name + '|' + step.state, at: Date.now() });
}

// kind → quickread 步骤索引映射；triage 用同序 index。
const SK_STEP_INDEX = {
  conclusion: 1,
  data: 2,
  risk: 3,
  evidence: 4,
  today: 1,
  defer: 2,
  delete: 3,
  blocks: 4
};

function completeSkeleton(agent) {
  const sk = agent._skeleton;
  if (!sk) return;
  sk.steps.forEach(function (step) { if (step.state !== 'done') step.state = 'done'; });
  sk.progress = 100;
  agent.emit({ kind: 'skeleton_done', text: '完成', at: Date.now() });
}

module.exports = {
  SKELETONS,
  buildSkeleton,
  installSkeleton,
  fillSkeleton,
  completeSkeleton
};
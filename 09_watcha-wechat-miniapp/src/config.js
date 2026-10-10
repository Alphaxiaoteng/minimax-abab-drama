// 全局配置。CLOUD_ENV / AGENT_BOT_ID 留空 = 走离线确定性内核（评委无云环境也能完整跑通演示）。
// 上线前把 CLOUD_ENV 换成云开发环境 ID，AGENT_BOT_ID 换成云开发 Agent ID，并把 appid 占位符替换掉。

const CLOUD_ENV = '';
const AGENT_BOT_ID = '';

// 首选模型与降级顺序；基础库版本或调用异常时按此顺序回退，全部失败则由 core/agent.js 降级到 local-engine。
const MODEL = 'deepseek-v4.1-flash';
const MODEL_FALLBACKS = ['hy3', 'glm-5.3-flash', 'kimi-k3'];

// 两个业务场景，key 与分包路由、skeleton、local-engine 方法一一对应。
const SCENES = {
  QUICKREAD: 'quickread',
  TRIAGE: 'triage'
};

// AI 调用超时（ms）。超过即静默降级，绝不白屏。
const TIMEOUT_MS = 60000;

// 输入长度上限，防止超长文本拖垮摘要打分与流式渲染。
const MAX_INPUT_CHARS = 8000;

// 纯离线演示开关：true 时 ai-adapter 直接不可用，强制走 local-engine，方便录屏与本地测试。
const IS_OFFLINE_DEMO = false;

module.exports = {
  CLOUD_ENV,
  AGENT_BOT_ID,
  MODEL,
  MODEL_FALLBACKS,
  SCENES,
  TIMEOUT_MS,
  MAX_INPUT_CHARS,
  IS_OFFLINE_DEMO
};
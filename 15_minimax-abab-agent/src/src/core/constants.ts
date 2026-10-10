/**
 * 全局常量与运行时开关（唯一事实来源）。
 * 任何切片都不得再定义第二份常量表。
 */

/** 赛事与产品标识 */
export const APP_ID = 'immersive-drama-agent' as const;
export const APP_NAME = '沉浸式互动推理剧 Agent' as const;

/** MiniMax 开放平台默认配置（可被环境变量覆盖，见 config.ts） */
export const MINIMAX_DEFAULTS = {
  baseUrl: 'https://api.minimax.chat',
  textPath: '/v1/text/chatcompletion_v2',
  ttsPath: '/v1/t2a_v2',
  textModel: 'abab7-chat-preview',
  speechModel: 'speech-02-hd',
  /** 单次请求超时（毫秒），超时即触发降级 */
  requestTimeoutMs: 20_000,
  maxRetries: 1,
} as const;

/** 文本生成的硬上限，用于成本与延迟控制 */
export const TEXT_LIMITS = {
  maxTokens: 1024,
  temperature: 0.9,
  topP: 0.95,
} as const;

/** 语音合成参数合法范围（T2A v2 协议） */
export const VOICE_RANGES = {
  speed: [0.5, 2.0],
  vol: [0.1, 10.0],
  pitch: [-12, 12],
} as const;

/** 评测阈值：低于该值的维度视为不达标，用于报告结论 */
export const EVAL_THRESHOLDS = {
  personaConsistency: 0.72,
  emotionAccuracy: 0.7,
  latencyP95Ms: 2_500,
  overallPass: 0.75,
} as const;

/** 确定性 mock 的固定种子（离线降级必须逐字节可复现） */
export const MOCK_SEED = 20_261_007 as const;

/**
 * 对外公共入口（barrel）。
 * 只做 re-export，不承载逻辑；集成测试从这里验证整条链路可用。
 */

export * from './core/constants.js';
export * from './core/errors.js';
export * from './core/config.js';
export * from './core/deterministic.js';
export * from './core/types.js';
export type {
  MiniMaxClientLike,
  MiniMaxClientOptions,
  DramaEngineLike,
  EngineOptions,
  DialogueRequest,
  DialogueResponse,
  RubricDimension,
  EvalReport,
  EvalCaseResult,
  PersonaRegistry,
  ServerHandle,
  ServerOptions,
} from './core/contracts.js';
export { SCENE_PHASE_ORDER } from './core/contracts.js';

export * from './personas/index.js';
export * from './minimax/index.js';
export * from './engine/index.js';
export * from './eval/index.js';

/**
 * 人格注册表：加载三个人格，提供固定顺序的只读列表与按 id 查询。
 */
import { ConfigError } from '../core/errors.js';
import type { Persona } from '../core/types.js';
import type { PersonaRegistry } from '../core/contracts.js';
import { ShenYan } from './shen-yan.js';
import { LinXiaoman } from './lin-xiaoman.js';
import { HeJinglan } from './he-jinglan.js';

/** 固定加载顺序：shen-yan → lin-xiaoman → he-jinglan（稳定引用，供注册表与查询共用） */
const ALL_PERSONAS: readonly Persona[] = Object.freeze([ShenYan, LinXiaoman, HeJinglan]);

export function loadAllPersonas(): readonly Persona[] {
  return ALL_PERSONAS;
}

/** 默认人格：沈砚 */
export function defaultPersona(): Persona {
  return ShenYan;
}

const BY_ID: Record<string, Persona> = {};
for (const persona of ALL_PERSONAS) {
  BY_ID[persona.id] = persona;
}

/** 人格注册表实现：byId 未知 id 抛 ConfigError */
export const personaRegistry: PersonaRegistry = Object.freeze({
  all: ALL_PERSONAS,
  byId(id: string): Persona {
    const found: Persona | undefined = BY_ID[id];
    if (!found) throw new ConfigError(`未知的人格 id：「${id}」`);
    return found;
  },
  ids(): readonly string[] {
    return ALL_PERSONAS.map((persona) => persona.id);
  },
});

export { ShenYan, LinXiaoman, HeJinglan };
import type { HarnessDriver } from "../core/contract";
import { SkyEngine, type SkyEngineOptions } from "./sky-engine";

/**
 * 评测 HarnessDriver 工厂：包裹 SkyEngine 为固定步长接口。
 * 不启动内部 RAF——eval harness 逐帧 advance(dt)，同 dt 序列 ⇒ 同 sample()。
 * mount 尺寸为 0（离屏/未挂载）时 SkyEngine 内部 clamp 到 ≥1，不抛异常。
 */
export function createThreeDriver(mount: HTMLElement, opts?: SkyEngineOptions): HarnessDriver {
  const engine = new SkyEngine(mount, opts);
  return {
    renderer: engine,
    advance: (dt: number) => engine.advance(dt),
    sample: () => engine.sample(),
    dispose: () => engine.dispose(),
  };
}
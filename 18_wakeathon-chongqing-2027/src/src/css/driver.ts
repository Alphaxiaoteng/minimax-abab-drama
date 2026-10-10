/**
 * CSS/Canvas 阵营的评测/驱动适配层。
 *
 * 与 `visual/driver.ts` 同族签名：评测引擎对两个阵营一视同仁。
 */
import type { HarnessDriver } from "../core/contract";
import { CssRenderer } from "./renderer";

export function createCssDriver(mount: HTMLElement): HarnessDriver {
  const renderer = new CssRenderer(mount);
  return {
    renderer,
    advance: (dt: number) => renderer.step(dt),
    sample: () => renderer.metrics(),
    dispose: () => renderer.dispose(),
  };
}

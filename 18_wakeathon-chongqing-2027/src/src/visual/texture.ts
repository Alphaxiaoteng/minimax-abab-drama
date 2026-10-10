import * as THREE from "three";

const cache = new Map<string, THREE.Texture>();

function canvasTexture(name: string, size: number, draw: (ctx: CanvasRenderingContext2D) => void): THREE.Texture {
  const hit = cache.get(name);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d context unavailable");
  draw(ctx);
  const tex = new THREE.CanvasTexture(canvas);
  cache.set(name, tex);
  return tex;
}

/** 柔和圆形粒子贴图（雾、窗光、烟花、无人机、蒸汽共用） */
export function softDotTexture(): THREE.Texture {
  return canvasTexture("soft-dot", 128, (ctx) => {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.4, "rgba(255,255,255,0.6)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  });
}

/** 彩纸片贴图：圆角小方片 */
export function confettiTexture(): THREE.Texture {
  return canvasTexture("confetti", 32, (ctx) => {
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.roundRect(4, 4, 24, 24, 6);
    ctx.fill();
  });
}

/** 引擎 dispose 时统一释放模块级贴图缓存 */
export function disposeTextures(): void {
  cache.forEach((t) => t.dispose());
  cache.clear();
}
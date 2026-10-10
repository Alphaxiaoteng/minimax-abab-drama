import * as THREE from "three";

/** 霓虹调色板：青 / 粉 / 琥珀 / 紫 / 薄荷（全项目唯一颜色事实来源） */
export const NEON = [0x00e5ff, 0xff2079, 0xffb300, 0x7c4dff, 0x00ffa3] as const;

/** 夜景基调与日出迁移端点 */
export const NIGHT_BG = new THREE.Color(0x070b16);
export const DAWN_BG = new THREE.Color(0x3b2150);
export const NIGHT_FOG = new THREE.Color(0x101a30);
export const DAWN_FOG = new THREE.Color(0x6f4a7d);
export const NIGHT_SUN = new THREE.Color(0x8fb4ff);
export const DAWN_SUN = new THREE.Color(0xffb36b);
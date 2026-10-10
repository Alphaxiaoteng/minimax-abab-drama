import * as THREE from "three";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";

/**
 * 屏幕撕裂 + 短促 RGB 分离。strength 由能量场驱动；
 * 撕裂相位由外部时间 setTime(t) 推进，pass 自身无内部时钟。
 */
export function createGlitchPass(): {
  pass: ShaderPass;
  setStrength: (s: number) => void;
  setTime: (t: number) => void;
} {
  const material = new THREE.ShaderMaterial({
    uniforms: {
      tDiffuse: { value: null as THREE.Texture | null },
      strength: { value: 0 },
      uTime: { value: 0 },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D tDiffuse;
      uniform float strength;
      uniform float uTime;
      varying vec2 vUv;

      float hash(float n) { return fract(sin(n) * 43758.5453123); }

      void main() {
        vec2 uv = vUv;
        // 水平位移条带：按行量化撕裂相位
        float band = floor(uv.y * 24.0);
        float jitter = hash(band + floor(uTime * 24.0));
        float tear = step(0.72, jitter) * strength;
        uv.x += (jitter - 0.5) * tear * 0.12;

        float shift = strength * 0.02;
        vec4 col;
        col.r = texture2D(tDiffuse, uv + vec2(shift, 0.0)).r;
        col.g = texture2D(tDiffuse, uv).g;
        col.b = texture2D(tDiffuse, uv - vec2(shift, 0.0)).b;
        col.a = texture2D(tDiffuse, uv).a;
        gl_FragColor = col;
      }
    `,
  });
  const pass = new ShaderPass(material);
  return {
    pass,
    setStrength: (s: number) => {
      material.uniforms.strength.value = s;
    },
    setTime: (t: number) => {
      material.uniforms.uTime.value = t;
    },
  };
}
import { useEffect, useRef, useCallback } from 'react';

// The vertex shader simply creates a fullscreen quad
const VERTEX_SHADER = `
attribute vec2 a_position;
varying vec2 vUv;
void main() {
  vUv = 0.5 * (a_position + 1.0);
  vUv.y = 1.0 - vUv.y; // WebGL textures are Y-flipped natively
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

// The fragment shader base template provides the gl-transitions spec
const FRAGMENT_BASE = `
precision highp float;
varying vec2 vUv;
uniform sampler2D texFrom;
uniform sampler2D texTo;
uniform float progress;

vec4 getFromColor(vec2 uv) { return texture2D(texFrom, uv); }
vec4 getToColor(vec2 uv) { return texture2D(texTo, uv); }

// --- TRANSITION CODE INJECTED HERE ---
__TRANSITION_CODE__
// -------------------------------------

void main() {
  gl_FragColor = transition(vUv);
}
`;

// Curated dictionary of raw gl-transitions 
export const SHADERS: Record<string, string> = {
  "glsl-directionalwarp": `
    vec4 transition (vec2 uv) {
      vec2 p = uv + progress * sign(vec2(-1.0, 1.0));
      vec2 f = fract(p);
      return mix(getToColor(f), getFromColor(f), step(0.0, p.y) * step(p.y, 1.0) * step(0.0, p.x) * step(p.x, 1.0));
    }
  `,
  "glsl-dreamy": `
    vec2 offset(float p, float x, float theta) {
      float phase = p*p + p + theta;
      float shifty = 0.03*p*cos(10.0*(p+x));
      return vec2(0.0, shifty);
    }
    vec4 transition(vec2 p) {
      return mix(getFromColor(p + offset(progress, p.x, 0.0)), getToColor(p + offset(1.0-progress, p.x, 3.14)), progress);
    }
  `,
  "glsl-pixelize": `
    vec4 transition(vec2 uv) {
      float d = min(progress, 1.0 - progress);
      float dist = ceil(d * 50.0) / 50.0;
      vec2 sqSize = 2.0 * dist / vec2(20.0);
      vec2 p = dist > 0.0 ? (floor(uv / sqSize) + 0.5) * sqSize : uv;
      return mix(getFromColor(p), getToColor(p), progress);
    }
  `,
  "glsl-multiply_blend": `
    vec4 transition(vec2 uv) {
      vec4 fc = getFromColor(uv);
      vec4 tc = getToColor(uv);
      vec4 blended = fc * tc;
      return mix(mix(fc, blended, progress * 2.0), mix(blended, tc, (progress - 0.5) * 2.0), step(0.5, progress));
    }
  `,
  "glsl-crosswarp": `
    vec4 transition(vec2 p) {
      float x = smoothstep(0.0, 1.0, (progress*2.0+p.x-1.0));
      return mix(getFromColor((p-0.5)*(1.0-x)+0.5), getToColor((p-0.5)*x+0.5), x);
    }
  `,
  "glsl-burn": `
    vec4 transition(vec2 uv) {
      return mix(getFromColor(uv) + getToColor(uv)*progress, getToColor(uv) + getFromColor(uv)*(1.0-progress), progress);
    }
  `
};

function compileShader(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("WebGL Compilation Error:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export function useGLTransition(width: number, height: number, transitionName?: string) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const glRef = useRef<WebGLRenderingContext | null>(null);
  const programRef = useRef<WebGLProgram | null>(null);
  const texturesRef = useRef<{ from: WebGLTexture | null; to: WebGLTexture | null }>({ from: null, to: null });
  const locRef = useRef<{ progress: WebGLUniformLocation | null }>({ progress: null });

  // Initialize WebGL context and compile the selected shader
  useEffect(() => {
    if (!canvasRef.current) canvasRef.current = document.createElement("canvas");
    const canvas = canvasRef.current;
    canvas.width = width;
    canvas.height = height;

    const gl = canvas.getContext("webgl");
    if (!gl) return;
    glRef.current = gl;

    if (!transitionName || !SHADERS[transitionName]) return;

    const fsSource = FRAGMENT_BASE.replace("__TRANSITION_CODE__", SHADERS[transitionName]);
    const vertexShader = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, fsSource);

    if (!vertexShader || !fragmentShader) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    programRef.current = program;
    gl.useProgram(program);

    // Setup full-screen quad
    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1,  1, -1, -1,  1,  -1,  1,  1, -1,  1,  1]), gl.STATIC_DRAW);

    const positionLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    // Setup Textures
    const setupTexture = (unit: number, uniformName: string) => {
      const tex = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.uniform1i(gl.getUniformLocation(program, uniformName), unit);
      return tex;
    };

    texturesRef.current = { from: setupTexture(0, "texFrom"), to: setupTexture(1, "texTo") };
    locRef.current.progress = gl.getUniformLocation(program, "progress");

  }, [width, height, transitionName]);

  // Render loop function exposed to components
  const drawGL = useCallback((fromMedia: any, toMedia: any, progress: number) => {
    const gl = glRef.current;
    const program = programRef.current;
    if (!gl || !program) return;

    gl.useProgram(program);

    try {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texturesRef.current.from);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, fromMedia);

      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, texturesRef.current.to);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, toMedia);

      gl.uniform1f(locRef.current.progress, progress);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    } catch (e) {
      // Catch errors if video elements aren't fully loaded yet
    }
  }, []);

  return { glCanvas: canvasRef.current, drawGL };
}
// v3.5.1「流光」画布（= App ui/sky.dart SkyLayer + shaders/sky.frag）：整个应用一块 WebGL1 画布，长边约 480 像素、CSS 拉伸铺满视口（柔光本身很糊，低分辨率看不出来）。
// 片元着色器的“流光核心”段与 App sky.frag 逐字相同（外壳换成 WebGL1）；只跟时间有关的量（5 团的中心 / 矩阵 / 此刻颜色）每帧在这里算一次（lib/sky.ts skyBlobAt / skyHue）。
// 节奏：rAF 节流到约 30 帧（= App Sky.frame 33ms）。停帧：页面隐藏、<html data-sky-covered>（整屏浮层盖住）、<html data-solid>（减少透明度，CSS 换实色）；
// 减少动态：只画一帧静止（t = 0，颜色变时重画）。换颜色（每分钟 / 切主题）400ms 线性插值过去。WebGL 不可用或上下文丢失 → 藏起画布，露出 .sky 的 CSS 竖向渐变（--sky-top / --sky-bottom）。
// 顶部渐隐条里的副本（ui/Sky.tsx <Sky copy />）是 2D 画布，主画布每画一帧就 drawImage 过去。
import { SKY_BLOBS, SKY_HUE_STEP, listenSkyColors, lerpHex, rgb01, skyBlobAt, skyHue, SKY_PARTS, type SkyColors } from "./sky";

const LONG_SIDE = 480;
const FRAME_MS = 33;
const RECOLOR_MS = 400;

const VERT = `attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG = `precision highp float;
uniform vec2 uScreen;    // 画布大小（画布像素）
uniform vec3 uTop;
uniform vec3 uBottom;
uniform vec2 uO0;
uniform vec4 uM0;
uniform vec4 uC0;
uniform vec2 uO1;
uniform vec4 uM1;
uniform vec4 uC1;
uniform vec2 uO2;
uniform vec4 uM2;
uniform vec4 uC2;
uniform vec2 uO3;
uniform vec4 uM3;
uniform vec4 uC3;
uniform vec2 uO4;
uniform vec4 uM4;
uniform vec4 uC4;

__CORE__

void main() {
  vec2 px = vec2(gl_FragCoord.x, uScreen.y - gl_FragCoord.y); // 左上为原点，= Flutter
  vec2 uv = px / uScreen;
  gl_FragColor = vec4(skyDither(skyColor(uv, uScreen.x / uScreen.y), px), 1.0);
}
`;

type Gl = { gl: WebGLRenderingContext; prog: WebGLProgram; u: Record<string, WebGLUniformLocation | null> };

let canvas: HTMLCanvasElement | null = null;
let ctx: Gl | null = null;
let lost = false;
const copies = new Set<HTMLCanvasElement>();

let from: SkyColors | null = null, to: SkyColors | null = null, since = 0;
let raf = 0, last = -Infinity;
const reduce = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;

function compile(gl: WebGLRenderingContext): Gl | null {
  const sh = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.warn("sky shader:", gl.getShaderInfoLog(s)); return null; }
    return s;
  };
  const vs = sh(gl.VERTEX_SHADER, VERT), fs = sh(gl.FRAGMENT_SHADER, FRAG.replace("__CORE__", CORE));
  if (!vs || !fs) return null;
  const prog = gl.createProgram()!;
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.bindAttribLocation(prog, 0, "aPos");
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn("sky program:", gl.getProgramInfoLog(prog)); return null; }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW); // 一个盖住全屏的三角形
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const u: Gl["u"] = {};
  for (const n of ["uScreen", "uTop", "uBottom"]) u[n] = gl.getUniformLocation(prog, n);
  for (let i = 0; i < 5; i++) for (const k of ["O", "M", "C"]) u[`u${k}${i}`] = gl.getUniformLocation(prog, `u${k}${i}`);
  return { gl, prog, u };
}

function size() {
  if (!canvas) return;
  const w = window.innerWidth, h = window.innerHeight, s = LONG_SIDE / Math.max(w, h, 1);
  const cw = Math.max(1, Math.round(w * s)), ch = Math.max(1, Math.round(h * s));
  if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
  for (const c of copies) if (c.width !== cw || c.height !== ch) { c.width = cw; c.height = ch; }
}

/** 此刻（含 400ms 换色插值）的七个颜色。 */
function colorsAt(now: number): SkyColors | null {
  if (!to) return null;
  if (!from) return to;
  const k = Math.min(1, (now - since) / RECOLOR_MS);
  if (k >= 1) { from = null; return to; }
  return Object.fromEntries(SKY_PARTS.map((p) => [p, lerpHex(from![p], to![p], k)])) as SkyColors;
}

function draw(now: number) {
  const c = colorsAt(now);
  if (!canvas || !ctx || lost || !c) return;
  const { gl, u } = ctx;
  const w = canvas.width, h = canvas.height, aspect = w / h;
  const t = reduce?.matches ? 0 : now / 1000;
  gl.viewport(0, 0, w, h);
  gl.uniform2f(u.uScreen, w, h);
  gl.uniform3fv(u.uTop, rgb01(c.top));
  gl.uniform3fv(u.uBottom, rgb01(c.bottom));
  SKY_BLOBS.forEach((b, i) => {
    const at = skyBlobAt(b, t, aspect);
    gl.uniform2f(u[`uO${i}`], at.x, at.y);
    // M = diag(kx, ky) · R(θ)，按行（= App ui/sky.dart）
    gl.uniform4f(u[`uM${i}`], at.kx * at.cos, at.kx * at.sin, -at.ky * at.sin, at.ky * at.cos);
    const [r, g, bl] = skyHue(c, t / SKY_HUE_STEP + b[12]);
    gl.uniform4f(u[`uC${i}`], r, g, bl, b[11]);
  });
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  for (const cp of copies) drawCopy(cp);
}

function drawCopy(cp: HTMLCanvasElement) {
  if (!canvas || lost) return;
  const g = cp.getContext("2d");
  if (!g) return;
  if (cp.width !== canvas.width || cp.height !== canvas.height) { cp.width = canvas.width; cp.height = canvas.height; }
  g.drawImage(canvas, 0, 0);
}

const root = () => document.documentElement;
const paused = () => document.hidden || "skyCovered" in root().dataset || "solid" in root().dataset;
const animating = () => !paused() && !reduce?.matches;

function loop(now: number) {
  raf = 0;
  if (paused()) return;
  // 减少动态：只在换色插值期间继续画，插值完就停（静止一帧）
  if (!reduce?.matches || from) raf = requestAnimationFrame(loop);
  if (now - last < FRAME_MS - 2) return;
  last = now;
  draw(now);
}

/** 状态变了（可见性 / 覆盖 / 实色 / 减少动态 / 新颜色）：该动就起 rAF，该停就停（静止时补画一帧）。 */
function kick() {
  if (!canvas) return;
  if (paused()) { cancelAnimationFrame(raf); raf = 0; return; }
  if (animating() || from) { last = -Infinity; if (!raf) raf = requestAnimationFrame(loop); }
  else draw(performance.now());
}

function setLost(v: boolean) {
  lost = v;
  if (canvas) canvas.hidden = v;
  for (const c of copies) c.hidden = v;
}

/** ui/Sky.tsx 主壁纸挂载时调；返回卸载函数。 */
export function mountSkyGl(el: HTMLCanvasElement): () => void {
  canvas = el;
  const gl = el.getContext("webgl", { alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: true, powerPreference: "low-power" }) as WebGLRenderingContext | null;
  ctx = gl ? compile(gl) : null;
  setLost(!ctx);
  const onLost = (e: Event) => { e.preventDefault(); setLost(true); cancelAnimationFrame(raf); raf = 0; };
  const onRestored = () => { ctx = compile(el.getContext("webgl") as WebGLRenderingContext); setLost(!ctx); kick(); };
  el.addEventListener("webglcontextlost", onLost);
  el.addEventListener("webglcontextrestored", onRestored);
  const onResize = () => { size(); kick(); };
  size();
  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", kick);
  reduce?.addEventListener("change", kick);
  const mo = new MutationObserver(kick);
  mo.observe(root(), { attributes: true, attributeFilter: ["data-sky-covered", "data-solid"] });
  listenSkyColors((c) => {
    const now = performance.now();
    if (to) { from = colorsAt(now); since = now; }
    to = c;
    if (from && SKY_PARTS.every((p) => from![p] === c[p])) from = null;
    kick();
  });
  kick();
  return () => {
    cancelAnimationFrame(raf); raf = 0;
    el.removeEventListener("webglcontextlost", onLost);
    el.removeEventListener("webglcontextrestored", onRestored);
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", kick);
    reduce?.removeEventListener("change", kick);
    mo.disconnect();
    listenSkyColors(() => {});
    if (canvas === el) { canvas = null; ctx = null; }
  };
}

/** 渐隐条里的副本画布（2D）：注册后主画布每画一帧就拷一份；返回注销函数。 */
export function addSkyCopy(el: HTMLCanvasElement): () => void {
  copies.add(el);
  el.hidden = lost || !ctx;
  size();
  drawCopy(el);
  return () => { copies.delete(el); };
}

// ---- 与 App shaders/sky.frag 逐字相同的一段（只改这里时两边一起改）----
const CORE = `// ---- 流光核心 BEGIN（与网页 frontend/src/lib/skyGl.ts 里同名段落逐字相同，frontend scripts/check-contrast.mjs 查）----
// 一团柔光：移到中心后乘 2×2 矩阵 M（= 两条轴的缩放 × 旋转，Dart / TS 每帧算好），q = |M·d|²，高斯 exp(-q) × 强度
vec3 skyBlob(vec3 col, vec2 p, vec2 o, vec4 m, vec4 c) {
  vec2 d = p - o;
  vec2 e = vec2(dot(m.xy, d), dot(m.zw, d));
  return mix(col, c.rgb, exp(-dot(e, e)) * c.a);
}

vec3 skyColor(vec2 uv, float aspect) {
  vec2 p = vec2(uv.x * aspect, uv.y);
  vec3 col = mix(uTop, uBottom, smoothstep(0.0, 1.0, pow(clamp(uv.y, 0.0, 1.0), 0.75)));
  col = skyBlob(col, p, uO0, uM0, uC0);
  col = skyBlob(col, p, uO1, uM1, uC1);
  col = skyBlob(col, p, uO2, uM2, uC2);
  col = skyBlob(col, p, uO3, uM3, uC3);
  col = skyBlob(col, p, uO4, uM4, uC4);
  return col;
}

// 抖动：±0.5/255，消掉大面积柔和渐变的色带。用 interleaved gradient noise（Jimenez 2014，公开公式）：
// 只有乘加和 fract，比原来的 sin 哈希便宜，噪声分布也更均匀
vec3 skyDither(vec3 col, vec2 px) {
  float n = fract(52.9829189 * fract(dot(px, vec2(0.06711056, 0.00583715))));
  return col + (n - 0.5) / 255.0;
}
// ---- 流光核心 END ----
`;

// v3.3「流光」壁纸的钟点与柔光（= App ui/motion.dart SkyClock + theme/tokens.dart SkyTable.at / Sky.keyframes / Sky.blobs / SkyPhase.hue）。
// 色表只在 styles/tokens.css（--sky-<时段>-<部位>，浅 / 深各一套）；这里按本地钟点在相邻两个关键帧之间线性插值（= Color.lerp 逐通道）。
// v3.5.1：柔光改成五团、漂移 + 旋转 + 伸缩、颜色在五个色相间轮转，画在一块 WebGL 画布上（lib/skyGl.ts，与 App 同一段着色器）；
// 这里每分钟把此刻的七个颜色交给它，底色 top / bottom 另写到 <html> 的 --sky-top / --sky-bottom（画布出来前 / 不支持 WebGL 时的竖向渐变）。
// 节奏：每分钟一次（= Sky.recolor），页面隐藏时停、回来立刻重算；切浅 / 深色时重算。
// 上半是纯函数（tests/sky.test.ts 直接用 node 跑），下半才碰 DOM。

export type SkyPhaseName = "night" | "dawn" | "day" | "dusk";
export const SKY_PARTS = ["top", "bottom", "a", "b", "c", "d", "e"] as const;
export const SKY_HUES = ["a", "b", "c", "d", "e"] as const;
export type SkyPart = (typeof SKY_PARTS)[number];
export type SkyColors = Record<SkyPart, string>;
export type SkyTable = Record<SkyPhaseName, SkyColors>;

/** 一天里的关键帧（钟点, 时段），之间线性过渡（= App Sky.keyframes）。 */
export const SKY_KEYFRAMES: readonly (readonly [number, SkyPhaseName])[] = [
  [0, "night"], [4.5, "night"], [6, "dawn"], [8, "day"], [16.5, "day"], [18.5, "dusk"], [20.5, "night"], [24, "night"],
];
export const SKY_PHASES: readonly SkyPhaseName[] = ["night", "dawn", "day", "dusk"];
export const SKY_RECOLOR_MS = 60_000;

/** 五团柔光（= App Sky.blobs，check-contrast.mjs 查同值）：[cx, cy, ax, ay, tx, ty, px, py, r, tr, ts, mix, hue]——
 *  中心（屏宽 / 屏高的比例）、漂移振幅、漂移周期（秒）、起始相位、半径（屏高比例）、转一圈（秒，负 = 逆时针）、伸缩周期（秒）、强度、色相起点。 */
export const SKY_BLOBS: readonly (readonly number[])[] = [
  [0.20, 0.18, 0.24, 0.12, 23, 31, 0.0, 1.3, 0.30, 71, 29, 0.78, 0], // A 左上
  [0.82, 0.36, 0.22, 0.16, 29, 19, 2.1, 0.4, 0.27, -83, 37, 0.72, 1], // B 右中上
  [0.28, 0.60, 0.26, 0.14, 41, 27, 4.0, 2.6, 0.28, 97, 43, 0.70, 4], // C 左中下
  [0.74, 0.78, 0.22, 0.14, 37, 21, 1.2, 5.1, 0.30, -61, 31, 0.70, 2], // D 右下
  [0.48, 0.98, 0.30, 0.08, 43, 33, 3.3, 0.9, 0.32, 89, 41, 0.62, 3], // E 底部
];
/** 每团柔光从一个色相过渡到下一个的秒数（= App Sky.hueStep）；形变幅度（= Sky.stretch）。 */
export const SKY_HUE_STEP = 24;
export const SKY_STRETCH = 0.3;

/** t 秒时一团柔光的样子（= App SkyBlob.at，两端同一组测试向量）：中心（屏高为单位，x 已乘 aspect）、旋转 cos / sin、两轴缩放（含半径与伸缩）。 */
export function skyBlobAt(b: readonly number[], t: number, aspect: number) {
  const [cx, cy, ax, ay, tx, ty, px, py, r, tr, ts] = b;
  const tau = 2 * Math.PI, ang = (tau * t) / tr, s = 1 + SKY_STRETCH * Math.sin((tau * t) / ts);
  return {
    x: (cx + ax * Math.sin((tau * t) / tx + px)) * aspect,
    y: cy + ay * Math.sin((tau * t) / ty + py),
    cos: Math.cos(ang), sin: Math.sin(ang),
    kx: 1 / (s * r), ky: s / r,
  };
}

const hex2 = (n: number) => Math.round(Math.min(255, Math.max(0, n))).toString(16).padStart(2, "0");

/** #rrggbb 逐通道线性插值（= Flutter Color.lerp，sRGB 空间）。 */
export function lerpHex(a: string, b: string, t: number): string {
  const ch = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  return "#" + [0, 1, 2].map((i) => hex2(ch(a, i) + (ch(b, i) - ch(a, i)) * t)).join("");
}

/** 钟点（0…24，带小数）→ 这一刻的五个颜色（= App SkyTable.at）。 */
export function skyAt(table: SkyTable, hour: number): SkyColors {
  const h = ((hour % 24) + 24) % 24;
  for (let i = 0; i < SKY_KEYFRAMES.length - 1; i++) {
    const [h0, a] = SKY_KEYFRAMES[i], [h1, b] = SKY_KEYFRAMES[i + 1];
    if (h <= h1) {
      if (a === b || h1 === h0) return { ...table[a] };
      const t = (h - h0) / (h1 - h0);
      return Object.fromEntries(SKY_PARTS.map((p) => [p, lerpHex(table[a][p], table[b][p], t)])) as SkyColors;
    }
  }
  return { ...table[SKY_KEYFRAMES[SKY_KEYFRAMES.length - 1][1]] };
}

/** 色相轮转（= App SkyPhase.hue）：k = 0…5 循环（0 = a、1 = b …），相邻两色之间 smoothstep 过渡。返回 0…1 的 [r, g, b]。 */
export function skyHue(c: SkyColors, k: number): [number, number, number] {
  const n = SKY_HUES.length, m = ((k % n) + n) % n, i = Math.floor(m), f0 = m - i, f = f0 * f0 * (3 - 2 * f0);
  const a = rgb01(c[SKY_HUES[i]]), b = rgb01(c[SKY_HUES[(i + 1) % n]]);
  return [0, 1, 2].map((j) => a[j] + (b[j] - a[j]) * f) as [number, number, number];
}

/** #rrggbb → 0…1 的 [r, g, b]。 */
export const rgb01 = (h: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as [number, number, number];

export const hourOf = (d: Date) => d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;

// ---- DOM ----

/** 从 tokens.css 读当前主题（浅 / 深）的整张色表。 */
function readTable(root: HTMLElement): SkyTable {
  const cs = getComputedStyle(root);
  const t = {} as SkyTable;
  for (const ph of SKY_PHASES) {
    t[ph] = {} as SkyColors;
    for (const p of SKY_PARTS) t[ph][p] = cs.getPropertyValue(`--sky-${ph}-${p}`).trim();
  }
  return t;
}

/** 此刻的七个颜色交给谁（lib/skyGl.ts 注册；没有 WebGL 时没人听，底色渐变照样在）。 */
let onColors: ((c: SkyColors) => void) | null = null;
let current: SkyColors | null = null;
export function listenSkyColors(fn: (c: SkyColors) => void) {
  onColors = fn;
  if (current) fn(current);
}

function paint() {
  const root = document.documentElement;
  const c = skyAt(readTable(root), hourOf(new Date()));
  root.style.setProperty("--sky-top", c.top);
  root.style.setProperty("--sky-bottom", c.bottom);
  current = c;
  onColors?.(c);
}

/** 整屏不透明浮层（云浏览器接管、看大图）盖住壁纸时的计数（v3.3 B4，= App ui/sky.dart SkyCover）：
 *  计数 > 0 时 <html data-sky-covered>：lib/skyGl.ts 停掉画布的逐帧绘制，base.css 让每层 .sky content-visibility: hidden 跳过合成；
 *  撤销后画布直接画“此刻”（时间按 performance.now 走，没有跳变以外的状态）。返回撤销函数（只生效一次）。 */
let skyCovers = 0;
export function coverSky(root: { dataset: DOMStringMap } = document.documentElement): () => void {
  if (skyCovers++ === 0) root.dataset.skyCovered = "";
  let done = false;
  return () => {
    if (done) return;
    done = true;
    if (--skyCovers === 0) delete root.dataset.skyCovered;
  };
}

let started = false;

/** 启动时调一次（main.tsx，首帧前）：先上色，之后每到整分钟重算；页面隐藏时停。 */
export function initSky() {
  if (started) return;
  started = true;
  paint();
  let timer = 0;
  const schedule = () => {
    window.clearTimeout(timer);
    if (document.hidden) return;
    const now = new Date();
    timer = window.setTimeout(() => { paint(); schedule(); }, SKY_RECOLOR_MS - (now.getSeconds() * 1000 + now.getMilliseconds()) + 50);
  };
  schedule();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) paint(); schedule(); });
  // 切浅 / 深色（lib/theme.ts 写 data-theme）→ 换色表（画布那边 400ms 渐变过去，= base.css .theme-switching）
  new MutationObserver(() => paint()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

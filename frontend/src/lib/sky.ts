// v3.3「流光」壁纸的钟点（= App ui/motion.dart SkyClock + theme/tokens.dart SkyTable.at / Sky.keyframes）。
// 色表只在 styles/tokens.css（--sky-<时段>-<部位>，浅 / 深各一套）；这里按本地钟点在相邻两个关键帧之间线性插值（= Color.lerp 逐通道），
// 写到 <html> 的 --sky-top / --sky-bottom / --sky-a / --sky-b / --sky-c，画法在 styles/base.css .sky（ui/Sky.tsx）。
// 节奏：每分钟一次（= Sky.recolor），页面隐藏时停、回来立刻重算；切浅 / 深色时重算。柔光漂移是 CSS 动画（只动 transform），不经过这里。
// 上半是纯函数（tests/sky.test.ts 直接用 node 跑），下半才碰 DOM。

export type SkyPhaseName = "night" | "dawn" | "day" | "dusk";
export const SKY_PARTS = ["top", "bottom", "a", "b", "c"] as const;
export type SkyPart = (typeof SKY_PARTS)[number];
export type SkyColors = Record<SkyPart, string>;
export type SkyTable = Record<SkyPhaseName, SkyColors>;

/** 一天里的关键帧（钟点, 时段），之间线性过渡（= App Sky.keyframes）。 */
export const SKY_KEYFRAMES: readonly (readonly [number, SkyPhaseName])[] = [
  [0, "night"], [4.5, "night"], [6, "dawn"], [8, "day"], [16.5, "day"], [18.5, "dusk"], [20.5, "night"], [24, "night"],
];
export const SKY_PHASES: readonly SkyPhaseName[] = ["night", "dawn", "day", "dusk"];
export const SKY_RECOLOR_MS = 60_000;

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

function paint() {
  const root = document.documentElement;
  const c = skyAt(readTable(root), hourOf(new Date()));
  for (const p of SKY_PARTS) root.style.setProperty(`--sky-${p}`, c[p]);
}

/** 整屏不透明浮层（云浏览器接管、看大图）盖住壁纸时的计数（v3.3 B4，= App ui/sky.dart SkyCover）：
 *  计数 > 0 时 <html data-sky-covered>，base.css 让每层 .sky（含顶部渐隐条里的副本）content-visibility: hidden，跳过柔光渲染。
 *  不用 animation-play-state: paused：它会冻住本地时间、恢复时改写 startTime，渐隐条副本靠 startTime = 0 与全屏层对齐（syncSky）会错位；
 *  content-visibility 跳过期间 startTime 不动，恢复时按文档时间线直接到“此刻”的位置。返回撤销函数（只生效一次）。 */
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

/** 让一层壁纸里的漂移动画对齐到同一个时间原点：全屏那层和顶部渐隐条里的副本逐像素重合（ui/Sky.tsx 挂载时调）。 */
export function syncSky(el: Element) {
  for (const a of el.getAnimations({ subtree: true })) a.startTime = 0;
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
  // 切浅 / 深色（lib/theme.ts 写 data-theme）→ 换色表；关掉“减少透明度”（data-solid）→ 柔光重新出现，重新对齐副本
  new MutationObserver((list) => {
    if (list.some((m) => m.attributeName === "data-theme")) paint();
    if (list.some((m) => m.attributeName === "data-solid")) requestAnimationFrame(() => document.querySelectorAll(".sky").forEach(syncSky));
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-solid"] });
}

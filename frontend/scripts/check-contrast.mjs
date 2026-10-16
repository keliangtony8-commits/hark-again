// 网页端配色守门（npm run build 里跟着 check-arch 一起跑；= App test/a11y_test.dart 的「配色对比度」一组）。
// 为什么要有：网页没有测试框架，配色只能靠人看，而浅色警示色 #b86e00 当小字用只有 3.62:1 一直没人发现。
// 规则：
//   1. 对比度（WCAG 相对亮度）：正文/气泡字/按钮字/警示·出错·成功小字 ≥ 4.5；最次要信息（--text-3）≥ 3（token 里就这么写的）。
//   2. 两端同源：上面这些关键色，浅/深两套都必须和 App lib/theme/tokens.dart 同值（改了颜色忘了改另一边 = 失败）。
//      这条只读得到完整仓库时才查：网页镜像里只有 frontend/（构建上下文就是它），那时跳过并说一声——
//      对比度那半永远查，因为只需要 tokens.css。
//   3. v3.3 流光壁纸色表（--sky-<时段>-<部位>）：浅/深 × 4 时段 × 5 色都和 App SkyTable.light/dark 同值；
//      壁纸上真实出现的颜色（全天每 15 分钟按 lib/sky.ts 关键帧插值 × 底色 11 个高度按 Sky.ramp × 叠上三团柔光峰值 blobMix，
//      = App test/sky_test.dart 同一采样）：正文 --text、次要字 --text-2 ≥ 4.5，最次要字 --text-3 ≥ 3。
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));
const css = readFileSync(join(frontend, "src/styles/tokens.css"), "utf8");
const dartPath = process.env.TOKENS_DART ?? join(frontend, "../app/lib/theme/tokens.dart");
const dart = existsSync(dartPath) ? readFileSync(dartPath, "utf8") : null;

// 壁纸采样参数各有唯一出处：关键帧 = lib/sky.ts SKY_KEYFRAMES，柔光强度 = base.css .sky-a/b/c 的 --mix，
// 底色曲线 = base.css 文件头注释与 App Sky.rampPow（0.75，色标就是按它算的）。这里按文本读，Docker 里的 node 20 不能直接 import .ts。
const skyTs = readFileSync(join(frontend, "src/lib/sky.ts"), "utf8");
const baseCss = readFileSync(join(frontend, "src/styles/base.css"), "utf8");
const KEYFRAMES = [.../SKY_KEYFRAMES[^=]*=\s*\[([\s\S]*?)\];/.exec(skyTs)[1].matchAll(/\[([\d.]+),\s*"(\w+)"\]/g)].map(([, h, ph]) => [Number(h), ph]);
const BLOB_MIX = ["a", "b", "c"].map((k) => Number(new RegExp(`\\.sky-${k}\\s*\\{[^}]*--mix:\\s*([\\d.]+)`).exec(baseCss)[1]));
const RAMP_POW = 0.75;
if (KEYFRAMES.length < 2 || BLOB_MIX.some(Number.isNaN)) throw new Error("读不到 lib/sky.ts SKY_KEYFRAMES 或 base.css .sky-a/b/c --mix");

/** 取 tokens.css 里某个选择器块的所有 --变量。 */
const cssTheme = (selector) => {
  const m = new RegExp(`${selector.replace(/[[\]]/g, "\\$&")}\\s*\\{([\\s\\S]*?)\\}`).exec(css);
  if (!m) throw new Error(`tokens.css 里找不到 ${selector}`);
  const out = {};
  for (const [, k, v] of m[1].matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8})/g)) out[k] = v.toLowerCase();
  return out;
};

/** 取 tokens.dart 里 static const light/dark 的字段（Color(0xAARRGGBB) → #rrggbb）。 */
const dartTheme = (name) => {
  const m = new RegExp(`static const ${name} = Palette\\(([\\s\\S]*?)\\n  \\);`).exec(dart);
  if (!m) throw new Error(`tokens.dart 里找不到 ${name}`);
  const out = {};
  for (const [, k, hex] of m[1].matchAll(/(\w+): Color\(0x([0-9a-fA-F]{8})\)/g)) out[k] = `#${hex.slice(2).toLowerCase()}`;
  return out;
};

/** tokens.dart 里 static const light/dark = SkyTable(...) → { "night-top": "#rrggbb", … }（顺序 = SkyPhase(top, bottom, blobA, blobB, blobC)）。 */
const SKY_PARTS = ["top", "bottom", "a", "b", "c"];
const dartSky = (name) => {
  const m = new RegExp(`static const ${name} = SkyTable\\(([\\s\\S]*?)\\n  \\);`).exec(dart);
  if (!m) throw new Error(`tokens.dart 里找不到 SkyTable.${name}`);
  const out = {};
  for (const [, phase, body] of m[1].matchAll(/(\w+): SkyPhase\(([\s\S]*?)\)\),/g)) {
    [...body.matchAll(/Color\(0x([0-9a-fA-F]{8})/g)].forEach(([, hex], i) => { out[`${phase}-${SKY_PARTS[i]}`] = `#${hex.slice(2).toLowerCase()}`; });
  }
  return out;
};
const SKY_PHASES = ["night", "dawn", "day", "dusk"];

// 网页变量名 ↔ App 字段名（只列要守的这几对；别名 / 派生色不参与）
const SAME = {
  "user-bubble": "userBubble", "on-user-bubble": "onUserBubble",
  bg: "bg", surface: "surface", "surface-2": "surface2",
  text: "text", "text-2": "text2", "text-3": "text3",
  ink: "ink", "on-ink": "onInk", accent: "accent", "on-accent": "onAccent",
  danger: "danger", warning: "warning", success: "success",
};

// [前景, 背景, 下限]；名称只为报错好读
const PAIRS = [
  ["气泡字", "on-user-bubble", "user-bubble", 4.5],
  ["正文/底", "text", "bg", 4.5],
  ["正文/卡", "text", "surface", 4.5],
  ["正文/卡2", "text", "surface-2", 4.5],
  ["次要字/底", "text-2", "bg", 4.5],
  ["次要字/卡", "text-2", "surface", 4.5],
  ["主按钮", "on-ink", "ink", 4.5],
  ["强调", "on-accent", "accent", 4.5],
  ["出错字", "danger", "bg", 4.5],
  ["警示字", "warning", "bg", 4.5],
  ["警示字/卡", "warning", "surface", 4.5],
  ["成功字", "success", "bg", 4.5],
  ["最次要字/底", "text-3", "bg", 3],
  ["最次要字/卡", "text-3", "surface", 3],
];

/** 颜色一律用 0…1 的 [r, g, b]；hex 进来先转。 */
const rgb = (c) => (typeof c === "string" ? [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16) / 255) : c);
const lum = (c) => {
  const [r, g, b] = rgb(c).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};
const mix = (a, b, t) => rgb(a).map((v, i) => v + (rgb(b)[i] - v) * t);
const ramp = (y) => { const x = y ** RAMP_POW; return x * x * (3 - 2 * x); };

/** 壁纸上真实会出现的颜色：全天每 15 分钟 × 底色 11 个高度 × （底色本身 + 叠上每一团柔光的峰值）。 */
function* skySamples(sky) {
  for (let q = 0; q < 96; q++) {
    const h = q / 4;
    let ph;
    for (let i = 0; i < KEYFRAMES.length - 1; i++) {
      const [h0, a] = KEYFRAMES[i], [h1, b] = KEYFRAMES[i + 1];
      if (h <= h1) { const t = h1 === h0 ? 0 : (h - h0) / (h1 - h0); ph = SKY_PARTS.map((p) => mix(sky[`${a}-${p}`], sky[`${b}-${p}`], t)); break; }
    }
    for (let y = 0; y <= 10; y++) {
      const base = mix(ph[0], ph[1], ramp(y / 10));
      yield [`${h} 点 y=${y / 10} 底色`, base];
      for (let k = 0; k < 3; k++) yield [`${h} 点 y=${y / 10} 柔光${"abc"[k]}`, mix(base, ph[2 + k], BLOB_MIX[k])];
    }
  }
}
const SKY_TEXT = [["正文", "text", 4.5], ["次要字", "text-2", 4.5], ["最次要字", "text-3", 3]];

const bad = [];
const skyWorst = [];
for (const [themeName, selector, dartName] of [["浅色", ":root", "light"], ["深色", ':root[data-theme="dark"]', "dark"]]) {
  const web = cssTheme(selector);
  const app = dart ? dartTheme(dartName) : null;
  if (!app) {
    if (dartName === "light") console.log(`（这次没查两端同值：读不到 ${dartPath}——网页镜像里只有 frontend/，属正常）`);
  } else {
    for (const [webName, appName] of Object.entries(SAME)) {
      if (!web[webName] || !app[appName]) bad.push(`${themeName}：${webName} / ${appName} 有一边没有`);
      else if (web[webName] !== app[appName]) bad.push(`${themeName}：--${webName} ${web[webName]} ≠ App ${appName} ${app[appName]}`);
    }
  }
  const sky = Object.fromEntries(SKY_PHASES.flatMap((ph) => SKY_PARTS.map((p) => [`${ph}-${p}`, web[`sky-${ph}-${p}`]])));
  if (app) {
    const appSky = dartSky(dartName);
    for (const [k, v] of Object.entries(sky)) {
      if (!v || !appSky[k]) bad.push(`${themeName}：--sky-${k} / SkyTable.${dartName} 有一边没有`);
      else if (v !== appSky[k]) bad.push(`${themeName}：--sky-${k} ${v} ≠ App SkyTable.${dartName} ${appSky[k]}`);
    }
  }
  const missing = Object.keys(sky).filter((k) => !sky[k]);
  for (const k of missing) bad.push(`${themeName}：tokens.css 缺 --sky-${k}`);
  if (!missing.length) {
    for (const [what, fg, min] of SKY_TEXT) {
      let worst = Infinity, where = "";
      for (const [at, c] of skySamples(sky)) { const r = ratio(web[fg], c); if (r < worst) { worst = r; where = at; } }
      skyWorst.push(`${themeName}${what} ${worst.toFixed(2)}`);
      if (worst < min) bad.push(`${themeName} ${what}/壁纸 --${fg} 最差 ${worst.toFixed(2)}:1 @ ${where}（要 ≥${min}）`);
    }
  }
  for (const [what, fg, bg, min] of PAIRS) {
    const r = ratio(web[fg], web[bg]);
    if (r < min) bad.push(`${themeName} ${what} --${fg} on --${bg} = ${r.toFixed(2)}:1（要 ≥${min}）`);
  }
}

if (bad.length) {
  console.error("配色守门失败：\n" + bad.join("\n"));
  process.exit(1);
}
console.log(`配色守门通过（${PAIRS.length} 对 × 2 套主题 + 壁纸全天采样 × 2 套：${skyWorst.join("、")}${dart ? "；壁纸 " + SKY_PHASES.length * SKY_PARTS.length + " 色与 App tokens.dart 同值" : ""}）`);

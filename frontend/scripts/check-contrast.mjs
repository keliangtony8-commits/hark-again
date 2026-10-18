// 网页端配色守门（npm run build 里跟着 check-arch 一起跑；= App test/a11y_test.dart 的「配色对比度」一组）。
// 为什么要有：网页没有测试框架，配色只能靠人看，而浅色警示色 #b86e00 当小字用只有 3.62:1 一直没人发现。
// 规则：
//   1. 对比度（WCAG 相对亮度）：正文/气泡字/按钮字/警示·出错·成功小字 ≥ 4.5；最次要信息（--text-3）≥ 3（token 里就这么写的）。
//   2. 两端同源：上面这些关键色，浅/深两套都必须和 App lib/theme/tokens.dart 同值（改了颜色忘了改另一边 = 失败）。
//      这条只读得到完整仓库时才查：网页镜像里只有 frontend/（构建上下文就是它），那时跳过并说一声——
//      对比度那半永远查，因为只需要 tokens.css。
//   3. v3.3 流光壁纸色表（--sky-<时段>-<部位>）：浅/深 × 4 时段 × 7 色都和 App SkyTable.light/dark 同值；
//      壁纸上真实出现的颜色（全天每 15 分钟按 lib/sky.ts 关键帧插值 × 底色 11 个高度按 Sky.ramp × 叠上五团柔光峰值
//      （强度 = SKY_BLOBS 的 mix，颜色 = 五色轮转每 1/4 步采一次，含相邻两色的 smoothstep 过渡），
//      = App test/sky_test.dart 同一采样）：正文 --text、次要字 --text-2 ≥ 4.5，最次要字 --text-3 ≥ 3。
//   4. v3.5.1 卡片 --card 是半透明“假玻璃”（rgba，壁纸透色）：浅/深两套和 App Palette.card 同值（含透明度），
//      卡上的字按“--card 叠在上面每一处壁纸”算：--text / --text-2 / --warning / --danger ≥ 4.5，--text-3 ≥ 3。
//   5. v3.5.1 浮层玻璃 --glass（顶栏 / 输入胶囊 / 搜索框 / 圆钮）也是 rgba、明显透出壁纸（= Hark）：浅/深和 App Palette.glass 同值（含透明度），
//      浮层上的字（导航字 --text-2、占位符 --text-3、图标 / 输入字 --text）按浮层下面最差的三种情况算：直接是壁纸、卡叠壁纸、
//      卡叠壁纸再被墨色（--ink：主按钮 / 字，= 浅色黑、深色白）盖住一半（σ24 模糊后一颗 48px 高实心按钮中线 ≈ 一半）。--text / --text-2 ≥ 4.5，--text-3 ≥ 3。
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));
const css = readFileSync(join(frontend, "src/styles/tokens.css"), "utf8");
const dartPath = process.env.TOKENS_DART ?? join(frontend, "../app/lib/theme/tokens.dart");
const dart = existsSync(dartPath) ? readFileSync(dartPath, "utf8") : null;

// 壁纸采样参数各有唯一出处：关键帧 = lib/sky.ts SKY_KEYFRAMES，柔光强度 = lib/sky.ts SKY_BLOBS 每行倒数第二个数（mix），
// 底色曲线 = App Sky.rampPow / 着色器核心里的 pow(…, 0.75)。这里按文本读，Docker 里的 node 20 不能直接 import .ts。
// v3.5.1 另守两条两端同源：skyGl.ts 嵌入的「流光核心 BEGIN/END」段 = App shaders/sky.frag 同名段逐字相同；SKY_BLOBS = App Sky.blobs 同值。
const skyTs = readFileSync(join(frontend, "src/lib/sky.ts"), "utf8");
const skyGl = readFileSync(join(frontend, "src/lib/skyGl.ts"), "utf8");
const KEYFRAMES = [.../SKY_KEYFRAMES[^=]*=\s*\[([\s\S]*?)\];/.exec(skyTs)[1].matchAll(/\[([\d.]+),\s*"(\w+)"\]/g)].map(([, h, ph]) => [Number(h), ph]);
const tsBlobsBody = /SKY_BLOBS[^=]*=\s*\[([\s\S]*?)\n\];/.exec(skyTs)?.[1] ?? "";
const SKY_BLOBS = [...tsBlobsBody.matchAll(/^\s*\[([-\d., ]+)\],/gm)].map(([, row]) => row.split(",").map((v) => Number(v.trim())));
const BLOB_MIX = SKY_BLOBS.map((b) => b[11]);
const HUES = ["a", "b", "c", "d", "e"];
const RAMP_POW = 0.75;
if (KEYFRAMES.length < 2 || SKY_BLOBS.length !== 5 || SKY_BLOBS.some((b) => b.length !== 13 || b.some(Number.isNaN)))
  throw new Error("读不到 lib/sky.ts SKY_KEYFRAMES 或 SKY_BLOBS（要 5 行 × 13 个数）");
const CORE_RE = /\/\/ ---- 流光核心 BEGIN[\s\S]*?\/\/ ---- 流光核心 END ----/;
const webCore = CORE_RE.exec(skyGl)?.[0];
if (!webCore) throw new Error("lib/skyGl.ts 里找不到「流光核心 BEGIN/END」段");

/** 取 tokens.css 里某个选择器块的所有 --变量。 */
const cssTheme = (selector) => {
  const m = new RegExp(`${selector.replace(/[[\]]/g, "\\$&")}\\s*\\{([\\s\\S]*?)\\}`).exec(css);
  if (!m) throw new Error(`tokens.css 里找不到 ${selector}`);
  const out = {};
  for (const [, k, v] of m[1].matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8})/g)) out[k] = v.toLowerCase();
  return out;
};

/** 取 tokens.css 某个选择器块里 --<name>（--card / --glass）的 rgba(r, g, b, a) → { c: [r,g,b] 0…1, a, argb: "#aarrggbb" }。 */
const cssRgba = (selector, name) => {
  const m = new RegExp(`${selector.replace(/[[\]]/g, "\\$&")}\\s*\\{([\\s\\S]*?)\\}`).exec(css);
  const v = m && new RegExp(`--${name}:\\s*rgba\\(\\s*(\\d+),\\s*(\\d+),\\s*(\\d+),\\s*([\\d.]+)\\s*\\)`).exec(m[1]);
  if (!v) return null;
  const [r, g, b, a] = v.slice(1).map(Number);
  const hex = (n) => n.toString(16).padStart(2, "0");
  return { c: [r, g, b].map((x) => x / 255), a, argb: `#${hex(Math.round(a * 255))}${hex(r)}${hex(g)}${hex(b)}` };
};

/** 取 tokens.dart 里 static const light/dark 的字段（Color(0xAARRGGBB) → #rrggbb）。 */
const dartTheme = (name) => {
  const m = new RegExp(`static const ${name} = Palette\\(([\\s\\S]*?)\\n  \\);`).exec(dart);
  if (!m) throw new Error(`tokens.dart 里找不到 ${name}`);
  const out = {};
  for (const [, k, hex] of m[1].matchAll(/(\w+): Color\(0x([0-9a-fA-F]{8})\)/g)) out[k] = `#${hex.slice(2).toLowerCase()}`;
  return out;
};

/** tokens.dart 里 static const light/dark = SkyTable(...) → { "night-top": "#rrggbb", … }（顺序 = SkyPhase(top, bottom, a, b, c, d, e)）。 */
const SKY_PARTS = ["top", "bottom", "a", "b", "c", "d", "e"];
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

/** 五色轮转（= lib/sky.ts skyHue）：k 处于 a…e 循环里，相邻两色 smoothstep 过渡。 */
const hue = (ph, k) => {
  const m = ((k % 5) + 5) % 5, i = Math.floor(m), f0 = m - i;
  return mix(ph[2 + i], ph[2 + ((i + 1) % 5)], f0 * f0 * (3 - 2 * f0));
};
const MIXES = [...new Set(BLOB_MIX)];
/** 壁纸上真实会出现的颜色：全天每 15 分钟 × 底色 11 个高度 × （底色本身 + 叠上每种强度的柔光峰值 × 轮转里每 1/4 步的颜色）。 */
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
      for (const m of MIXES) for (let k = 0; k < 20; k++) yield [`${h} 点 y=${y / 10} 柔光 mix=${m} 色相 ${HUES[Math.floor(k / 4)]}+${(k % 4) / 4}`, mix(base, hue(ph, k / 4), m)];
    }
  }
}
const SKY_TEXT = [["正文", "text", 4.5], ["次要字", "text-2", 4.5], ["最次要字", "text-3", 3]];
const CARD_TEXT = [...SKY_TEXT, ["警示字", "warning", 4.5], ["出错字", "danger", 4.5]];
const GLASS_TEXT = SKY_TEXT;
/** App Palette.light/dark 的 card / glass：Color(0xAARRGGBB) → "#aarrggbb"（带透明度，两端逐字节同值）。 */
const dartArgb = (name, field) => {
  const m = new RegExp(`static const ${name} = Palette\\(([\\s\\S]*?)\\n  \\);`).exec(dart);
  const v = m && new RegExp(`\\b${field}: Color\\(0x([0-9a-fA-F]{8})\\)`).exec(m[1]);
  return v ? `#${v[1].toLowerCase()}` : null;
};

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
  const card = cssRgba(selector, "card");
  if (!card) bad.push(`${themeName}：tokens.css 缺 --card: rgba(…)`);
  else {
    if (app) {
      const appCard = dartArgb(dartName, "card");
      if (appCard !== card.argb) bad.push(`${themeName}：--card ${card.argb} ≠ App card ${appCard}`);
    }
    if (!missing.length) {
      for (const [what, fg, min] of CARD_TEXT) {
        let worst = Infinity, where = "";
        for (const [at, c] of skySamples(sky)) { const r = ratio(web[fg], mix(c, card.c, card.a)); if (r < worst) { worst = r; where = at; } }
        skyWorst.push(`${themeName}${what}/卡 ${worst.toFixed(2)}`);
        if (worst < min) bad.push(`${themeName} ${what}/卡（--card 叠壁纸）--${fg} 最差 ${worst.toFixed(2)}:1 @ ${where}（要 ≥${min}）`);
      }
    }
  }
  const glass = cssRgba(selector, "glass");
  if (!glass) bad.push(`${themeName}：tokens.css 缺 --glass: rgba(…)`);
  else {
    if (app) {
      const appGlass = dartArgb(dartName, "glass");
      if (appGlass !== glass.argb) bad.push(`${themeName}：--glass ${glass.argb} ≠ App glass ${appGlass}`);
    }
    if (!missing.length && card) {
      // 浮层下面最差的三种：壁纸 / 卡叠壁纸 / 卡叠壁纸再被墨色盖住一半（滚过主按钮、字）
      const unders = [["壁纸", (c) => c], ["卡", (c) => mix(c, card.c, card.a)], ["卡上墨色一半", (c) => mix(mix(c, card.c, card.a), web.ink, 0.5)]];
      for (const [what, fg, min] of GLASS_TEXT) {
        let worst = Infinity, where = "";
        for (const [on, under] of unders) {
          for (const [at, c] of skySamples(sky)) { const r = ratio(web[fg], mix(under(c), glass.c, glass.a)); if (r < worst) { worst = r; where = `${on} ${at}`; } }
        }
        skyWorst.push(`${themeName}${what}/浮层 ${worst.toFixed(2)}`);
        if (worst < min) bad.push(`${themeName} ${what}/浮层（--glass 叠壁纸 / 卡 / 卡上墨色）--${fg} 最差 ${worst.toFixed(2)}:1 @ ${where}（要 ≥${min}）`);
      }
    }
  }
  for (const [what, fg, bg, min] of PAIRS) {
    const r = ratio(web[fg], web[bg]);
    if (r < min) bad.push(`${themeName} ${what} --${fg} on --${bg} = ${r.toFixed(2)}:1（要 ≥${min}）`);
  }
}

// v3.5.1 两端同源：着色器核心段逐字相同、五团柔光参数同值（同样只在读得到完整仓库时查）
const fragPath = process.env.SKY_FRAG ?? join(frontend, "../app/shaders/sky.frag");
const frag = existsSync(fragPath) ? readFileSync(fragPath, "utf8") : null;
let coreSame = false, blobsSame = false;
if (frag) {
  const appCore = CORE_RE.exec(frag)?.[0];
  if (!appCore) bad.push(`${fragPath} 里找不到「流光核心 BEGIN/END」段`);
  else if (appCore !== webCore) {
    const a = webCore.split("\n"), b = appCore.split("\n");
    const i = a.findIndex((l, j) => l !== b[j]);
    bad.push(`流光核心不同：skyGl.ts 第 ${i + 1} 行「${a[i] ?? "（无）"}」≠ sky.frag「${b[i] ?? "（无）"}」`);
  } else coreSame = true;
}
if (dart) {
  const body = /static const blobs = \[([\s\S]*?)\n\s*\];/.exec(dart)?.[1] ?? "";
  const appBlobs = [...body.matchAll(/SkyBlob\(([-\d., ]+)\)/g)].map(([, row]) => row.split(",").map((v) => Number(v.trim())));
  if (appBlobs.length !== SKY_BLOBS.length) bad.push(`柔光团数：网页 SKY_BLOBS ${SKY_BLOBS.length} ≠ App Sky.blobs ${appBlobs.length}`);
  else {
    SKY_BLOBS.forEach((row, i) => {
      if (row.length !== appBlobs[i].length || row.some((v, j) => v !== appBlobs[i][j]))
        bad.push(`柔光 ${"ABCDE"[i]}：网页 [${row.join(", ")}] ≠ App SkyBlob(${appBlobs[i].join(", ")})`);
    });
    blobsSame = !bad.some((b) => b.startsWith("柔光 "));
  }
}

if (bad.length) {
  console.error("配色守门失败：\n" + bad.join("\n"));
  process.exit(1);
}
console.log(`配色守门通过（${PAIRS.length} 对 × 2 套主题 + 壁纸全天采样 × 2 套：${skyWorst.join("、")}${dart ? "；壁纸 " + SKY_PHASES.length * SKY_PARTS.length + " 色 + --card / --glass 与 App tokens.dart 同值" : ""}${blobsSame ? "；5 团柔光参数与 App Sky.blobs 同值" : ""}${coreSame ? "；着色器核心与 App sky.frag 逐字相同" : ""}）`);

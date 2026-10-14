// 网页端配色守门（npm run build 里跟着 check-arch 一起跑；= App test/a11y_test.dart 的「配色对比度」一组）。
// 为什么要有：网页没有测试框架，配色只能靠人看，而浅色警示色 #b86e00 当小字用只有 3.62:1 一直没人发现。
// 规则：
//   1. 对比度（WCAG 相对亮度）：正文/气泡字/按钮字/警示·出错·成功小字 ≥ 4.5；最次要信息（--text-3）≥ 3（token 里就这么写的）。
//   2. 两端同源：上面这些关键色，浅/深两套都必须和 App lib/theme/tokens.dart 同值（改了颜色忘了改另一边 = 失败）。
//      这条只读得到完整仓库时才查：网页镜像里只有 frontend/（构建上下文就是它），那时跳过并说一声——
//      对比度那半永远查，因为只需要 tokens.css。
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));
const css = readFileSync(join(frontend, "src/styles/tokens.css"), "utf8");
const dartPath = process.env.TOKENS_DART ?? join(frontend, "../app/lib/theme/tokens.dart");
const dart = existsSync(dartPath) ? readFileSync(dartPath, "utf8") : null;

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

const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

const bad = [];
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
  for (const [what, fg, bg, min] of PAIRS) {
    const r = ratio(web[fg], web[bg]);
    if (r < min) bad.push(`${themeName} ${what} --${fg} on --${bg} = ${r.toFixed(2)}:1（要 ≥${min}）`);
  }
}

if (bad.length) {
  console.error("配色守门失败：\n" + bad.join("\n"));
  process.exit(1);
}
console.log(`配色守门通过（${PAIRS.length} 对 × 2 套主题${dart ? "，且与 App tokens.dart 同值" : ""}）`);

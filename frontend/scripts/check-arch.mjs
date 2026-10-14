// 网页端架构守卫（= App test/sheet_test.dart / design_test.dart 的网页版），npm run build 先跑它，违规就失败。
// 规则：
//   1. 确认 / 提示只走 ui/dialog.tsx（confirmDialog / noticeDialog），不许浏览器原生 confirm / alert / prompt。
//   2. @keyframes 只写在 styles/base.css（动效统一一处）。
//   3. 聊天区和卡片块坐在玻璃上：blocks/ 与 features/chat/ 的 CSS 不许用实底 --surface-2 / --bg，填充用 --tile（= App GlassFills）。
//   4. 材质只在底层（styles/ 与 ui/）定义（= App“boxShadow 只在 glass.dart、surface2 只在 theme/”）：其余 CSS 不许直接写
//      var(--shadow-*) / backdrop-filter / var(--surface-2)，投影用 var(--elev-card|float|raised|knob)，模糊用 .glass / .glass.raised / .glass-drawer。
//   5. 强调色克制（= App design_test「accent 只出现在登记过的信号位」）：var(--accent*) 只在 ACCENT 登记的文件里、且不超过登记次数
//      （未读点、进度/运行中、链接/搜索命中、焦点环、唯一关键状态）；其余用 --ink / --text-2。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src", import.meta.url)); // Windows 上 URL.pathname 是 /C:/…，直接用会拼成 C:\C:\…
const files = [];
const walk = (d) => readdirSync(d).forEach((n) => { const p = join(d, n); statSync(p).isDirectory() ? walk(p) : files.push(p); });
walk(root);

const ACCENT = {
  "styles/base.css": 5, // 链接、选中文字、品牌点、焦点环、跳过链接
  "ui/ui.css": 6, // 文字链接、搜索命中×2、预算进度条、图表焦点环、运行中脉冲
  "blocks/blocks.css": 2, // 浏览器接管中的边框；后台任务运行中的进度点
  "features/chat/chat.css": 2, // 跳转闪烁底、工具进行中转圈
  "features/home/home.css": 1, // 收件箱未读点
  "shell/shell.css": 1, // 导航未读点
};
const bad = [];
for (const f of files) {
  const rel = relative(root, f).replaceAll("\\", "/"); // 规则按 / 写，Windows 的 relative() 给的是 \
  const src = readFileSync(f, "utf8");
  if (!rel.startsWith("styles/tokens")) {
    const n = (src.match(/var\(--accent/g) || []).length;
    if (n > (ACCENT[rel] ?? 0)) bad.push(`${rel} 用了 ${n} 处 var(--accent*)（登记 ${ACCENT[rel] ?? 0}）→ 非信号位用 --ink / --text-2，确需新增先在 ACCENT 登记角色`);
  }
  src.split("\n").forEach((line, i) => {
    if (/\.(tsx?|jsx?)$/.test(f) && rel !== "ui/dialog.tsx" && /(^|[^\w.])(window\.)?(confirm|alert|prompt)\(/.test(line))
      bad.push(`${rel}:${i + 1} 原生 confirm/alert/prompt → 用 ui/dialog.tsx 的 confirmDialog / noticeDialog`);
    if (f.endsWith(".css") && rel !== "styles/base.css" && line.includes("@keyframes"))
      bad.push(`${rel}:${i + 1} @keyframes 只能写在 styles/base.css`);
    if (f.endsWith(".css") && /^(blocks|features\/chat)\//.test(rel) && /var\(--(surface-2|bg)\)/.test(line))
      bad.push(`${rel}:${i + 1} 玻璃上的填充用 var(--tile)，不用 --surface-2 / --bg`);
    if (f.endsWith(".css") && !/^(styles|ui)\//.test(rel)) {
      if (/var\(--shadow-/.test(line)) bad.push(`${rel}:${i + 1} 投影用 var(--elev-*)，不直接写 --shadow-*`);
      if (/backdrop-filter/.test(line)) bad.push(`${rel}:${i + 1} 页面不写 backdrop-filter → 拼 .glass / .glass.raised / .glass-drawer`);
      if (/var\(--surface-2\)/.test(line)) bad.push(`${rel}:${i + 1} 玻璃上的填充用 var(--tile)，--surface-2 只在 styles/ 里`);
    }
  });
}
if (bad.length) { console.error("架构守卫失败：\n" + bad.join("\n")); process.exit(1); }
console.log(`架构守卫通过（${files.length} 个文件）`);

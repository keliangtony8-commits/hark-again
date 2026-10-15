// 网页端架构守卫（= App test/sheet_test.dart / design_test.dart 的网页版），npm run build 先跑它，违规就失败。
// 规则：
//   1. 确认 / 提示只走 ui/dialog.tsx（confirmDialog / noticeDialog），不许浏览器原生 confirm / alert / prompt。
//   2. @keyframes 只写在 styles/base.css（动效统一一处）。
//   3. 聊天区和卡片块坐在玻璃上：blocks/ 与 features/chat/ 的 CSS 不许用实底 --surface-2 / --bg，填充用 --tile（= App GlassFills）。
//   4. 材质只在底层（styles/ 与 ui/）定义（= App“boxShadow 只在 glass.dart、surface2 只在 theme/”）：其余 CSS 不许直接写
//      var(--shadow-*) / backdrop-filter / var(--surface-2)，投影用 var(--elev-card|float|raised|knob)，模糊用 .glass / .glass.raised / .glass-drawer。
//   5. 强调色克制（= App design_test「accent 只出现在登记过的信号位」）：var(--accent*) 只在 ACCENT 登记的文件里、且不超过登记次数
//      （未读点、进度/运行中、链接/搜索命中、焦点环、唯一关键状态）；其余用 --ink / --text-2。
//   6. 让出底部输入胶囊只用量出来的 --footer-h（ui/kit.tsx Page / FloatingFooter、ChatView），不许写死兜底数
//      var(--footer-h, 88px)——兜底只会掩盖“忘了量”，胶囊长高（附件、多行、建议）就盖住最后一张卡（v2.94）。
//   7. 列表行 / 分组 / 子页说明只走 ui/kit.tsx 的 ListRow / ListGroup / PageIntro（= App ListRow / ListGroup / PageIntro，v2.97 E1）：
//      页面里手写 className="row …" / "list …" 只许出现在 RAW_ROWS 登记的旧文件里、且不超过登记次数（只减不增，迁完删登记）；
//      .sub-line 段落只由 PageIntro 输出。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src", import.meta.url)); // Windows 上 URL.pathname 是 /C:/…，直接用会拼成 C:\C:\…
const files = [];
const walk = (d) => readdirSync(d).forEach((n) => { const p = join(d, n); statSync(p).isDirectory() ? walk(p) : files.push(p); });
walk(root);

const ACCENT = {
  "styles/base.css": 5, // 链接、选中文字、品牌点、焦点环、跳过链接
  "ui/ui.css": 7, // 文字链接、搜索命中×2、预算进度条、图表焦点环、运行中脉冲、跳转闪烁底（v3.0 由 chat.css 搬来，聊天 / 设置搜索直达共用）
  "blocks/blocks.css": 2, // 浏览器接管中的边框；后台任务运行中的进度点
  "features/chat/chat.css": 1, // 工具进行中转圈
  "features/home/home.css": 1, // 收件箱未读点
  "shell/shell.css": 1, // 导航未读点
};
// v2.98 E1 Web 收尾后仍手写的行（都不适合 ListRow，原因见 docs/devlog.md「v2.98 E1 Web 收尾」）：分体行（主体可点 + 行尾独立按钮 / 开关）、
// 正文带细条或多行说明的富内容行、行首是时间文字的时间线行、常驻 aria-live 副标题行、role=checkbox 选择行。数只许变小；容器一律 ListGroup。
const RAW_ROWS = {
  "features/computer/ComputerDetails.tsx": 6, // 内存 / 磁盘写入 / 配额行：正文里带细条
  "features/computer/ComputerSection.tsx": 4, // 状态行（内存细条）×2 + 服务 / 后台任务分体行
  "features/home/HomeScreen.tsx": 1, // 今天时间线：行首是时间文字
  "features/home/InboxRow.tsx": 1, // 分体行：主体 + 时间 + 菜单
  "features/me/ConnectorsScreen.tsx": 1, // MCP 服务器分体行：主体 + 移除
  "features/me/ReplyLanguageRow.tsx": 1, // 副标题位是常驻 aria-live 容器
  "features/me/SkillsScreen.tsx": 1, // 分体行：主体 + 开关
  "features/me/TaskDetailScreen.tsx": 4, // 运行记录：顶对齐、状态点、多行错误说明
  "features/me/TaskMemory.tsx": 1, // 助手备忘：同运行记录版式，两行预览
  "features/me/TasksScreen.tsx": 1, // 分体行：主体 + 开关
  "features/me/TopConversations.tsx": 2, // 行下一条占比细条
  "features/projects/ProjectFilePicker.tsx": 1, // role=checkbox + 勾选框
};
const RAW_ROW = /className=\{?[`"](row|list)[ `"]/g;
const bad = [];
for (const f of files) {
  const rel = relative(root, f).replaceAll("\\", "/"); // 规则按 / 写，Windows 的 relative() 给的是 \
  const src = readFileSync(f, "utf8");
  if (!rel.startsWith("styles/tokens")) {
    const n = (src.match(/var\(--accent/g) || []).length;
    if (n > (ACCENT[rel] ?? 0)) bad.push(`${rel} 用了 ${n} 处 var(--accent*)（登记 ${ACCENT[rel] ?? 0}）→ 非信号位用 --ink / --text-2，确需新增先在 ACCENT 登记角色`);
  }
  if (f.endsWith(".tsx") && rel !== "ui/kit.tsx") {
    const n = (src.match(RAW_ROW) || []).length;
    if (n > (RAW_ROWS[rel] ?? 0)) bad.push(`${rel} 手写了 ${n} 处 className="row/list"（登记 ${RAW_ROWS[rel] ?? 0}）→ 用 ui/kit.tsx 的 ListRow / ListGroup`);
    if (/sub-line/.test(src)) bad.push(`${rel} 手写 .sub-line 说明 → 用 PageIntro（不给 summary）`);
  }
  src.split("\n").forEach((line, i) => {
    if (/\.(tsx?|jsx?)$/.test(f) && rel !== "ui/dialog.tsx" && /(^|[^\w.])(window\.)?(confirm|alert|prompt)\(/.test(line))
      bad.push(`${rel}:${i + 1} 原生 confirm/alert/prompt → 用 ui/dialog.tsx 的 confirmDialog / noticeDialog`);
    if (f.endsWith(".css") && rel !== "styles/base.css" && line.includes("@keyframes"))
      bad.push(`${rel}:${i + 1} @keyframes 只能写在 styles/base.css`);
    if (f.endsWith(".css") && /^(blocks|features\/chat)\//.test(rel) && /var\(--(surface-2|bg)\)/.test(line))
      bad.push(`${rel}:${i + 1} 玻璃上的填充用 var(--tile)，不用 --surface-2 / --bg`);
    if (f.endsWith(".css") && /var\(--footer-h\s*,/.test(line))
      bad.push(`${rel}:${i + 1} --footer-h 是量出来的胶囊高度，不写兜底数 → var(--footer-h)，并确认外层由 Page footer / ChatView 给值`);
    if (f.endsWith(".css") && !/^(styles|ui)\//.test(rel)) {
      if (/var\(--shadow-/.test(line)) bad.push(`${rel}:${i + 1} 投影用 var(--elev-*)，不直接写 --shadow-*`);
      if (/backdrop-filter/.test(line)) bad.push(`${rel}:${i + 1} 页面不写 backdrop-filter → 拼 .glass / .glass.raised / .glass-drawer`);
      if (/var\(--surface-2\)/.test(line)) bad.push(`${rel}:${i + 1} 玻璃上的填充用 var(--tile)，--surface-2 只在 styles/ 里`);
    }
  });
}
if (bad.length) { console.error("架构守卫失败：\n" + bad.join("\n")); process.exit(1); }
console.log(`架构守卫通过（${files.length} 个文件）`);

// 浏览器画面卡 + 接管页的纯规则（v1.29 / v2.82，= app models/browser_view.dart）：接管条文案、截图刷新节奏（截图轮询，不上 VNC）、
// 读屏句子、接管页坐标换算。卡片 blocks/BrowserBlock.tsx 只做预览 + 入口，接管在全屏 blocks/BrowserTakeover.tsx。
import type { BrowserFile, BrowserHandoff } from "./types";

export const HANDOFF_TITLE = "需要你来";
export const HANDOFF_DONE = "完成，交还";
export const HANDOFF_CANCEL = "做不了";
/** v2.28 浏览器服务本身不能用（卡上 block.down）：标题 + 怎么办（原因在 down 里）。和 app models/browser_view.dart 同文案。 */
export const BROWSER_DOWN_TITLE = "云浏览器现在用不了";
export const BROWSER_DOWN_HINT = "是服务器上的浏览器服务出了问题，不是网页的问题。修好后让助手再打开一次。";

/** 卡头右边的按钮：打开全屏接管页。 */
export const TAKEOVER_LABEL = "接管";
/** 电脑端接管页的一句手势说明（第一次操作后收起）。手机 App 是“双指放大，单指滚动，长按拖动”。 */
export const TAKEOVER_HINT = "单击即点击网页，滚轮滚动，按住拖动，可直接输入";
export const TAKEOVER_KEYS_HINT = "打字发到网页，空着发送 = 回车";
/** 浏览器服务视口（browser/service.py VIEW）。 */
export const BROWSER_VIEW = { width: 1280, height: 800 };
/** 拖动 / 滚动攒多久发一次（= App Timing.takeoverInput）。 */
export const TAKEOVER_INPUT_MS = 80;
/** 按下后移动超过这么多像素才算拖动（否则松手 = 点一下）。 */
export const TAKEOVER_DRAG_SLOP = 4;

/** 截图在 box 里按 contain 摆放的位置。 */
export function takeoverFit(w: number, h: number) {
  const aspect = BROWSER_VIEW.width / BROWSER_VIEW.height;
  const fw = w / h > aspect ? h * aspect : w;
  const fh = fw / aspect;
  return { left: (w - fw) / 2, top: (h - fh) / 2, width: fw, height: fh };
}

/** 接管页上的一点（相对 box 左上）→ 网页 0–1 坐标；落在留边处 → null。 */
export function takeoverPoint(x: number, y: number, w: number, h: number): { x: number; y: number } | null {
  const f = takeoverFit(w, h);
  if (x < f.left || y < f.top || x > f.left + f.width || y > f.top + f.height) return null;
  return { x: (x - f.left) / f.width, y: (y - f.top) / f.height };
}

/** 直接打字时哪些键原样转发（其余可见字符当文字打进去）。 */
export const TAKEOVER_KEYS = new Set(["Enter", "Backspace", "Tab", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/** 接管结束后的一行小字；还在等 → 空。 */
export function handoffStateLine(h: BrowserHandoff): string {
  switch (h.state) {
    case "done": return "你已交还，助手接着做";
    case "cancelled": return "你没有接管，助手会换个办法";
    case "expired": return "等太久没回应，已取消";
    default: return "";
  }
}

export const SCREEN_FAST = 600, SCREEN_OPENING = 1000, SCREEN_IDLE = 1500, SCREEN_PAUSE_AFTER = 120_000;

/** 刷新节奏（毫秒）：接管页开着（或助手在等你）→ 快；页面在打开 → 中；只是看着 → 慢。 */
export const screenInterval = (control: boolean, live: boolean) => (control ? SCREEN_FAST : live ? SCREEN_OPENING : SCREEN_IDLE);

/** 只是看着超过 2 分钟就暂停刷新；操作、打开、等接管都不停。 */
export const screenShouldPause = (idleMs: number, control: boolean, live: boolean, pending: boolean) =>
  !control && !live && !pending && idleMs >= SCREEN_PAUSE_AFTER;

export function browserScreenLabel(takeover: boolean, paused: boolean, site?: string): string {
  const where = site ? `${site} 的浏览器` : "浏览器";
  if (paused) return `${where}画面已暂停，轻点继续`;
  return takeover ? `${where}实时画面，已接管，点哪里就点网页哪里` : `${where}实时画面，点开接管`;
}

/** 卡上文件条的第二行（v1.32，= App browserFileLine）：传上去的 → “已传到网页”；下载的 → “已存到 downloads”。 */
export function browserFileLine(f: BrowserFile): string {
  if (f.kind === "upload") return "已传到网页";
  const slash = f.path.lastIndexOf("/");
  return slash > 0 ? `已存到 ${f.path.slice(0, slash)}` : "已存到工作区";
}

export const browserFileLabel = (f: BrowserFile) => `${f.name}，${browserFileLine(f)}，点开查看`;

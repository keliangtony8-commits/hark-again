// 浏览器画面卡的纯规则（v1.29，= app models/browser_view.dart）：接管条文案、截图刷新节奏（截图轮询，不上 VNC）、读屏句子。
import type { BrowserFile, BrowserHandoff } from "./types";

export const HANDOFF_TITLE = "需要你来";
export const HANDOFF_DONE = "完成，交还";
export const HANDOFF_CANCEL = "做不了";

/** 按钮：没在操作 → 接管；在操作 → 交还（交还的对象是助手）。 */
export const controlLabel = (control: boolean) => (control ? "交还" : "接管");

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

/** 刷新节奏（毫秒）：你在操作（或助手在等你）→ 快；页面在打开 → 中；只是看着 → 慢。 */
export const screenInterval = (control: boolean, live: boolean) => (control ? SCREEN_FAST : live ? SCREEN_OPENING : SCREEN_IDLE);

/** 只是看着超过 2 分钟就暂停刷新；操作、打开、等接管都不停。 */
export const screenShouldPause = (idleMs: number, control: boolean, live: boolean, pending: boolean) =>
  !control && !live && !pending && idleMs >= SCREEN_PAUSE_AFTER;

export function browserScreenLabel(control: boolean, paused: boolean, site?: string): string {
  const where = site ? `${site} 的浏览器` : "浏览器";
  if (paused) return `${where}画面已暂停，点一下继续`;
  return control ? `${where}实时画面，已接管，点哪里就点网页哪里` : `${where}实时画面`;
}

/** 卡上文件条的第二行（v1.32，= App browserFileLine）：传上去的 → “已传到网页”；下载的 → “已存到 downloads”。 */
export function browserFileLine(f: BrowserFile): string {
  if (f.kind === "upload") return "已传到网页";
  const slash = f.path.lastIndexOf("/");
  return slash > 0 ? `已存到 ${f.path.slice(0, slash)}` : "已存到工作区";
}

export const browserFileLabel = (f: BrowserFile) => `${f.name}，${browserFileLine(f)}，点开查看`;

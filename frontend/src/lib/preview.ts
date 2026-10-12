// 端口预览（后端 app/preview.py）：工作区电脑里跑着的网页服务的签名链接，带期限。
// 预览卡和电脑页“正在监听的端口”共用；与 App models/preview.dart 同一套文案。
export type ListeningPort = { port: number; loopback: boolean; pid?: number | null; command: string };
export type PreviewLink = { workspace: string; port: number; url: string; command: string; expires_at: string };

export const portTitle = (port: number, title?: string | null) => (title && title.trim()) || `端口 ${port}`;

export function shortCommand(c: string): string {
  const s = c.trim().replace(/\s+/g, " ");
  return s.length <= 48 ? s : `${s.slice(0, 47)}…`;
}

export const portLine = (p: ListeningPort) =>
  p.loopback ? "只监听本机，要让服务监听 0.0.0.0" : p.command ? shortCommand(p.command) : "网页服务";

export function previewExpiry(expires: string | null | undefined, now = Date.now()): string {
  if (!expires) return "";
  const t = Date.parse(expires);
  if (Number.isNaN(t)) return "";
  const left = t - now;
  if (left <= 0) return "已过期";
  const h = Math.floor(left / 3600_000);
  if (h >= 1) return `${h >= 23 ? 24 : h + 1} 小时内有效`;
  return `还能用 ${Math.max(1, Math.floor(left / 60_000))} 分钟`;
}

export const previewExpired = (expires: string | null | undefined, now = Date.now()) =>
  !!expires && !Number.isNaN(Date.parse(expires)) && Date.parse(expires) <= now;

/** 卡里嵌着看时的 iframe 沙盒：和服务器给的 CSP sandbox 一致（不透明源，碰不到本页登录信息）。 */
export const PREVIEW_SANDBOX = "allow-scripts allow-forms allow-popups allow-modals allow-downloads";

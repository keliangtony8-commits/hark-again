import { server } from "./api";

/** 预览走当前连接的服务器地址（App 里可能和 PUBLIC_URL 不同），分享用后端给的公开地址。 */
export const previewUrl = (slug: string) => `${server.get()}/p/${slug}/`;

export async function copyLink(url: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(url); return true; } catch { return false; }
}

/** 老服务器没有 published 字段 = 已发布。 */
export const isLive = (p: { published?: boolean }) => p.published !== false;

/** 系统分享面板（支持的浏览器才有）；没有就返回 false，调用方退回复制链接。 */
export async function shareLink(url: string, title: string): Promise<boolean> {
  if (!navigator.share) return false;
  try { await navigator.share({ url, title }); return true; } catch { return true; } // 用户取消也算处理过，不再复制
}

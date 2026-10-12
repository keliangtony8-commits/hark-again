// 云浏览器里保存的登录（后端 app/browser_sessions.py，GET /api/browser/sessions、DELETE /api/browser/sessions/{name}）。
// 会话按网站起名：在某个网站登录一次，之后的任务都接着用。纯规则，和 App models/browser_session.dart 同一套措辞。
import { formatAgo } from "./format";

export type BrowserSession = {
  name: string; label: string; open: boolean; saved: boolean; last_used: string | null; cookies: number; domains: string[];
  /** v1.36：服务端判定的登录成功 / 登录过期时刻（再登录成功会清掉过期）；旧服务端没有这两个字段。 */
  signed_in_at?: string | null; expired_at?: string | null;
};
export type BrowserSessionList = { sessions: BrowserSession[]; max_open: number };

export const BROWSER_SESSIONS_PATH = "/api/browser/sessions";
export const BROWSER_SESSIONS_EMPTY = "还没有保存的网站登录";
export const BROWSER_SESSIONS_EMPTY_LINE = "让我在网页上登录一次，之后的任务都会接着用这个登录。";

/** 最近用过的在前，没时间的最后（稳定）。 */
export function sortBrowserSessions(list: BrowserSession[]): BrowserSession[] {
  return list.map((s, i) => [s, i] as const).sort(([a, i], [b, j]) => {
    const x = a.last_used ? Date.parse(a.last_used) : null, y = b.last_used ? Date.parse(b.last_used) : null;
    if (x == null || y == null) return x === y ? i - j : x == null ? 1 : -1;
    return y - x || i - j;
  }).map(([s]) => s);
}

export const BROWSER_SESSION_EXPIRED_LINE = "登录过期了，用到时会请你重新登录";
export const browserSessionExpired = (s: BrowserSession) => !!s.expired_at;

/** 行尾：登录过期 → 已过期（警示色）；开着 → 正在用。 */
export const browserSessionHint = (s: BrowserSession) => (browserSessionExpired(s) ? "已过期" : s.open ? "正在用" : null);

export function browserSessionDetail(s: BrowserSession, now = new Date()): string {
  const when = s.last_used ? `上次用 ${formatAgo(s.last_used, now)}` : null;
  const kept = browserSessionExpired(s) ? BROWSER_SESSION_EXPIRED_LINE
    : s.saved && s.cookies > 0 ? "登录已保存" : "还没有保存的登录";
  return [when, kept].filter(Boolean).join(" · ");
}

export const browserSessionSemantics = (s: BrowserSession, now = new Date()) =>
  `${s.label}，${browserSessionDetail(s, now)}${!browserSessionExpired(s) && s.open ? "，正在用" : ""}`;

export const browserSignOutText = (s: BrowserSession) =>
  `会关掉这个网站的浏览器，并删掉保存的登录。下次要用 ${s.label} 时需要重新登录。`;

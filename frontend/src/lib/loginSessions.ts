// 登录设备（v2.61，= App models/login_session.dart）：/api/auth/sessions 的数据和文字规则。
// 哪个 token 还算数只在后端 app/login_sessions.py。网页不报设备名，后端按 User-Agent 猜（“Chrome · Windows”）。

export interface LoginSession {
  id: string; label: string; kind: "app" | "browser" | "other" | string;
  created_at: string | null; last_seen_at: string | null; current: boolean;
}
export const LOGIN_SESSIONS_PATH = "/api/auth/sessions";

function ago(t: Date, now: Date): string {
  const m = Math.floor((now.getTime() - t.getTime()) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  if (m < 60 * 24) return `${Math.floor(m / 60)} 小时前`;
  if (m < 60 * 24 * 30) return `${Math.floor(m / 1440)} 天前`;
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

function day(t: Date, now: Date): string {
  const d0 = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((d0(now) - d0(t)) / 86400000);
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  return t.getFullYear() === now.getFullYear() ? `${t.getMonth() + 1}月${t.getDate()}日` : `${t.getFullYear()}年${t.getMonth() + 1}月${t.getDate()}日`;
}

/** 副标题：本机写“这台设备”，别的写最近活动；都带登录日期。 */
export function loginSessionLine(s: LoginSession, now = new Date()): string {
  const head = s.current ? "这台设备" : s.last_seen_at ? `${ago(new Date(s.last_seen_at), now)}活动` : "";
  const since = s.created_at ? `${day(new Date(s.created_at), now)}登录` : "";
  return [head, since].filter(Boolean).join(" · ");
}

export const loginSessionsSummary = (list: LoginSession[]) => (list.length <= 1 ? "只有这台设备登着" : `${list.length} 台设备登着`);
export const signedOutToast = (n: number) => (n <= 0 ? "没有别的设备登着" : `已退出其他 ${n} 台设备`);
export const enabledSignedOutToast = (n: number) => (n <= 0 ? null : `为了安全，已退出其他 ${n} 台设备`);

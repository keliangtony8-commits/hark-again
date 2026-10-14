// 钟点与耗时：和 App ui/format.dart 的 formatWhen / formatDuration 同措辞。
const two = (n: number) => String(n).padStart(2, "0");

/** 今天 08:00 / 昨天 08:00 / 明天 08:00 / 10月9日 08:00 / 2025年10月9日 08:00（本地时区）。 */
export function formatWhen(iso: string | null, now = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso);
  const clock = `${two(t.getHours())}:${two(t.getMinutes())}`;
  const day = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return `今天 ${clock}`;
  if (diff === 1) return `昨天 ${clock}`;
  if (diff === -1) return `明天 ${clock}`;
  if (t.getFullYear() === now.getFullYear()) return `${t.getMonth() + 1}月${t.getDate()}日 ${clock}`;
  return `${t.getFullYear()}年${t.getMonth() + 1}月${t.getDate()}日 ${clock}`;
}

/** 聊天里点一下露出的消息时间（§I，同 App formatClock）：当天 17:07 / 10月13日 17:07 / 2025年10月13日 17:07（本地时区）。 */
export function formatClock(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso);
  const clock = `${two(t.getHours())}:${two(t.getMinutes())}`;
  if (t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() && t.getDate() === now.getDate()) return clock;
  if (t.getFullYear() === now.getFullYear()) return `${t.getMonth() + 1}月${t.getDate()}日 ${clock}`;
  return `${t.getFullYear()}年${t.getMonth() + 1}月${t.getDate()}日 ${clock}`;
}

/** 不到 1 秒 / 12 秒 / 3 分 5 秒 / 1 小时 2 分。 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return "不到 1 秒";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return s % 60 === 0 ? `${Math.floor(s / 60)} 分` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
  return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`;
}

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];
/** 10月11日 星期日（主页问候下的日期）。同 App formatDate。 */
export const formatDate = (t: Date) => `${t.getMonth() + 1}月${t.getDate()}日 星期${WEEKDAYS[t.getDay()]}`;

/** 聊天里的日期分隔：今天 / 昨天 / 10月9日 星期五 / 2025年10月9日 星期四（本地时区）。同 App formatDay。 */
export function formatDay(iso: string, now = new Date()): string {
  const t = new Date(iso);
  const diff = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()) / 86400000);
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  return t.getFullYear() === now.getFullYear() ? formatDate(t) : `${t.getFullYear()}年${formatDate(t)}`;
}

/** 第 i 条消息上方要不要画日期分隔：和前面最近一条有时间的消息不在同一天（没有时间的消息从不起新的一天）。同 App startsNewDay。 */
export function startsNewDay(ms: { created_at?: string }[], i: number): boolean {
  const at = ms[i].created_at;
  if (!at) return false;
  const t = new Date(at);
  for (let j = i - 1; j >= 0; j--) {
    const p = ms[j].created_at;
    if (p) { const d = new Date(p); return d.getFullYear() !== t.getFullYear() || d.getMonth() !== t.getMonth() || d.getDate() !== t.getDate(); }
  }
  return true;
}

/** 刚刚 / 5 分钟前 / 3 小时前 / 2 天前 / 2026-09-01。同 App formatAgo。 */
export function formatAgo(iso: string | null, now = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso);
  const m = Math.floor((now.getTime() - t.getTime()) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  if (m < 1440) return `${Math.floor(m / 60)} 小时前`;
  if (m < 43200) return `${Math.floor(m / 1440)} 天前`;
  return `${t.getFullYear()}-${two(t.getMonth() + 1)}-${two(t.getDate())}`;
}

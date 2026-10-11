// 用量与花费（GET /api/usage）：类型 + 展示格式。和 App 的 models/usage.dart、ui/format.dart 同一套规则。
export type ModelUsage = { model: string; calls: number; prompt_tokens: number; completion_tokens: number; cost: number };
export type UsagePeriod = { calls: number; tokens: number; cost: number; models: ModelUsage[] };
/** 本月某一天（服务器 TIMEZONE 的本地日期 "YYYY-MM-DD"）。 */
export type UsageDay = { date: string; calls: number; tokens: number; cost: number };
/** 本月最花钱的对话之一；title 为 null = 对话已删（用量还在）。 */
export type UsageConversation = { id: string; title: string | null; calls: number; tokens: number; cost: number };
/** 上个月：全月合计 + to_date 同期（上月 1 号到上月同一天同一时刻，服务器按 TIMEZONE 对齐日历）。 */
export type UsageSum = { calls: number; tokens: number; cost: number };
export type LastMonthUsage = UsageSum & { to_date: UsageSum };
/** daily：本月 1 号到今天每天一项；conversations：本月最花钱的几个对话；last_month：上月对比。老服务器都没有。 */
export type UsageReport = { currency: string; budget: number | null; priced: string[]; today: UsagePeriod; month: UsagePeriod;
  daily?: UsageDay[]; conversations?: UsageConversation[]; last_month?: LastMonthUsage };
export type BudgetLevel = "ok" | "near" | "over";

const NEAR_AT = 0.8;

export const budgetRatio = (r: UsageReport) => (r.budget && r.budget > 0 ? r.month.cost / r.budget : null);

export function budgetLevel(r: UsageReport): BudgetLevel {
  const x = budgetRatio(r);
  return x === null || x < NEAR_AT ? "ok" : x < 1 ? "near" : "over";
}

/** 本月至今对比上月同期的涨跌（0.23 = 多 23%）；有定价按钱，否则 token。老服务器 / 上月同期为 0 → null。与 App 的 monthDelta 同规则。 */
export function monthDelta(r: UsageReport): number | null {
  const lm = r.last_month;
  if (!lm) return null;
  const money = r.priced.length > 0;
  const prev = money ? lm.to_date.cost : lm.to_date.tokens;
  if (prev <= 0) return null;
  return (money ? r.month.cost : r.month.tokens) / prev - 1;
}

export const FLAT_WITHIN = 0.05;

export const hasUnpriced = (r: UsageReport) => r.month.models.some((m) => !r.priced.includes(m.model));

export function formatMoney(v: number, currency: string) {
  const sign = currency === "CNY" ? "¥" : currency === "USD" ? "$" : `${currency} `;
  return sign + v.toFixed(v !== 0 && Math.abs(v) < 0.1 ? 3 : 2);
}

export function formatTokens(n: number) {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`;
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0)}M`;
}

/** 一段用量的合计 + 按模型拆分（和 App 的 UsageTotal 同形状）：单个对话累计 GET /api/conversations/{id}/usage、
 *  某一天 GET /api/usage/days/{date}（多一个 date）共用。 */
export type UsageTotal = { currency: string; priced: string[]; total: UsagePeriod; date?: string };
export type ConversationUsage = UsageTotal;
/** 某一天的明细 GET /api/usage/days/{date}：按模型（total）+ 那天最花钱的对话（老服务器没有 → undefined）。与 App 的 UsageDayDetail 同形状。 */
export type UsageDayDetail = UsageTotal & { conversations?: UsageConversation[] };

/** 某个对话占当天的份额（0..1），规则同 shareOf。 */
export function dayShareOf(d: UsageDayDetail, c: UsageConversation): number {
  const money = d.priced.length > 0 && d.total.cost > 0;
  const total = money ? d.total.cost : d.total.tokens;
  if (total <= 0) return 0;
  return Math.min(Math.max((money ? c.cost : c.tokens) / total, 0), 1);
}

/** 聊天顶栏标题下那一行；还没调用过模型 → null（不显示）。与 App 的 usageLine 同规则。 */
export function usageLine(u: ConversationUsage): string | null {
  if (u.total.calls === 0) return null;
  const tokens = `${formatTokens(u.total.tokens)} token`;
  return u.priced.length > 0 ? `${formatMoney(u.total.cost, u.currency)} · ${tokens}` : tokens;
}

/** 本月天数（图表按整月排格子）。与 App 的 UsageReport.daysInMonth 同规则。 */
export function daysInMonth(r: UsageReport): number {
  const first = r.daily?.[0]?.date;
  if (!first) return 0;
  const [y, m] = first.split("-").map(Number);
  return new Date(y, m, 0).getDate();
}

/** 按预算平均到每天；没设预算或没定价 → null。与 App 的 dailyPace 同规则。 */
export function dailyPace(r: UsageReport): number | null {
  const n = daysInMonth(r);
  return r.budget && r.budget > 0 && r.priced.length > 0 && n > 0 ? r.budget / n : null;
}

/** 图表上方的读数，与 App usage_chart.dart 的 dayLabel / dayValue 同文案。 */
export function dayLabel(d: UsageDay, today: boolean) {
  const [, m, day] = d.date.split("-").map(Number);
  return `${m}月${day}日${today ? "（今天）" : ""}`;
}

export function dayValue(d: UsageDay, r: UsageReport) {
  if (d.calls === 0) return "没有调用";
  const tokens = `${formatTokens(d.tokens)} token · ${d.calls} 次`;
  return r.priced.length === 0 ? tokens : `${formatMoney(d.cost, r.currency)} · ${tokens}`;
}

/** 某个对话占本月的份额（0..1）：有定价按钱，否则按 token。与 App 的 UsageReport.shareOf 同规则。 */
export function shareOf(r: UsageReport, c: UsageConversation): number {
  const money = r.priced.length > 0 && r.month.cost > 0;
  const total = money ? r.month.cost : r.month.tokens;
  if (total <= 0) return 0;
  return Math.min(Math.max((money ? c.cost : c.tokens) / total, 0), 1);
}

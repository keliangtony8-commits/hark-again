// 用量与花费（GET /api/usage）：类型 + 展示格式。和 App 的 models/usage.dart、ui/format.dart 同一套规则。
/** cached_tokens = prompt_tokens 里命中提示缓存的部分（后端 app/prompt_cache.py；老服务器没有这个字段）。 */
export type ModelUsage = { model: string; calls: number; prompt_tokens: number; completion_tokens: number; cached_tokens?: number; cost: number };
export type UsagePeriod = { calls: number; tokens: number; cost: number; models: ModelUsage[]; prompt_tokens?: number; cached_tokens?: number };

/** “缓存命中 62%”；没有命中（供应商不报 / 老服务器）→ null，不显示。和 App 的 cacheHitLabel 同一规则。 */
export function cacheHitLabel(cached: number | undefined, prompt: number): string | null {
  if (!cached || cached <= 0 || prompt <= 0) return null;
  const pct = Math.min(100, (cached / prompt) * 100);
  return `缓存命中 ${pct < 1 ? "<1" : Math.round(pct)}%`;
}
/** 本月某一天（服务器 TIMEZONE 的本地日期 "YYYY-MM-DD"）。 */
export type UsageDay = { date: string; calls: number; tokens: number; cost: number };
/** 本月最花钱的对话之一；title 为 null = 对话已删（用量还在）。 */
export type UsageConversation = { id: string; title: string | null; calls: number; tokens: number; cost: number };
/** 上个月：全月合计 + to_date 同期（上月 1 号到上月同一天同一时刻，服务器按 TIMEZONE 对齐日历）。 */
export type UsageSum = { calls: number; tokens: number; cost: number };
export type LastMonthUsage = UsageSum & { to_date: UsageSum };
/** 本月“自动选模型”的账（后端 app/router_stats.py 是唯一规则；= App RouterUsage）。saved / net 为 null = 复杂档没定价，不估。 */
export type RouterUsage = { turns: number; simple: number; complex: number; free: number;
  classifier: { turns: number; cost: number; ms: number }; simple_cost: number; saved: number | null; net: number | null;
  simple_model: string; complex_model: string };
/** daily：本月 1 号到今天每天一项；conversations：本月最花钱的几个对话；last_month：上月对比；router：自动选模型的账（没用过“自动” → null）。老服务器都没有。 */
export type UsageReport = { currency: string; budget: number | null; priced: string[]; today: UsagePeriod; month: UsagePeriod;
  daily?: UsageDay[]; conversations?: UsageConversation[]; last_month?: LastMonthUsage; router?: RouterUsage | null };
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
/** 本月一次调用都没有（新装、月初）：用量页不画全零的每日图，换一张说明卡（= App UsageReport.idle）。 */
export const isIdle = (r: UsageReport) => r.month.calls === 0 && r.month.tokens === 0;

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

// —— 自动选模型的账（与 App models/usage.dart 的 routerHeadline / routerSplitLine / routerCostLine / routerNote 同一套文案）——
export const routerSimpleShare = (u: RouterUsage) => (u.turns <= 0 ? 0 : Math.min(1, Math.max(0, u.simple / u.turns)));
export const routerLosing = (u: RouterUsage) => (u.net ?? 0) < 0;
const simpleName = (u: RouterUsage) => u.simple_model || "简单档";
const complexName = (u: RouterUsage) => u.complex_model || "复杂档";

export function routerHeadline(u: RouterUsage, currency: string): string {
  if (u.net === null || u.net === undefined) return `${u.turns} 轮`;
  return u.net < 0 ? `多花 ${formatMoney(-u.net, currency)}` : `约省 ${formatMoney(u.net, currency)}`;
}

export const routerSplitLine = (u: RouterUsage) =>
  `本月 ${u.turns} 轮 · ${simpleName(u)} ${u.simple} 轮 · ${complexName(u)} ${u.complex} 轮`;

export function routerCostLine(u: RouterUsage, currency: string, money: boolean): string {
  const parts: string[] = u.free > 0 ? [`${u.free} 轮按规则直接定（不花钱）`] : [];
  const c = u.classifier;
  if (c.turns > 0) parts.push(`${c.turns} 轮问了分类器${money ? `，花 ${formatMoney(c.cost, currency)}` : ""}${c.ms > 0 ? `，平均 ${c.ms} 毫秒` : ""}`);
  return parts.length ? parts.join(" · ") : "都用了默认档";
}

export function routerNote(u: RouterUsage): string {
  if (u.net === null || u.net === undefined) return "复杂档没配单价，算不出省了多少。在服务器 .env 的 MODEL_PRICES 补上两档单价即可。";
  if (routerLosing(u)) return "分类器花的比省下的还多。可以在服务器 .env 把 MODEL_ROUTER 改成 rules（只用规则、零调用）。";
  return "按“同样的 token 换成复杂档要花多少”估算，减去分类器的花费。";
}

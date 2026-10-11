import type { UsagePeriod, UsageReport, UsageSum } from "./usage";

/**
 * 本月用量导出成 CSV（和 App 的 models/usage_csv.dart 同一套规则，逐字节一致）。
 * 纯客户端：数据就是已加载的 /api/usage 报表。一张长表，第一列“类别”= 汇总 / 每天 / 模型 / 对话。
 * 汇总带上月同期 + 上月全月（有 last_month 才有，没有模型拆分 → 输入/输出留空）。
 * 没定价 → 花费整列留空；未定价模型那行留空；每天/对话没有输入输出拆分，留空；防公式注入；BOM + CRLF。
 */
export const USAGE_CSV_HEADER = ["类别", "名称", "日期", "调用次数", "输入 token", "输出 token", "总 token"];

export function usageCsv(r: UsageReport): string {
  const money = r.priced.length > 0;
  const cost = (v: number, priced = true) => (money && priced ? num(v) : "");
  const rows: string[][] = [
    [...USAGE_CSV_HEADER, `花费（${r.currency}）`],
    period("本月", r.month, money),
    period("今天", r.today, money),
    ...(r.last_month ? [period("上月同期", r.last_month.to_date, money), period("上月全月", r.last_month, money)] : []),
    ...(r.budget != null ? [["汇总", "预算", "", "", "", "", "", num(r.budget)]] : []),
    ...(r.daily ?? []).map((d) => ["每天", "", d.date, `${d.calls}`, "", "", `${d.tokens}`, cost(d.cost)]),
    ...r.month.models.map((m) => ["模型", m.model, "", `${m.calls}`, `${m.prompt_tokens}`, `${m.completion_tokens}`,
      `${m.prompt_tokens + m.completion_tokens}`, cost(m.cost, r.priced.includes(m.model))]),
    ...(r.conversations ?? []).map((c) => ["对话", c.title ?? "已删除的对话", "", `${c.calls}`, "", "", `${c.tokens}`, cost(c.cost)]),
  ];
  return "\uFEFF" + rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** 文件名：用量-2026-10.csv（月份取 daily 第一天；老服务器没有就用 at / 现在）。 */
export function usageCsvFileName(r: UsageReport, at = new Date()): string {
  const first = r.daily?.[0]?.date;
  const ym = first ? first.slice(0, 7) : `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, "0")}`;
  return `用量-${ym}.csv`;
}

function period(name: string, p: UsagePeriod | UsageSum, money: boolean): string[] {
  const models = "models" in p ? p.models : [];
  const split = models.length > 0;
  const sum = (k: "prompt_tokens" | "completion_tokens") => models.reduce((a, m) => a + m[k], 0);
  return ["汇总", name, "", `${p.calls}`, split ? `${sum("prompt_tokens")}` : "", split ? `${sum("completion_tokens")}` : "",
    `${p.tokens}`, money ? num(p.cost) : ""];
}

/** 最多 4 位小数，去掉末尾的 0。 */
function num(v: number): string {
  let s = v.toFixed(4);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" ? "0" : s;
}

function cell(v: string): string {
  let s = v;
  if (s && "=+-@\t\r".includes(s[0]) && Number.isNaN(Number(s))) s = `'${s}`;
  if (/[",\r\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
  return s;
}

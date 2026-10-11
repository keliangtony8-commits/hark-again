import { useCallback, useEffect, useState } from "react";
import { http } from "../../lib/api";
import { budgetLevel, budgetRatio, formatMoney, formatTokens, hasUnpriced, type UsageReport } from "../../lib/usage";
import { downloadText } from "../../lib/export";
import { usageCsv, usageCsvFileName } from "../../lib/usageCsv";
import { IconDownload } from "../../ui/icons";
import { Skeleton } from "../../ui/kit";
import DailyChart from "./DailyChart";
import DayBreakdown from "./DayBreakdown";
import ModelUsageList from "./ModelUsageList";
import MonthCompare from "./MonthCompare";
import TopConversations from "./TopConversations";

/** 设置页“用量与花费”：本月（对比预算、对比上月同期 MonthCompare）、今天、本月每天（DailyChart，选一天看按模型拆分 DayBreakdown）、最花钱的对话（TopConversations，点开跳进去）、按模型拆分；右上角下载本月 CSV（lib/usageCsv.ts）。只读；记账在后端 app/usage.py。 */
export default function UsageCard() {
  const [r, setR] = useState<UsageReport | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try { setR(await http.get<UsageReport>("/api/usage")); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (error) return <div className="list"><button className="row" onClick={load}><div className="row-body"><div className="row-title">用量加载失败</div><div className="row-sub">{error} · 点这里重试</div></div></button></div>;
  if (!r) return <Skeleton rows={2} />;

  const money = r.priced.length > 0;
  const ratio = budgetRatio(r);
  const level = budgetLevel(r);
  return (
    <div className="usage">
      <div className="usage-hero list">
        <div className="usage-head">
          <div className="usage-label">本月</div>
          <button className="icon-btn sm" title="下载本月 CSV" aria-label="下载本月 CSV"
            onClick={() => downloadText(usageCsvFileName(r), usageCsv(r), "text/csv")}><IconDownload /></button>
        </div>
        <div className="usage-big">{money ? formatMoney(r.month.cost, r.currency) : `${formatTokens(r.month.tokens)} token`}</div>
        <MonthCompare report={r} />
        {ratio !== null && r.budget !== null && <>
          <div className={`meter meter-${level}`} role="meter" aria-label="本月预算" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)}>
            <span style={{ transform: `scaleX(${Math.min(ratio, 1)})` }} />
          </div>
          <div className={`usage-note note-${level}`}>
            {level === "over"
              ? `已超出预算 ${formatMoney(r.month.cost - r.budget, r.currency)}（预算 ${formatMoney(r.budget, r.currency)}）`
              : `预算 ${formatMoney(r.budget, r.currency)} · 还剩 ${formatMoney(r.budget - r.month.cost, r.currency)}（${Math.round(ratio * 100)}%）`}
          </div>
        </>}
        <div className="usage-stats">
          <div><span>今天</span><b>{money ? formatMoney(r.today.cost, r.currency) : formatTokens(r.today.tokens)}</b><small>{r.today.calls} 次调用</small></div>
          <div><span>本月 token</span><b>{formatTokens(r.month.tokens)}</b><small>{r.month.calls} 次调用</small></div>
        </div>
      </div>
      {r.daily && r.daily.length > 0 && <DailyChart report={r} detail={(day, today) => <DayBreakdown report={r} day={day} today={today} />} />}
      {r.conversations && r.conversations.length > 0 && <TopConversations report={r} />}
      {r.month.models.length > 0 && <ModelUsageList models={r.month.models} priced={r.priced} currency={r.currency} />}
      {(!money || hasUnpriced(r)) && (
        <p className="usage-hint">
          {money ? "“未定价”的模型只统计 token。在服务器 .env 的 MODEL_PRICES 里补上单价即可算钱。"
            : "还没配置单价，只统计 token。在服务器 .env 里设置 MODEL_PRICES（每百万 token 的价格）和 MONTHLY_BUDGET 后就能看到花费和预算。"}
        </p>
      )}
    </div>
  );
}

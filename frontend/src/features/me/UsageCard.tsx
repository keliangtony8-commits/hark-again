import { useNavigate } from "react-router-dom";
import { useSwr } from "../../hooks/useSwr";
import { budgetLevel, budgetRatio, formatMoney, formatTokens, hasUnpriced, isIdle, type UsageReport } from "../../lib/usage";
import { downloadText } from "../../lib/export";
import { usageCsv, usageCsvFileName } from "../../lib/usageCsv";
import { IconDownload, IconGauge } from "../../ui/icons";
import { Hint, ListGroup, ListRow, stagger } from "../../ui/kit";
import CountUp from "../../ui/CountUp";
import DailyChart from "./DailyChart";
import DayBreakdown from "./DayBreakdown";
import ModelUsageList from "./ModelUsageList";
import MonthCompare from "./MonthCompare";
import RouterUsageCard from "./RouterUsageCard";
import TopConversations from "./TopConversations";

/** 设置页“用量与花费”（= App dbaeb72）：一张概览卡（本月、对比预算 / 上月同期 MonthCompare、今天、本月调用次数），本月每天（DailyChart，选一天看按模型拆分 DayBreakdown）、最花钱的对话（TopConversations，点开跳进去；已删的合并一行；前 3 行 +“全部 N 个 ›”进 /me/usage/conversations）、按模型拆分（前 3 行 +“全部 ›”进 /me/usage/models）、自动选模型的账（RouterUsageCard，没用过“自动”不显示）；右上角下载本月 CSV（lib/usageCsv.ts）。只读；记账在后端 app/usage.py。 */
/** 用量页每个列表只露前几行，其余进子页（UsageScreen 里的 UsageDetailScreen）。 */
export const PREVIEW_ROWS = 3;

export default function UsageCard() {
  const nav = useNavigate();
  const { data: r, error, reload } = useSwr<UsageReport>("/api/usage");

  if (error) return <ListGroup><ListRow onClick={() => void reload()} trail={null} title="用量加载失败" sub={`${error.message} · 点这里重试`} /></ListGroup>;
  // 骨架形状跟报表一致（概览卡 / 每日图，= App _ReportSkeleton），换成内容时整块淡入不跳版
  if (!r) return <div className="usage usage-skeleton" aria-busy="true"><div className="skeleton sk-hero" style={{ height: 148 + 104 }} /><div className="skeleton sk-chart" /></div>;

  const money = r.priced.length > 0;
  const ratio = budgetRatio(r);
  const level = budgetLevel(r);
  return (
    <div className="usage fade-in">
      <div className="usage-hero list enter" style={stagger(0)}>
        <div className="usage-head">
          <div className="usage-label">本月</div>
          <button className="icon-btn sm" title="下载本月 CSV" aria-label="下载本月 CSV"
            onClick={() => downloadText(usageCsvFileName(r), usageCsv(r), "text/csv")}><IconDownload /></button>
        </div>
        <div className="usage-big"><CountUp value={money ? formatMoney(r.month.cost, r.currency) : `${formatTokens(r.month.tokens)} token`} /></div>
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
          <div><span>今天</span><b><CountUp value={money ? formatMoney(r.today.cost, r.currency) : formatTokens(r.today.tokens)} /></b><small>{r.today.calls} 次调用</small></div>
          <div><span>本月调用</span><b><CountUp value={`${r.month.calls} 次`} /></b><small>{money ? `${formatTokens(r.month.tokens)} token` : "本月合计"}</small></div>
        </div>
      </div>
      {isIdle(r) && <div className="enter" style={stagger(1)}><Hint icon={<IconGauge />} title="本月还没有用量" text="和助手聊上几句，这里会按天画出用量，并列出最花钱的对话和各个模型的花费。" /></div>}
      {!isIdle(r) && r.daily && r.daily.length > 0 && <div className="enter" style={stagger(1)}><DailyChart report={r} detail={(day, today) => <DayBreakdown report={r} day={day} today={today} />} /></div>}
      {r.conversations && r.conversations.length > 0 && <div className="enter" style={stagger(2)}><TopConversations report={r} limit={PREVIEW_ROWS} /></div>}
      {r.month.models.length > 0 && <section className="enter" style={stagger(3)}>
        <div className="section-title"><span>本月按模型</span>
          {r.month.models.length > PREVIEW_ROWS && <button className="btn btn-ghost btn-sm" onClick={() => nav("/me/usage/models")}>全部 ›</button>}
        </div>
        <ModelUsageList models={r.month.models} priced={r.priced} currency={r.currency} limit={PREVIEW_ROWS} />
      </section>}
      {r.router && <div className="enter" style={stagger(4)}><RouterUsageCard usage={r.router} currency={r.currency} money={money} /></div>}
      {(!money || hasUnpriced(r)) && (
        <p className="usage-hint" style={{ fontSize: "var(--fs-xs)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
          title={money ? "未定价模型只统计 token。在服务器 .env 的 MODEL_PRICES 里补上单价即可算钱。" : "还没配置单价，只统计 token。在服务器 .env 里设置 MODEL_PRICES（每百万 token 的价格）和 MONTHLY_BUDGET 后就能看到花费和预算。"}>
          {money ? "未定价模型只统计 token · .env 的 MODEL_PRICES 补单价" : "未配单价，只统计 token · .env 设 MODEL_PRICES 看花费"}
        </p>
      )}
    </div>
  );
}

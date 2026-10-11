import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { http } from "../../lib/api";
import { dayShareOf, formatMoney, formatTokens, type ModelUsage, type UsageDay, type UsageDayDetail, type UsageReport } from "../../lib/usage";
import { IconChevron } from "../../ui/icons";
import { Skeleton } from "../../ui/kit";

/** 用量图选定那天的明细（按模型 + 那天最花钱的对话），与 App usage_day.dart 同规则：
 *  没调用 → 不显示；一律取 GET /api/usage/days/{date}（今天也取，报表里没有“今天的对话”），以日期为 key 挂载，换天就重取；
 *  今天在请求途中/失败时先用报表的 today 画模型行。对话行点开跳进对话（/chat + state.open），已删的只展示。 */
export default function DayBreakdown({ report: r, day, today }: { report: UsageReport; day: UsageDay; today: boolean }) {
  const active = day.calls > 0;
  const [state, setState] = useState<{ data: UsageDayDetail | null; error: boolean }>({ data: null, error: false });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!active) return;
    let live = true;
    http.get<UsageDayDetail>(`/api/usage/days/${day.date}`)
      .then((data) => { if (live) setState({ data, error: false }); })
      .catch(() => { if (live) setState({ data: null, error: true }); });
    return () => { live = false; };
  }, [active, day.date, tick]);

  if (!active) return null;
  const fallback = today ? <DayModelRows models={r.today.models} priced={r.priced} currency={r.currency} /> : null;
  if (state.error) return <>{fallback}<button className="day-retry" onClick={() => { setState({ data: null, error: false }); setTick((t) => t + 1); }}>明细加载失败，点这里重试</button></>;
  if (!state.data) return fallback ?? <Skeleton rows={1} />;
  const d = state.data;
  return <>
    <DayModelRows models={d.total.models} priced={d.priced} currency={d.currency} />
    {d.conversations && d.conversations.length > 0 && <DayConversationRows detail={d} label={today ? "今天最花钱的对话" : "那天最花钱的对话"} />}
  </>;
}

/** 紧凑的按模型行：名字 · token · 钱，下面一条占当天比例的细条（有定价按钱，否则按 token）。 */
function DayModelRows({ models, priced, currency }: { models: ModelUsage[]; priced: string[]; currency: string }) {
  const money = priced.length > 0 && models.some((m) => m.cost > 0);
  const val = (m: ModelUsage) => (money ? m.cost : m.prompt_tokens + m.completion_tokens);
  const total = models.reduce((s, m) => s + val(m), 0);
  return (
    <div className="day-models">
      {models.map((m) => (
        <div className="day-row" key={m.model}>
          <span className="day-row-name">{m.model}<small>{formatTokens(m.prompt_tokens + m.completion_tokens)} token · {m.calls} 次</small></span>
          <b className={priced.includes(m.model) ? undefined : "muted"}>{priced.includes(m.model) ? formatMoney(m.cost, currency) : "未定价"}</b>
          <Meter share={total > 0 ? val(m) / total : 0} />
        </div>
      ))}
    </div>
  );
}

/** 那天最花钱的对话：同一种紧凑行；能点的是按钮（带箭头），已删的灰显。 */
function DayConversationRows({ detail: d, label }: { detail: UsageDayDetail; label: string }) {
  const nav = useNavigate();
  const money = d.priced.length > 0;
  return (
    <div className="day-convs">
      <div className="day-label">{label}</div>
      {(d.conversations ?? []).map((c) => {
        const inner = <>
          <span className="day-row-name">{c.title ?? "已删除的对话"}<small>{formatTokens(c.tokens)} token · {c.calls} 次</small></span>
          <b>{money ? formatMoney(c.cost, d.currency) : formatTokens(c.tokens)}</b>
          {c.title !== null && <IconChevron />}
          <Meter share={dayShareOf(d, c)} />
        </>;
        return c.title === null
          ? <div className="day-row gone" key={c.id}>{inner}</div>
          : <button className="day-row" key={c.id} onClick={() => nav("/chat", { state: { open: c.id } })}>{inner}</button>;
      })}
    </div>
  );
}

const Meter = ({ share }: { share: number }) => <div className="meter" aria-hidden><span style={{ transform: `scaleX(${share})` }} /></div>;

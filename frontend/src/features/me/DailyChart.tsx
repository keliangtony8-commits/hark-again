import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { dailyPace, dayLabel, dayValue, daysInMonth, formatMoney, type UsageDay, type UsageReport } from "../../lib/usage";

const W = 10; // 每格在 viewBox 里的宽
const H = 100;
const GAP = 0.28; // 柱间空隙占格宽，与 App DailyBarsPainter 一致
const HEADROOM = 1.12;
const MIN_VISIBLE = 2;

/** 用量卡“本月每天”：与 App usage_chart.dart 同版面、同规则。
 *  点/拖选天（默认今天）；键盘 ←/→ 换天（role=slider）；有预算且定价时画日均预算虚线，超过的柱子用警示色。
 *  detail：选定那天的明细（DayBreakdown）；读数跟手，明细只在选定时换（按下、松手、键盘），拖动途中不请求。 */
export default function DailyChart({ report: r, detail }: { report: UsageReport; detail?: (day: UsageDay, today: boolean) => ReactNode }) {
  const days = r.daily ?? [];
  const slots = daysInMonth(r);
  const money = r.priced.length > 0;
  const pace = dailyPace(r);
  const [picked, setPicked] = useState<number | null>(null); // null = 跟着今天
  const [settled, setSettled] = useState<number | null>(null); // 明细跟着的那天；拖动途中不变
  const svg = useRef<SVGSVGElement>(null);
  if (days.length === 0 || slots === 0) return null;

  const last = days.length - 1;
  const sel = Math.min(Math.max(picked ?? last, 0), last);
  const value = (i: number) => (money ? days[i].cost : days[i].tokens);
  const values = days.map((_, i) => value(i));
  const top = Math.max(Math.max(...values), pace ?? 0) * HEADROOM || 1;
  const peak = values.indexOf(Math.max(...values));
  const shown = Math.min(Math.max(settled ?? last, 0), last);
  const pick = (i: number, settle = true) => {
    const next = Math.min(Math.max(i, 0), last);
    setPicked(next);
    if (settle) setSettled(next);
  };
  const pickAt = (e: PointerEvent<SVGSVGElement>, settle: boolean) => {
    const box = svg.current?.getBoundingClientRect();
    if (box && box.width > 0) pick(Math.floor(((e.clientX - box.left) / box.width) * slots), settle);
  };
  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key];
    if (step) { e.preventDefault(); pick(sel + step); }
    if (e.key === "Home") { e.preventDefault(); pick(0); }
    if (e.key === "End") { e.preventDefault(); pick(last); }
  };
  const label = (i: number) => `${dayLabel(days[i], i === last)}：${dayValue(days[i], r)}`;
  const bw = W * (1 - GAP);

  return (
    <div className="daily list">
      <div className="daily-head" aria-hidden>
        <span>{dayLabel(days[sel], sel === last)}</span>
        <b>{dayValue(days[sel], r)}</b>
      </div>
      <svg
        ref={svg}
        className="daily-plot"
        viewBox={`0 0 ${slots * W} ${H}`}
        preserveAspectRatio="none"
        role="slider"
        tabIndex={0}
        aria-label={`本月每天的${money ? "花费" : "token"}，最多的是 ${Number(days[peak].date.slice(8))} 日（${dayValue(days[peak], r)}）`}
        aria-valuemin={1}
        aria-valuemax={days.length}
        aria-valuenow={sel + 1}
        aria-valuetext={label(sel)}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); pickAt(e, true); }}
        onPointerMove={(e) => { if (e.buttons) pickAt(e, false); }}
        onPointerUp={() => setSettled(picked)}
        onPointerCancel={() => setSettled(picked)}
        onKeyDown={onKey}
      >
        <line className="base" x1={0} y1={H - 0.5} x2={slots * W} y2={H - 0.5} vectorEffect="non-scaling-stroke" />
        {values.map((v, i) => {
          if (v <= 0) return null;
          const h = Math.max((v / top) * H, MIN_VISIBLE);
          const cls = [pace !== null && v > pace ? "hot" : "", i === sel ? "on" : ""].join(" ").trim();
          return <rect key={days[i].date} className={cls || undefined} x={i * W + (W - bw) / 2} y={H - h} width={bw} height={h} rx={1} />;
        })}
        {values[sel] <= 0 && <rect className="dot" x={sel * W + (W - bw) / 2} y={H - 3} width={bw} height={3} rx={1} />}
        {pace !== null && <line className="pace" x1={0} y1={H - (pace / top) * H} x2={slots * W} y2={H - (pace / top) * H} vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="daily-axis" aria-hidden><span>1日</span><span>{Math.ceil(slots / 2)}日</span><span>{slots}日</span></div>
      {pace !== null && <div className="daily-legend"><i />日均预算 {formatMoney(pace, r.currency)}，超过的那天标成橙色</div>}
      {detail && <div className="day-detail" key={days[shown].date}>{detail(days[shown], shown === last)}</div>}
    </div>
  );
}

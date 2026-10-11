import { FLAT_WITHIN, formatMoney, formatTokens, monthDelta, type UsageReport } from "../../lib/usage";

/** 月卡里的“比上月同期”：涨跌小标签 + 上月全月作参照；规则与 App 的 MonthCompare 相同
 *  （涨 warning、降 中性 tile（v2.1 强调色克制）、±5% 内持平、上月同期为 0 只给一句说明、老服务器不显示）。 */
export default function MonthCompare({ report: r }: { report: UsageReport }) {
  const lm = r.last_month;
  if (!lm) return null;
  const money = r.priced.length > 0;
  const whole = money ? formatMoney(lm.cost, r.currency) : `${formatTokens(lm.tokens)} token`;
  const d = monthDelta(r);
  if (d === null) {
    const idle = (money ? lm.cost : lm.tokens) <= 0;
    return <div className="usage-note">{idle ? "上月没有用量" : `上月同期没有用量 · 上月全月 ${whole}`}</div>;
  }
  const flat = Math.abs(d) < FLAT_WITHIN;
  const tone = flat ? "flat" : d > 0 ? "up" : "down";
  const pct = d > 9.99 ? `${(d + 1).toFixed(0)} 倍` : `${Math.round(Math.abs(d) * 100)}%`;
  const label = flat ? "与上月同期持平" : `比上月同期${d > 0 ? "多" : "少"} ${pct}`;
  return (
    <div className="month-compare usage-note">
      <span className="month-delta-wrap" role="img" aria-label={label}>
        <span className={`delta-chip delta-${tone}`} aria-hidden>{flat ? "→ 持平" : `${d > 0 ? "↑ +" : "↓ −"}${pct}`}</span>
        <span aria-hidden>比上月同期</span>
      </span>
      <span>· 上月全月 {whole}</span>
    </div>
  );
}

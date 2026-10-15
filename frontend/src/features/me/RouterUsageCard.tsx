import { routerCostLine, routerHeadline, routerLosing, routerNote, routerSimpleShare, routerSplitLine, type RouterUsage } from "../../lib/usage";
import CountUp from "../../ui/CountUp";
import { ListGroup } from "../../ui/kit";

/** 用量页“自动选模型”：本月约省多少（或多花）、两档各走了多少轮（墨色占比条）、分类器花了多少。= App RouterUsageCard；规则在 lib/usage.ts。 */
export default function RouterUsageCard({ usage: u, currency, money }: { usage: RouterUsage; currency: string; money: boolean }) {
  const share = routerSimpleShare(u);
  const pct = Math.round(share * 100);
  const losing = routerLosing(u);
  const head = routerHeadline(u, currency);
  return (
    <ListGroup className="router-usage" label={`自动选模型，${head}，${routerSplitLine(u)}`}>
      <div className="usage-label">自动选模型</div>
      <div className={`usage-big${losing ? " is-losing" : ""}`}><CountUp value={head} /></div>
      <div className="usage-note">{routerSplitLine(u)}</div>
      <div className="meter" role="meter" aria-label={`${u.simple_model || "简单档"}占比`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <span style={{ transform: `scaleX(${share})` }} />
      </div>
      <div className="router-legend"><span>{u.simple_model || "简单档"} {pct}%</span><span>{u.complex_model || "复杂档"} {100 - pct}%</span></div>
      <div className="usage-note">{routerCostLine(u, currency, money)}</div>
      <p className={`router-note${losing ? " is-losing" : ""}`}>{routerNote(u)}</p>
    </ListGroup>
  );
}

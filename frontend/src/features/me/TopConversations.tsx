import { useNavigate } from "react-router-dom";
import { IconChat, IconChevron, IconTrash } from "../../ui/icons";
import { ListGroup } from "../../ui/kit";
import { formatMoney, formatTokens, shareOf, type UsageReport } from "../../lib/usage";

/** 设置页用量卡里“本月最花钱的对话”：点一行跳进那个对话（和收件箱横幅同一条路：/chat + state.open）；已删的只展示。
 *  与 App 的 TopConversationList 同文案同规则。 */
export default function TopConversations({ report: r }: { report: UsageReport }) {
  const nav = useNavigate();
  const money = r.priced.length > 0;
  return (
    <section className="top-convs">
      <div className="usage-label">本月最花钱的对话</div>
      <ListGroup>
        {(r.conversations ?? []).map((c) => {
          const share = shareOf(r, c);
          const inner = <>
            <span className="row-icon" aria-hidden>{c.title === null ? <IconTrash /> : <IconChat />}</span>
            <div className="row-body">
              <div className="row-title">{c.title ?? "已删除的对话"}</div>
              <div className="row-sub">{formatTokens(c.tokens)} token · {c.calls} 次 · 占本月 {Math.round(share * 100)}%</div>
            </div>
            <span className="row-trail"><b>{money ? formatMoney(c.cost, r.currency) : formatTokens(c.tokens)}</b>{c.title !== null && <IconChevron />}</span>
            <div className="meter" aria-hidden><span style={{ transform: `scaleX(${share})` }} /></div>
          </>;
          return c.title === null
            ? <div className="row gone" key={c.id}>{inner}</div>
            : <button className="row" key={c.id} onClick={() => nav("/chat", { state: { open: c.id } })}>{inner}</button>;
        })}
      </ListGroup>
    </section>
  );
}

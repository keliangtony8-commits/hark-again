import { useNavigate } from "react-router-dom";
import { IconChat, IconChevron, IconTrash } from "../../ui/icons";
import { ListGroup } from "../../ui/kit";
import { formatMoney, formatTokens, shareOf, type UsageConversation, type UsageReport } from "../../lib/usage";

type Row = { c: UsageConversation; n: number };

/** 合并后的行：已删的对话（title === null）并成一条（id = "deleted"，calls/tokens/cost 为合计），排在第一个已删对话的位置；其余原样、原序。= App TopConversationList.rowsOf */
export function conversationRows(list: UsageConversation[]): Row[] {
  const gone = list.filter((c) => c.title === null);
  const merged: UsageConversation = {
    id: "deleted", title: null,
    calls: gone.reduce((a, c) => a + c.calls, 0),
    tokens: gone.reduce((a, c) => a + c.tokens, 0),
    cost: gone.reduce((a, c) => a + c.cost, 0),
  };
  const rows: Row[] = [];
  let placed = false;
  for (const c of list) {
    if (c.title !== null) rows.push({ c, n: 1 });
    else if (!placed) { rows.push({ c: merged, n: gone.length }); placed = true; }
  }
  return rows;
}

/** 用量页“本月最花钱的对话”：点一行跳进那个对话（和收件箱横幅同一条路：/chat + state.open）；已删的合并成一行“已删除的对话 N 个”，只展示。
 *  limit = 只露前几行（合并之后数），超出时标题行尾“全部 N 个 ›”进 /me/usage/conversations；不传 = 全量（子页）。与 App 的 TopConversationList 同文案同规则。 */
export default function TopConversations({ report: r, limit, title = true }: { report: UsageReport; limit?: number; title?: boolean }) {
  const nav = useNavigate();
  const money = r.priced.length > 0;
  const list = r.conversations ?? [];
  const rows = conversationRows(list);
  const shown = limit === undefined ? rows : rows.slice(0, limit);
  return (
    <section className="top-convs">
      {title && <div className="section-title"><span>本月最花钱的对话</span>
        {limit !== undefined && rows.length > limit &&
          <button className="btn btn-ghost btn-sm" onClick={() => nav("/me/usage/conversations")}>全部 {list.length} 个 ›</button>}
      </div>}
      <ListGroup>
        {shown.map(({ c, n }) => {
          const share = shareOf(r, c);
          const gone = c.title === null;
          const inner = <>
            <span className="row-icon" aria-hidden>{gone ? <IconTrash /> : <IconChat />}</span>
            <div className="row-body">
              <div className="row-title">{c.title ?? `已删除的对话 ${n} 个`}</div>
              <div className="row-sub">{gone ? "合计 " : ""}{formatTokens(c.tokens)} token · {c.calls} 次 · 占本月 {Math.round(share * 100)}%</div>
            </div>
            <span className="row-trail"><b>{money ? formatMoney(c.cost, r.currency) : formatTokens(c.tokens)}</b>{!gone && <IconChevron />}</span>
            <div className="meter" aria-hidden><span style={{ transform: `scaleX(${share})` }} /></div>
          </>;
          return gone
            ? <div className="row gone" key={c.id}>{inner}</div>
            : <button className="row" key={c.id} onClick={() => nav("/chat", { state: { open: c.id } })}>{inner}</button>;
        })}
      </ListGroup>
    </section>
  );
}

import { useBlockActions } from "./actions";
import { originLabel, originSemantics, relayMeta, relaySemantics } from "../lib/relay";
import type { OriginBlock, RelayBlock as T } from "../lib/types";
import { IconChevron, IconMerge } from "../ui/icons";

/** v2.23 转交卡：助手把一件事交给了另一个项目。整张卡可点 = 打开那个项目里的那段对话（Home 等只读场景不可点、没有箭头）。 */
export function RelayBlock({ block }: { block: T }) {
  const { openConversation } = useBlockActions();
  const body = (
    <>
      <span className="blk-relay-mark" aria-hidden>{block.emoji ?? "📁"}</span>
      <span className="blk-relay-body">
        <span className="blk-relay-title"><IconMerge size={14} />已交给 · {block.name}</span>
        {block.text && <span className="blk-relay-text">{block.text}</span>}
        <span className="blk-relay-meta">{relayMeta(block)}</span>
      </span>
      {openConversation && <span className="blk-relay-go" aria-hidden><IconChevron size={16} /></span>}
    </>
  );
  if (!openConversation || !block.conversation_id) return <div className="card blk-relay" aria-label={relaySemantics(block)}>{body}</div>;
  return (
    <button type="button" className="card blk-relay is-link" aria-label={relaySemantics(block)}
      onClick={() => openConversation(block.conversation_id, block.project_id || null)}>{body}</button>
  );
}

/** v2.23 用户消息里“来自 X”：气泡上方一枚小标签，点一下回到来源那段对话。 */
export function OriginChip({ block }: { block: OriginBlock }) {
  const { openConversation } = useBlockActions();
  const cid = block.conversation_id;
  if (!openConversation || !cid) {
    return <span className="skill-chip is-static" aria-label={originSemantics(block)}><IconMerge size={12} /><span>{originLabel(block)}</span></span>;
  }
  return (
    <button type="button" className="skill-chip" aria-label={originSemantics(block)} title={originSemantics(block)}
      onClick={() => openConversation(cid, block.project_id ?? null)}><IconMerge size={12} /><span>{originLabel(block)}</span></button>
  );
}

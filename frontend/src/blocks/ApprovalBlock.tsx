import { useState } from "react";
import { approvalExtraOptions, approvalGrantedLine, approvalOnHost, approvalSemantics } from "../lib/host";
import type { ApprovalBlock as T } from "../lib/types";
import { IconAlert, IconChat, IconChevron, IconRule, IconServer, IconShield } from "../ui/icons";
import { useBlockActions } from "./actions";

const STATE_TEXT: Record<T["state"], string> = { pending: "等待批准", approved: "已批准", rejected: "已拒绝", expired: "已过期" };

/** 审批卡（= App blocks/interactive_blocks.dart ApprovalBlockView）。
 *  主机命令卡（v1.49 target = host）：服务器图标、“在 <机器> 上，以 root”、note（危险时警示色）、
 *  “拒绝 / 仅这一次”之外的批准范围行（这段对话里都允许 / 以后都允许 X 开头的命令）依次浮入；批准后一句“已选：…”。 */
export default function ApprovalBlock({ block }: { block: T }) {
  const { replyApproval } = useBlockActions();
  const [sent, setSent] = useState(false);
  const pending = block.state === "pending";
  const host = approvalOnHost(block);
  const options = block.options ?? [];
  const granted = approvalGrantedLine(block);
  const reply = (ok: boolean, option?: string) => { setSent(true); replyApproval?.(block.id, ok, option); };
  return (
    <div className={`card blk-approval ${block.state}`} role="group" aria-label={approvalSemantics(block)}>
      <div className="blk-approval-head">
        {host ? <IconServer size={18} /> : <IconShield size={18} />}
        <span className="blk-approval-title">{block.title}
          {host && <span className="blk-approval-where">{block.host ? `在 ${block.host} 上，以 root` : "在服务器本机上，以 root"}</span>}
        </span>
      </div>
      {block.note && (
        <div className={`blk-approval-note${block.warn ? " is-warn" : ""}`}>{block.warn && <IconAlert size={14} />}<span>{block.note}</span></div>
      )}
      <pre className="blk-approval-detail">{block.detail}</pre>
      {pending && replyApproval ? (
        <>
          <div className="blk-approval-actions">
            <button className="btn btn-ghost btn-sm" disabled={sent} onClick={() => reply(false)}>拒绝</button>
            <button className="btn btn-primary btn-sm" disabled={sent} onClick={() => reply(true, options[0]?.id)}>
              {options[0]?.label ?? "批准执行"}</button>
          </div>
          {approvalExtraOptions(block).map((o, i) => (
            <button key={o.id} className="blk-approval-scope enter" style={{ animationDelay: `calc(var(--stagger) * ${i + 1})` }}
              disabled={sent} onClick={() => reply(true, o.id)} aria-label={`批准，${o.label}`}>
              {o.id === "rule" ? <IconRule size={16} /> : <IconChat size={16} />}<span>{o.label}</span><IconChevron size={14} />
            </button>
          ))}
        </>
      ) : (
        <div className="blk-approval-state">{STATE_TEXT[block.state]}{granted && <span className="blk-approval-granted">{granted}</span>}</div>
      )}
    </div>
  );
}

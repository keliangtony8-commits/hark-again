import { useState } from "react";
import type { ApprovalBlock as T } from "../lib/types";
import { IconShield } from "../ui/icons";
import { useBlockActions } from "./actions";

const STATE_TEXT: Record<T["state"], string> = { pending: "等待批准", approved: "已批准", rejected: "已拒绝", expired: "已过期" };

export default function ApprovalBlock({ block }: { block: T }) {
  const { replyApproval } = useBlockActions();
  const [sent, setSent] = useState(false);
  const pending = block.state === "pending";
  return (
    <div className={`card blk-approval ${block.state}`}>
      <div className="blk-approval-head"><IconShield size={18} /><span>{block.title}</span></div>
      <pre className="blk-approval-detail">{block.detail}</pre>
      {pending && replyApproval ? (
        <div className="blk-approval-actions">
          <button className="btn btn-ghost btn-sm" disabled={sent} onClick={() => { setSent(true); replyApproval(block.id, false); }}>拒绝</button>
          <button className="btn btn-primary btn-sm" disabled={sent} onClick={() => { setSent(true); replyApproval(block.id, true); }}>批准执行</button>
        </div>
      ) : (
        <div className="blk-approval-state">{STATE_TEXT[block.state]}</div>
      )}
    </div>
  );
}

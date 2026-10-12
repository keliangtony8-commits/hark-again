import { useEffect, useRef, useState } from "react";
import { planReviewBody, planReviewCollapsedByDefault, planReviewHint, planReviewLabel, planReviewLong, planReviewSemantics } from "../lib/planReview";
import type { PlanReviewBlock as T } from "../lib/types";
import { IconCheck, IconChevronDown, IconMap } from "../ui/icons";
import Markdown from "../ui/Markdown";
import { useBlockActions } from "./actions";

/** 方案卡（v1.71 计划模式，= App blocks/plan_review_block.dart）：标题 + 状态、Markdown 正文（长的先露一截）、
 *  等批准时“再改改 / 批准，开始执行”（approval.reply）；有了结果收成一行，点卡头展开。 */
export default function PlanReviewBlock({ block }: { block: T }) {
  const { replyApproval } = useBlockActions();
  const [sent, setSent] = useState(false);
  const [open, setOpen] = useState(() => !planReviewCollapsedByDefault(block));
  const [full, setFull] = useState(false);
  const wasPending = useRef(block.state === "pending");
  useEffect(() => {
    if (wasPending.current && block.state !== "pending") setOpen(false); // 刚有结果：收起
    wasPending.current = block.state === "pending";
  }, [block.state]);
  const pending = block.state === "pending";
  const collapsible = !pending;
  const shown = open || !collapsible;
  const long = planReviewLong(block);
  const reply = (ok: boolean) => { setSent(true); replyApproval?.(block.id, ok); };
  return (
    <div className={`card blk-review ${block.state}`} role="group" aria-label={planReviewSemantics(block)}>
      <button type="button" className="blk-review-head" disabled={!collapsible} aria-expanded={collapsible ? shown : undefined}
        onClick={() => setOpen((o) => !o)}>
        <span key={String(block.state === "approved")} className="blk-review-icon">
          {block.state === "approved" ? <IconCheck size={18} /> : <IconMap size={18} />}
        </span>
        <span className="blk-review-title">{block.title}
          <span key={block.state} className="blk-review-hint">{planReviewHint(block)}</span>
        </span>
        <span key={`s-${block.state}`} className="blk-review-state">{planReviewLabel(block)}</span>
        {collapsible && <span className={`blk-plan-chev${shown ? " is-open" : ""}`}><IconChevronDown size={16} /></span>}
      </button>
      {shown && (
        <div className="blk-review-body">
          <div className={`blk-review-plan${long && !full ? " is-peek" : ""}`}><Markdown text={planReviewBody(block)} /></div>
          {long && <button type="button" className="btn btn-ghost btn-sm blk-review-more" onClick={() => setFull((f) => !f)}>{full ? "收起" : "展开全部"}</button>}
        </div>
      )}
      {pending && replyApproval && (
        <div className="blk-approval-actions blk-review-actions">
          <button className="btn btn-ghost btn-sm" disabled={sent} onClick={() => reply(false)}>再改改</button>
          <button className="btn btn-primary btn-sm" disabled={sent} onClick={() => reply(true)}>批准，开始执行</button>
        </div>
      )}
    </div>
  );
}

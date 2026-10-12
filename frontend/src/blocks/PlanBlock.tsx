import { useEffect, useRef, useState } from "react";
import { planCollapsedByDefault, planFinished, planProgress, planRatio, planSemantics } from "../lib/plan";
import type { PlanBlock as T, PlanItem } from "../lib/types";
import { IconCheck, IconChevronDown } from "../ui/icons";

/** 计划清单卡（App blocks/plan_block.dart 同一套）：标题 + 进度、进度条、改计划的原因、逐步打勾。
 *  进行中那一步闪点只在这一轮没结束时；全做完且结束 → 收起成一行，点标题展开；清单为空不画。 */
export default function PlanBlock({ block }: { block: T }) {
  const [open, setOpen] = useState(() => !planCollapsedByDefault(block));
  const wasSettled = useRef(!!block.settled);
  useEffect(() => {
    if (!wasSettled.current && planCollapsedByDefault(block)) setOpen(false); // 看着它做完：自动收起
    wasSettled.current = !!block.settled;
  }, [block]);
  if (!block.items?.length) return null;
  const collapsible = planFinished(block);
  const shown = open || !collapsible;
  const progress = planProgress(block);
  return (
    <div className="card blk-plan" role="group" aria-label={planSemantics(block)}>
      <button type="button" className="blk-plan-head" disabled={!collapsible} aria-expanded={collapsible ? shown : undefined}
        onClick={() => setOpen((o) => !o)}>
        <span className="blk-plan-title">计划</span>
        <span key={progress} className="blk-plan-progress">{progress}</span>
        {collapsible && <span className={`blk-plan-chev${shown ? " is-open" : ""}`}><IconChevronDown size={16} /></span>}
      </button>
      {shown && (
        <div className="blk-plan-body" aria-hidden>
          <div className="blk-plan-meter"><span style={{ transform: `scaleX(${planRatio(block)})` }} /></div>
          {block.explanation && <p key={block.explanation} className="blk-plan-why">{block.explanation}</p>}
          <ol className="blk-plan-steps">
            {block.items.map((item, i) => <Step key={item.content} item={item} live={!block.settled} index={i} />)}
          </ol>
        </div>
      )}
    </div>
  );
}

function Step({ item, live, index }: { item: PlanItem; live: boolean; index: number }) {
  const mark = item.status === "completed" ? "done" : item.status === "in_progress" ? (live ? "live" : "now") : "todo";
  return (
    <li className={`blk-plan-step is-${item.status.replace("_", "-")}`} style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}>
      <span key={mark} className={`blk-plan-mark is-${mark}`}>
        {mark === "done" ? <IconCheck size={14} /> : mark === "live" ? <span className="job-dot" /> : null}
      </span>
      <span className="blk-plan-text">{item.content}</span>
    </li>
  );
}

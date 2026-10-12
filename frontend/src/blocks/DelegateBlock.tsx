import { useState } from "react";
import { delegateCanOpen, delegateProgress, delegateSemantics, delegateTaskLine } from "../lib/delegate";
import type { DelegateBlock as T, DelegateTask } from "../lib/types";
import { IconAlert, IconCheck, IconChevronDown, IconClock, IconStop } from "../ui/icons";

/** 子助手卡（App blocks/delegate_block.dart 同一套）：并行的几个子任务各自做到哪；完成的点开看交回的结论。
 *  在做的点只在 live（这一轮还在跑）时闪。 */
export default function DelegateBlock({ block }: { block: T }) {
  if (!block.tasks?.length) return null;
  const progress = delegateProgress(block);
  return (
    <div className="card blk-delegate" role="group" aria-label={delegateSemantics(block)}>
      <div className="blk-delegate-head">
        <span className="blk-delegate-title">子助手</span>
        <span key={progress} className="blk-delegate-progress">{progress}</span>
      </div>
      <ul className="blk-delegate-tasks">
        {block.tasks.map((t, i) => <Task key={t.title} task={t} live={!!block.live} index={i} />)}
      </ul>
    </div>
  );
}

function Task({ task, live, index }: { task: DelegateTask; live: boolean; index: number }) {
  const [open, setOpen] = useState(false);
  const canOpen = delegateCanOpen(task);
  const shown = open && canOpen;
  const line = delegateTaskLine(task);
  const mark = task.state === "running" && live ? "live" : task.state;
  return (
    <li className="blk-delegate-task" style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}>
      <button type="button" className="blk-delegate-row" disabled={!canOpen} aria-expanded={canOpen ? shown : undefined}
        onClick={() => setOpen((o) => !o)}>
        <span key={mark} className={`blk-delegate-mark is-${task.state}`} aria-hidden>
          {mark === "live" ? <span className="job-dot" /> : mark === "done" ? <IconCheck size={14} />
            : mark === "failed" ? <IconAlert size={16} /> : mark === "partial" ? <IconClock size={16} />
            : mark === "stopped" ? <IconStop size={14} /> : null}
        </span>
        <span className="blk-delegate-text">
          <span className="blk-delegate-name">{task.title}</span>
          <span key={line} className={`blk-delegate-line${task.state === "failed" ? " is-bad" : ""}`}>{line}</span>
        </span>
        {canOpen && <span className={`blk-delegate-chev${shown ? " is-open" : ""}`}><IconChevronDown size={16} /></span>}
      </button>
      {shown && <div className="blk-delegate-result">{task.result}</div>}
    </li>
  );
}

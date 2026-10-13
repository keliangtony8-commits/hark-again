import { useState } from "react";
import { delegateCanFollow, delegateFollowTitle, delegateHasResult, delegateProgress, delegateSemantics, delegateTaskLine } from "../lib/delegate";
import type { DelegateBlock as T, DelegateTask } from "../lib/types";
import { IconAlert, IconCheck, IconChevronDown, IconClock, IconStop } from "../ui/icons";
import { useBlockActions } from "./actions";

/** 子助手卡（App blocks/delegate_block.dart 同一套）：并行的几个子任务各自做到哪；完成的点开看交回的结论。
 *  在做的点只在 live（这一轮还在跑）时闪。v1.97：这一轮结束后展开里有“追问”——就地写一句，发出去主助手接着问这个子助手
 *  （电脑上直接在卡里输入，不弹窗；App 是底部弹窗）。 */
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
        {block.tasks.map((t, i) => <Task key={t.title} task={t} block={block} index={i} />)}
      </ul>
    </div>
  );
}

function Task({ task, block, index }: { task: DelegateTask; block: T; index: number }) {
  const [open, setOpen] = useState(false);
  const live = !!block.live;
  const { followUp } = useBlockActions();
  const canFollow = !!followUp && delegateCanFollow(block, task);
  const canOpen = delegateHasResult(task) || canFollow;
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
      {shown && delegateHasResult(task) && <div className="blk-delegate-result">{task.result}</div>}
      {shown && canFollow && <Follow title={task.title} onSend={(text) => followUp!(task.id!, task.title, text)} />}
    </li>
  );
}

function Follow({ title, onSend }: { title: string; onSend: (text: string) => void }) {
  const [writing, setWriting] = useState(false);
  const [text, setText] = useState("");
  const send = () => {
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
    setWriting(false);
  };
  if (!writing) {
    return <button type="button" className="blk-delegate-follow" onClick={() => setWriting(true)}>追问</button>;
  }
  return (
    <div className="blk-delegate-ask">
      <textarea autoFocus rows={2} value={text} aria-label={delegateFollowTitle(title)} placeholder={`${delegateFollowTitle(title)}：它记得自己查过、做过的`}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
          if (e.key === "Escape") setWriting(false);
        }} />
      <div className="blk-delegate-ask-actions">
        <button type="button" className="btn btn-soft" onClick={() => setWriting(false)}>取消</button>
        <button type="button" className="btn btn-primary" disabled={!text.trim()} onClick={send}>发送</button>
      </div>
    </div>
  );
}

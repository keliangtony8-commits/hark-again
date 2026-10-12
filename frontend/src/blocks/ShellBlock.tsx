import { useState } from "react";
import { shellDuration, shellHasMore, shellSemantics, shellStateLabel, shellTail, shellTone } from "../lib/shell";
import type { ShellBlock as T } from "../lib/types";
import { Sheet } from "../ui/kit";
import { IconAlert, IconCheck, IconCopy, IconStop } from "../ui/icons";

/** 用户自己跑的命令卡（输入框 !命令，不经过助手；App blocks/shell_block.dart 同一套）。
 *  样子沿用后台任务卡（blk-job 一家）：状态点 + $ 命令 + 用时 / 输出尾巴 / 一句说明 / 状态词 + 完整输出、复制。 */
export default function ShellBlock({ block: b }: { block: T }) {
  const [full, setFull] = useState(false);
  const [copied, setCopied] = useState(false);
  const tone = shellTone(b.state);
  const tail = shellTail(b.output);
  const empty = b.state === "running" ? "等待输出…" : b.state === "refused" || b.state === "error" ? "（没有执行）" : "（没有输出）";
  const label = shellStateLabel(b);
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className={`card blk-job blk-shell tone-${tone}`} role="group" aria-label={shellSemantics(b)}>
      <div className="blk-job-head" aria-hidden>
        <span key={tone} className="blk-job-mark">
          {tone === "running" ? <i className="job-dot" /> : tone === "ok" ? <IconCheck size={16} /> : tone === "problem" ? <IconAlert size={16} /> : <IconStop size={14} />}
        </span>
        <span className="blk-shell-cmd">$ {b.command}</span>
        <span key={String(b.seconds == null)} className="blk-job-time blk-shell-time">{shellDuration(b.seconds)}</span>
      </div>
      <pre className={`blk-job-log ${tail ? "" : "is-empty"}`} aria-hidden>{tail || empty}</pre>
      {b.note && <p key={b.note} className="blk-job-reason" aria-hidden>{b.note}</p>}
      <div className="blk-job-foot">
        <span key={label} className="blk-job-state">{label}</span>
        {b.state !== "running" && (
          <span className="blk-shell-actions">
            {shellHasMore(b.output) && <button className="btn btn-ghost btn-sm" onClick={() => setFull(true)}>完整输出</button>}
            <button className="icon-btn sm" onClick={() => copy(`$ ${b.command}\n${b.output.replace(/\s+$/, "")}`)} aria-label="复制命令和输出" title="复制命令和输出">
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            </button>
          </span>
        )}
      </div>
      {full && (
        <Sheet title={`$ ${b.command}`} onClose={() => setFull(false)}
          actions={<button className="btn btn-ghost" onClick={() => copy(b.output)}>{copied ? <IconCheck size={16} /> : <IconCopy />}{copied ? "已复制" : "复制输出"}</button>}>
          <p className="blk-job-sheet-meta">{[label, shellDuration(b.seconds)].filter(Boolean).join(" · ")}</p>
          <pre className="blk-job-full">{b.output.trim() ? b.output.replace(/\s+$/, "") : "（没有输出）"}</pre>
        </Sheet>
      )}
    </div>
  );
}

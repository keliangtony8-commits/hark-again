import { useState } from "react";
import { type ChangesScope, changeTag, changesConfirm, changesNote, changesSemantics, changesTitle, changesTotals, changesUndoable } from "../lib/changes";
import type { ChangesBlock as T } from "../lib/types";
import { confirmDialog } from "../ui/dialog";
import { FileDiffRow } from "../ui/Diff";
import { IconDoc, IconRefresh } from "../ui/icons";
import { useBlockActions } from "./actions";

/** 改动卡（v1.68，= App blocks/changes_block.dart）：这一轮改过的文件，每个一份净 diff，可整轮撤销（先确认）。 */
export default function ChangesBlock({ block }: { block: T }) {
  const { undoChanges } = useBlockActions();
  if (!block.files.length) return null;
  return <ChangesPanel block={block} className="card" onUndo={undoChanges ? () => undoChanges(block.token) : undefined} />;
}

/** 改动列表本体（v2.18 拆出来：后台任务卡里嵌同一块，scope = job）。onUndo 返回 null = 成功，否则是原因。 */
export function ChangesPanel({ block, onUndo, scope = "turn", className = "" }: {
  block: T; onUndo?: () => Promise<string | null>; scope?: ChangesScope; className?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!block.files.length) return null;
  const [added, removed] = changesTotals(block);
  const note = error ?? changesNote(block, scope);
  const canUndo = changesUndoable(block) && !!onUndo;
  const title = changesTitle(block, scope);

  const undo = async () => {
    if (!onUndo) return;
    const ok = await confirmDialog({ ...changesConfirm(block, scope), action: "撤销" });
    if (!ok) return;
    setBusy(true); setError(null);
    setError(await onUndo());
    setBusy(false);
  };

  return (
    <div className={`${className} blk-changes ${scope === "job" ? "is-embedded" : ""} ${block.undone ? "is-undone" : ""}`} role="group" aria-label={changesSemantics(block, scope)}>
      <div className="blk-changes-head">
        <span key={String(!!block.undone)} className="blk-changes-icon">{block.undone ? <IconRefresh size={16} /> : <IconDoc size={16} />}</span>
        <span key={title} className="blk-changes-title">{title}</span>
        {!block.undone && (
          <span className="step-change"><span className="diff-add">+{added}</span>{removed > 0 && <span className="diff-remove">−{removed}</span>}</span>
        )}
        {canUndo && <button className="btn btn-ghost btn-sm fade-in" disabled={busy} onClick={undo}>{busy ? "撤销中…" : "撤销"}</button>}
      </div>
      <ul className="file-diff-list">
        {block.files.map((f, i) => (
          <FileDiffRow key={f.path} c={f} i={i} tag={changeTag(f)} open={open === f.path}
            onToggle={() => setOpen(open === f.path ? null : f.path)} />
        ))}
      </ul>
      {!!block.more && <div className="blk-changes-note">还有 {block.more} 个文件</div>}
      {note && <div key={note} className={`blk-changes-note ${error ? "is-error" : ""}`}>{note}</div>}
    </div>
  );
}

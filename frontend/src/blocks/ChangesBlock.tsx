import { useState } from "react";
import { changeTag, changesCount, changesNote, changesSemantics, changesTitle, changesTotals, changesUndoable } from "../lib/changes";
import type { ChangesBlock as T } from "../lib/types";
import { confirmDialog } from "../ui/dialog";
import { Diff, DiffStat } from "../ui/Diff";
import { IconChevron, IconDoc, IconRefresh } from "../ui/icons";
import { useBlockActions } from "./actions";

/** 改动卡（v1.68，= App blocks/changes_block.dart）：这一轮改过的文件，每个一份净 diff，可整轮撤销（先确认）。 */
export default function ChangesBlock({ block }: { block: T }) {
  const { undoChanges } = useBlockActions();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!block.files.length) return null;
  const [added, removed] = changesTotals(block);
  const note = error ?? changesNote(block);
  const canUndo = changesUndoable(block) && !!undoChanges;

  const undo = async () => {
    if (!undoChanges) return;
    const ok = await confirmDialog({
      title: "撤销这一轮的文件改动？",
      text: `${changesCount(block)} 个文件会回到助手改之前的样子；这一轮新建的文件会被删掉。`,
      action: "撤销",
    });
    if (!ok) return;
    setBusy(true); setError(null);
    setError(await undoChanges(block.token));
    setBusy(false);
  };

  return (
    <div className={`card blk-changes ${block.undone ? "is-undone" : ""}`} role="group" aria-label={changesSemantics(block)}>
      <div className="blk-changes-head">
        <span key={String(!!block.undone)} className="blk-changes-icon">{block.undone ? <IconRefresh size={16} /> : <IconDoc size={16} />}</span>
        <span key={changesTitle(block)} className="blk-changes-title">{changesTitle(block)}</span>
        {!block.undone && (
          <span className="step-change"><span className="diff-add">+{added}</span>{removed > 0 && <span className="diff-remove">−{removed}</span>}</span>
        )}
        {canUndo && <button className="btn btn-ghost btn-sm fade-in" disabled={busy} onClick={undo}>{busy ? "撤销中…" : "撤销"}</button>}
      </div>
      <ul className="blk-changes-files">
        {block.files.map((f, i) => {
          const tag = changeTag(f);
          const can = !!f.diff;
          const line = (
            <>
              <code className="blk-changes-path" title={f.path}>{f.path}</code>
              <span className="step-change">{tag ? <span className="step-new">{tag}</span> : <DiffStat c={f} />}{can && <IconChevron size={12} />}</span>
            </>
          );
          return (
            <li key={f.path} className="blk-changes-file" style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
              {can ? (
                <button type="button" className={`blk-changes-line step-toggle ${open === f.path ? "open" : ""}`} aria-expanded={open === f.path}
                  onClick={() => setOpen(open === f.path ? null : f.path)}>{line}</button>
              ) : <div className="blk-changes-line">{line}</div>}
              {open === f.path && <Diff c={f} />}
            </li>
          );
        })}
      </ul>
      {!!block.more && <div className="blk-changes-note">还有 {block.more} 个文件</div>}
      {note && <div key={note} className={`blk-changes-note ${error ? "is-error" : ""}`}>{note}</div>}
    </div>
  );
}

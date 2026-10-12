import { changeLabel, changeSemantics, diffLines } from "../lib/activity";
import type { FileChange } from "../lib/types";
import { IconChevron } from "./icons";

/** 文件改动的小部件（v1.68 从活动时间线抽出，时间线一步 + 改动卡共用；= App ui/diff_view.dart）。样式在 ui.css。
 *  FileDiffRow：一行文件（v1.69 从改动卡抽出，apply_patch 一步改几个文件时时间线也用它）。 */
export function DiffStat({ c }: { c: FileChange }) {
  return (
    <>
      {c.created && <span className="step-new">新建</span>}
      {c.moved_from && <span className="step-new">改名</span>}
      <span className="diff-add">+{c.added}</span>
      {c.removed > 0 && <span className="diff-remove">−{c.removed}</span>}
    </>
  );
}

export function Diff({ c }: { c: FileChange }) {
  return (
    <pre className="step-diff" aria-label={`${c.path} 的改动`}>
      {diffLines(c.diff).map(([kind, text], i) => <span key={i} className={`diff-${kind}`}>{text || " "}{"\n"}</span>)}
    </pre>
  );
}

/** 一个文件一行：路径（改名写 “旧 → 新”；父级 .is-undone 时划掉）+ tag 或 “+N −M” + 可展开 diff。展开状态由外面管。 */
export function FileDiffRow({ c, i, open, onToggle, tag }: { c: FileChange; i: number; open: boolean; onToggle: () => void; tag?: string | null }) {
  const label = changeLabel(c);
  const can = !!c.diff;
  const line = (
    <>
      <code className="file-diff-path" title={label}>{label}</code>
      <span className="step-change">{tag ? <span className="step-new">{tag}</span> : <DiffStat c={c} />}{can && <IconChevron size={12} />}</span>
    </>
  );
  return (
    <li className="file-diff-row" style={{ animationDelay: `calc(${Math.min(i, 10)} * var(--stagger))` }}>
      {can ? (
        <button type="button" className={`file-diff-line step-toggle ${open ? "open" : ""}`} aria-expanded={open}
          aria-label={`${label}，${tag ?? changeSemantics(c)}`} onClick={onToggle}>{line}</button>
      ) : <div className="file-diff-line" role="group" aria-label={`${label}，${tag ?? changeSemantics(c)}`}>{line}</div>}
      {open && <Diff c={c} />}
    </li>
  );
}

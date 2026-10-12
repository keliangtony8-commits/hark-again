import { diffLines } from "../lib/activity";
import type { FileChange } from "../lib/types";

/** 文件改动的两件小部件（v1.68 从活动时间线抽出，时间线一步 + 改动卡共用；= App ui/diff_view.dart）。样式在 ui.css。 */
export function DiffStat({ c }: { c: FileChange }) {
  return (
    <>
      {c.created && <span className="step-new">新建</span>}
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

import type { ProjectFile } from "../../lib/types";
import { IconFile } from "../../ui/icons";
import { stagger } from "../../ui/kit";
import { projectFileLine } from "../projects/projectHome";

/** 输入框顶部的 @ 候选（和编辑条 / 命令条同一个位置）：↑↓ 选、Enter/Tab 补全、Esc 收起由 Composer 处理。
 *  files = null 表示还在读文件列表。 */
export default function MentionList({ files, active, onPick, onHover }: {
  files: ProjectFile[] | null; active: number; onPick: (f: ProjectFile) => void; onHover: (i: number) => void;
}) {
  if (!files || files.length === 0) {
    return <div className="edit-bar mention-empty"><span>{files ? "没有对得上的文件 · 发出去我也会按名字再找一次" : "正在找文件…"}</span></div>;
  }
  return (
    <ul className="mention-list" role="listbox" aria-label="引用文件">
      {files.map((f, i) => (
        <li key={f.path} role="option" aria-selected={i === active} className={`mention-item ${i === active ? "on" : ""}`} style={stagger(i)}
          onMouseDown={(e) => { e.preventDefault(); onPick(f); }} onMouseEnter={() => onHover(i)}>
          <IconFile size={14} />
          <span className="mention-name">{f.name}</span>
          <span className="mention-sub">{projectFileLine(f)}</span>
        </li>
      ))}
    </ul>
  );
}

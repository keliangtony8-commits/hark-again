import type { ReactNode } from "react";
import { stagger } from "../../ui/kit";

/** 候选条里的一行：文件（@）和技能（$）共用。 */
export type MentionItem = { key: string; icon: ReactNode; title: string; sub: string };

/** 输入框顶部的 @ / $ 候选（和编辑条 / 命令条同一个位置）：↑↓ 选、Enter/Tab 补全、Esc 收起由 Composer 处理。
 *  items = null 表示还在读列表；为空时显示 empty。 */
export default function MentionList({ items, active, label, empty, loading, onPick, onHover }: {
  items: MentionItem[] | null; active: number; label: string; empty: string; loading: string;
  onPick: (key: string) => void; onHover: (i: number) => void;
}) {
  if (!items || items.length === 0) {
    return <div className="edit-bar mention-empty"><span>{items ? empty : loading}</span></div>;
  }
  return (
    <ul className="mention-list" role="listbox" aria-label={label}>
      {items.map((it, i) => (
        <li key={it.key} role="option" aria-selected={i === active} className={`mention-item ${i === active ? "on" : ""}`} style={stagger(i)}
          onMouseDown={(e) => { e.preventDefault(); onPick(it.key); }} onMouseEnter={() => onHover(i)}>
          {it.icon}
          <span className="mention-name">{it.title}</span>
          <span className="mention-sub">{it.sub}</span>
        </li>
      ))}
    </ul>
  );
}

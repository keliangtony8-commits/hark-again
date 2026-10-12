import { useEffect, useMemo, useRef, useState } from "react";
import type { Conversations } from "../../hooks/useConversations";
import { groupConversations } from "../../lib/history";
import type { ConversationSummary } from "../../lib/types";
import { IconClose, IconDownload, IconEdit, IconGlobe, IconMore, IconPin, IconPlus, IconSearch, IconTrash, IconFolder } from "../../ui/icons";
import { Highlight, Menu, SearchField } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";
import ConversationFilesSheet from "./ConversationFilesSheet";
import ShareSheet from "./ShareSheet";

type Props = {
  title: string;
  list: Conversations;
  activeId: string | null;
  /** focus：搜索命中正文时那条消息的 id，打开后定位过去。 */
  onOpen: (id: string | null, focus?: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
};

/**
 * 对话历史：搜索框 + 分组列表（置顶 / 今天 / …）+ 每行菜单（置顶、改名、全部文件、分享为网页、导出、删除）。
 * 桌面是常驻侧栏，移动端是抽屉——同一个组件，CSS 决定形态。数据全在 useConversations。
 */
export default function ConversationList({ title, list, activeId, onOpen, onDelete, onClose }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [sharing, setSharing] = useState<string | null>(null);
  const [files, setFiles] = useState<string | null>(null);
  const q = list.query.trim();
  // 搜索时按相关度（服务端顺序）平铺；平时按时间分组
  const groups = useMemo(
    () => (q ? [{ label: list.searching ? "搜索中…" : `${list.items.length} 个结果`, items: list.items }] : groupConversations(list.items)),
    [q, list.items, list.searching],
  );

  return (
    <aside className="convs glass-drawer" aria-label="对话历史">
      <div className="convs-head">
        <span className="convs-title">{title}</span>
        <button className="icon-btn mobile-only" onClick={onClose} aria-label="关闭"><IconClose /></button>
      </div>
      <button className="new-chat" onClick={() => onOpen(null)}><IconPlus />新对话</button>
      <SearchField className="conv-search" value={list.query} onChange={list.setQuery} placeholder="搜索标题和内容" />
      <nav className="conv-list">
        {groups.map((g) => (
          <div key={g.label} className="conv-group">
            <div className="conv-label">{g.label}</div>
            {g.items.map((c, i) => (
              <ConversationRow key={c.id} c={c} q={q} index={i} active={c.id === activeId} editing={editing === c.id}
                onOpen={() => onOpen(c.id, c.message_id)}
                onEdit={(on) => setEditing(on ? c.id : null)}
                onRename={(t) => { setEditing(null); list.rename(c.id, t); }}
                onPin={() => list.setPinned(c.id, !c.pinned)}
                onShare={() => setSharing(c.id)}
                onFiles={() => setFiles(c.id)}
                onExport={() => list.exportMarkdown(c)}
                onDelete={async () => { if (await confirmDialog({ title: `删除「${c.title}」？`, text: "整段对话会一起删除。" })) onDelete(c.id); }} />
            ))}
          </div>
        ))}
        {q && !list.searching && list.items.length === 0 && <div className="conv-empty">没有找到「{q}」</div>}
      </nav>
      {files && <ConversationFilesSheet conversationId={files} onClose={() => setFiles(null)} />}
      {sharing && <ShareSheet conversationId={sharing} onClose={() => setSharing(null)} />}
    </aside>
  );
}

type RowProps = {
  c: ConversationSummary; q: string; index: number; active: boolean; editing: boolean;
  onOpen: () => void; onEdit: (on: boolean) => void; onRename: (t: string) => void; onPin: () => void; onShare: () => void; onFiles: () => void; onExport: () => void; onDelete: () => void;
};

function ConversationRow({ c, q, index, active, editing, onOpen, onEdit, onRename, onPin, onShare, onFiles, onExport, onDelete }: RowProps) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) input.current?.select(); }, [editing]);

  if (editing) {
    return (
      <div className="conv-item editing">
        <input ref={input} className="conv-rename" defaultValue={c.title} aria-label="新标题"
          onKeyDown={(e) => {
            if (e.key === "Enter") onRename(e.currentTarget.value);
            if (e.key === "Escape") onEdit(false);
          }}
          onBlur={(e) => onRename(e.currentTarget.value)} />
      </div>
    );
  }
  return (
    <div className={`conv-item ${active ? "active" : ""}`} role="button" onClick={onOpen}
      style={{ animationDelay: `calc(var(--stagger) * ${Math.min(index, 8)})` }}>
      <div className="conv-body">
        <span className="conv-title">{c.pinned && <span className="conv-pin"><IconPin size={12} /></span>}<Highlight text={c.title} q={q} /></span>
        {c.snippet && <span className="conv-snippet"><Highlight text={c.snippet} q={q} /></span>}
      </div>
      <Menu trigger={<IconMore />} items={[
        { label: c.pinned ? "取消置顶" : "置顶", icon: <IconPin />, onSelect: onPin },
        { label: "重命名", icon: <IconEdit />, onSelect: () => onEdit(true) },
        { label: "全部文件", icon: <IconFolder />, onSelect: onFiles },
        { label: "分享为网页", icon: <IconGlobe />, onSelect: onShare },
        { label: "导出 Markdown", icon: <IconDownload />, onSelect: onExport },
        { label: "删除", icon: <IconTrash />, danger: true, onSelect: onDelete },
      ]} />
    </div>
  );
}

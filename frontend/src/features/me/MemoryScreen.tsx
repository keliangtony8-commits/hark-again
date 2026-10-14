import { useState } from "react";
import { categoryCounts, categoryLabel, filterMemories, MEMORY_CATEGORIES, MEMORY_SEARCH_FROM, MEMORY_STARTERS, memorySummary } from "../../lib/memory";
import { formatWhen } from "../../lib/format";
import { useMemories } from "../../lib/memoryStore";
import type { Memory } from "../../lib/types";
import { IconPlus, IconSearch } from "../../ui/icons";
import { Highlight, Hint, Page, PageHeader, PageIntro, SearchField, Section, Sheet, Skeleton, StarterCard, stagger } from "../../ui/kit";
import MemoryDigestCard from "./MemoryDigestCard";
import { filterNotes, useMemoryNotes } from "../../lib/memoryNotes";
import { MemoryNotesSection, NoteSheet } from "./MemoryNotes";

/** 记忆：页头摘要 →（空时起步卡）→ 概括卡 → 搜索（≥7 条，笔记也算）→ 分类筛选 → 主题笔记（v2.21，MemoryNotes.tsx）→ 按分类分组带数量。
 *  与 App MemoryScreen 同版式，筛选规则在 lib/memory.ts / lib/memoryNotes.ts；“+”选一句话记忆或主题笔记。 */
export default function MemoryScreen() {
  const mem = useMemories(); // 与聊天里的记忆卡共用一份列表（lib/memoryStore.ts）
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<Memory> | null>(null);
  const notes = useMemoryNotes();
  const [adding, setAdding] = useState(false); // “+”的二选一
  const [newNote, setNewNote] = useState(false);

  const counts = categoryCounts(mem.items);
  const category = counts.some(([c]) => c === filter) ? filter : null; // 选中的分类删空了就回到全部
  const groups = filterMemories(mem.items, query, category);
  const noteHits = category ? [] : filterNotes(notes.items, query);
  const empty = mem.items.length === 0 && notes.items.length === 0;
  let n = 0; // 整页错峰序号（封顶 10）
  const firstWord = query.trim().split(/\s+/)[0] ?? "";

  const save = async () => {
    if (!editing?.content?.trim()) return;
    const body = { content: editing.content.trim(), category: editing.category ?? "general" };
    if (editing.id) await mem.update(editing.id, body); else await mem.create(body);
    setEditing(null);
  };
  const pickable = [...new Set([...Object.keys(MEMORY_CATEGORIES), editing?.category ?? "general"])];

  return (
    <Page header={<PageHeader title="记忆" back action={
      <button className="icon-btn" onClick={() => setAdding(true)} aria-label="添加"><IconPlus /></button>} />}>
      <PageIntro loading={!mem.loaded} summary={memorySummary(mem.items, notes.items.length)}
        line="每次对话我都会参考这些内容。聊天中我会自动记录；有误可直接修改，不需要的可删除。" />
      {!mem.loaded ? <Skeleton /> : empty ? (
        <StarterCard title="还没有记忆" text="聊天时说“记住我不吃辣”我就会记下来，也可以先告诉我几件事。">
          {MEMORY_STARTERS.map((s) => (
            <button key={s.label} className="btn btn-ghost" onClick={() => setEditing({ content: s.content, category: s.category })}><IconPlus size={16} />{s.label}</button>
          ))}
          <button className="btn btn-ghost" onClick={() => setNewNote(true)}><IconPlus size={16} />记一个人</button>
        </StarterCard>
      ) : (<>
        <MemoryDigestCard version={mem.items} />
        {(mem.items.length + notes.items.length >= MEMORY_SEARCH_FROM || query) && <SearchField className="memory-search" value={query} onChange={setQuery} placeholder="搜索记忆" />}
        {counts.length > 1 && (
          <div className="seg" role="group" aria-label="按分类筛选">
            <button className={`chip ${!category ? "on" : ""}`} aria-pressed={!category} onClick={() => setFilter(null)}>全部 {mem.items.length}</button>
            {counts.map(([c, n]) => (
              <button key={c} className={`chip ${category === c ? "on" : ""}`} aria-pressed={category === c}
                onClick={() => setFilter(category === c ? null : c)}>{categoryLabel(c)} {n}</button>
            ))}
          </div>
        )}
        {!category && <MemoryNotesSection query={query} />}
        {groups.length === 0 && noteHits.length === 0 && !(mem.items.length === 0 && !query) ? (
          <Hint icon={<IconSearch size={26} />} title="没有匹配的记忆" text="未找到结果，可更换关键词或查看全部分类。"
            action={<button className="btn btn-ghost" onClick={() => { setQuery(""); setFilter(null); }}>清除筛选</button>} />
        ) : groups.map(([cat, items]) => (
          <Section key={cat} title={`${categoryLabel(cat)} · ${items.length}`}>
            <div className="list">
              {items.map((m) => (
                <button key={m.id} className="row memory-row enter" style={stagger(Math.min(++n, 10))} onClick={() => setEditing(m)}>
                  <div className="row-body">
                    <div className="row-title"><Highlight text={m.content} q={firstWord} /></div>
                    {m.updated_at && <div className="row-sub">{formatWhen(m.updated_at)}</div>}
                  </div>
                </button>
              ))}
            </div>
          </Section>
        ))}
      </>)}
      {adding && (
        <Sheet title="新增" onClose={() => setAdding(false)}>
          <div className="list">
            <button className="row" onClick={() => { setAdding(false); setEditing({ category: category ?? "general", content: "" }); }}>
              <div className="row-body"><div className="row-title">一句话记忆</div><div className="row-sub">一条偏好或事实，比如“我对花生过敏”</div></div></button>
            <button className="row" onClick={() => { setAdding(false); setNewNote(true); }}>
              <div className="row-body"><div className="row-title">主题笔记</div><div className="row-sub">关于一个人、地方或项目的一串细节</div></div></button>
          </div>
        </Sheet>
      )}
      {newNote && <NoteSheet note={null} onClose={() => setNewNote(false)} />}
      {editing && (
        <Sheet title={editing.id ? "编辑记忆" : "添加记忆"} onClose={() => setEditing(null)} actions={<>
          {editing.id && <button className="btn btn-danger push-left" onClick={async () => { await mem.remove(editing.id!); setEditing(null); }}>忘掉这条</button>}
          <button className="btn btn-ghost" onClick={() => setEditing(null)}>取消</button>
          <button className="btn btn-primary" disabled={!editing.content?.trim()} onClick={save}>保存</button>
        </>}>
          <label className="form-field"><span>内容</span>
            <textarea value={editing.content ?? ""} autoFocus placeholder="比如：不吃香菜；早上 8 点前别打扰"
              onChange={(e) => setEditing({ ...editing, content: e.target.value })} /></label>
          <div className="form-field"><span>分类</span>
            <div className="seg" role="radiogroup" aria-label="分类">
              {pickable.map((k) => (
                <button key={k} role="radio" aria-checked={(editing.category ?? "general") === k}
                  className={`chip ${(editing.category ?? "general") === k ? "on" : ""}`}
                  onClick={() => setEditing({ ...editing, category: k })}>{categoryLabel(k)}</button>
              ))}
            </div></div>
        </Sheet>
      )}
    </Page>
  );
}

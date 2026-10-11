import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { categoryCounts, categoryLabel, filterMemories, MEMORY_CATEGORIES } from "../../lib/memory";
import { formatWhen } from "../../lib/format";
import type { Memory } from "../../lib/types";
import { IconBrain, IconPlus, IconSearch } from "../../ui/icons";
import { Highlight, Hint, Page, PageHeader, SearchField, Sheet, Skeleton } from "../../ui/kit";
import MemoryDigestCard from "./MemoryDigestCard";

/** 记忆：概括卡 → 搜索 → 分类筛选 → 按分类分组。与 App MemoryScreen 同版式，筛选规则在 lib/memory.ts。 */
export default function MemoryScreen() {
  const mem = useResource<Memory>("/api/memories");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<Memory> | null>(null);

  const counts = categoryCounts(mem.items);
  const category = counts.some(([c]) => c === filter) ? filter : null; // 选中的分类删空了就回到全部
  const groups = filterMemories(mem.items, query, category);
  const filtering = !!query.trim() || !!category;
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
      <button className="icon-btn" onClick={() => setEditing({ category: category ?? "general", content: "" })} aria-label="添加"><IconPlus /></button>} />}>
      <p className="desc">每次对话我都会参考这些。说错了就改，不想让我记的直接删。</p>
      <MemoryDigestCard version={mem.items} />
      {mem.loading ? <Skeleton /> : mem.items.length === 0 ? (
        <Hint icon={<IconBrain size={26} />} title="还没有记忆" text="聊天时我会自动记下你的偏好，你也可以手动添加。" />
      ) : (<>
        <SearchField className="memory-search" value={query} onChange={setQuery} placeholder="搜索记忆" />
        {counts.length > 1 && (
          <div className="seg" role="group" aria-label="按分类筛选">
            <button className={`chip ${!category ? "on" : ""}`} aria-pressed={!category} onClick={() => setFilter(null)}>全部 {mem.items.length}</button>
            {counts.map(([c, n]) => (
              <button key={c} className={`chip ${category === c ? "on" : ""}`} aria-pressed={category === c}
                onClick={() => setFilter(category === c ? null : c)}>{categoryLabel(c)} {n}</button>
            ))}
          </div>
        )}
        {groups.length === 0 ? (
          <Hint icon={<IconSearch size={26} />} title="没有匹配的记忆" text="换个词，或者看看全部分类。"
            action={<button className="btn btn-ghost" onClick={() => { setQuery(""); setFilter(null); }}>清除筛选</button>} />
        ) : groups.map(([cat, items]) => (
          <div key={cat} className="memory-group">
            <div className="section-title">{categoryLabel(cat)}{filtering && <span>{items.length}</span>}</div>
            <div className="list">
              {items.map((m, i) => (
                <button key={m.id} className="row memory-row" style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }} onClick={() => setEditing(m)}>
                  <div className="row-body">
                    <div className="row-title"><Highlight text={m.content} q={firstWord} /></div>
                    {m.updated_at && <div className="row-sub">{formatWhen(m.updated_at)}</div>}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </>)}
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

import { useState } from "react";
import { formatWhen } from "../../lib/format";
import { filterNotes, NOTE_KINDS, noteKindLabel, notePathPreview, noteSubtitle, useMemoryNotes } from "../../lib/memoryNotes";
import type { MemoryNote } from "../../lib/types";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconFile, IconPlace, IconUser } from "../../ui/icons";
import { Highlight, ListGroup, ListRow, Section, Sheet } from "../../ui/kit";
import Markdown from "../../ui/Markdown";

/** 记忆笔记（v2.21）：记忆页里的“主题笔记”一节 + 一篇笔记的阅读 / 编辑弹层。与 App features/me/memory_notes.dart 同规则：
 *  阅读态渲染 Markdown，“编辑”切到表单（类别 / 名字 / 标题 / 正文），只有真改了才能保存，带着改动关掉先确认；名字只填一段时预览会存成的路径。 */
const kindIcon = (k: string) => (k === "contact" ? <IconUser size={18} /> : k === "place" ? <IconPlace size={18} /> : <IconFile size={18} />);

export function MemoryNotesSection({ query, from = 1 }: { query: string; from?: number }) {
  const notes = useMemoryNotes();
  const [open, setOpen] = useState<MemoryNote | null>(null);
  const shown = filterNotes(notes.items, query);
  const firstWord = query.trim().split(/\s+/)[0] ?? "";
  return (
    <>
      {shown.length > 0 && (
        <Section title={`主题笔记 · ${shown.length}`}>
          <ListGroup>
            {shown.map((n, i) => (
              <ListRow key={n.id} className="memory-row note-row" enter={Math.min(from + i, 10)} onClick={() => setOpen(n)}
                label={`笔记 ${n.title}，${noteKindLabel(n.kind)}`} icon={kindIcon(n.kind)}
                title={<Highlight text={n.title} q={firstWord} />} sub={noteSubtitle(n)} />
            ))}
          </ListGroup>
        </Section>
      )}
      {open && <NoteSheet note={open} onClose={() => setOpen(null)} />}
    </>
  );
}

/** note = null → 新建。 */
export function NoteSheet({ note, onClose }: { note: MemoryNote | null; onClose: () => void }) {
  const store = useMemoryNotes();
  const live = note ? store.items.find((n) => n.id === note.id) ?? note : null; // 列表刷新（助手刚改过）时阅读态跟着换
  const [editing, setEditing] = useState(note === null);
  const [form, setForm] = useState(() => ({ path: note?.path ?? "", title: note?.title ?? "", kind: note?.kind ?? "contact", body: note?.body ?? "" }));
  const [busy, setBusy] = useState(false);
  const dirty = live
    ? form.path.trim() !== live.path || form.title.trim() !== live.title || form.kind !== live.kind || form.body !== live.body
    : form.path.trim() !== "" || form.body !== "";
  const canSave = editing && dirty && form.path.trim() !== "" && !busy;
  const preview = notePathPreview(form.path, form.kind);
  const fill = (n: MemoryNote) => setForm({ path: n.path, title: n.title, kind: n.kind, body: n.body });

  const run = async (op: () => Promise<void>) => {
    setBusy(true);
    try { await op(); } catch (e) { await noticeDialog("没有保存", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const save = () => run(async () => {
    const title = form.title.trim();
    if (!live) {
      await store.create({ path: form.path.trim(), kind: form.kind, body: form.body, ...(title ? { title } : {}) });
      onClose();
      return;
    }
    const body: Partial<MemoryNote> = {};
    if (form.path.trim() !== live.path) body.path = form.path.trim();
    if (title !== live.title) body.title = title;
    if (form.kind !== live.kind) body.kind = form.kind;
    if (form.body !== live.body) body.body = form.body;
    fill(await store.update(live.id, body));
    setEditing(false);
  });
  const remove = async () => {
    if (!live || !(await confirmDialog({ title: `删除笔记「${live.title}」？`, text: "整篇内容都会删掉，我以后也看不到它。" }))) return;
    await run(async () => { await store.remove(live.id); onClose(); });
  };
  const leave = async (after: () => void) => {
    if (editing && dirty && !(await confirmDialog({ title: "放弃没保存的改动？", text: "刚才改的内容不会保存。", action: "放弃" }))) return;
    after();
  };
  const cancel = () => leave(() => { if (!live) onClose(); else { fill(live); setEditing(false); } });

  return (
    <Sheet title={!live ? "新笔记" : editing ? "编辑笔记" : "笔记"} onClose={() => void leave(onClose)} actions={editing ? <>
      <button className="btn btn-ghost" onClick={cancel} disabled={busy}>取消</button>
      <button className="btn btn-primary" disabled={!canSave} onClick={save}>保存</button>
    </> : <>
      <button className="btn btn-danger push-left" onClick={remove} disabled={busy}>删除</button>
      <button className="btn btn-primary" onClick={() => { if (live) fill(live); setEditing(true); }}>编辑</button>
    </>}>
      {!editing && live ? (
        <div className="note-read enter">
          <div className="note-head">
            <strong className="note-title">{live.title}</strong>
            <div className="note-meta">
              <span className="note-kind">{noteKindLabel(live.kind)}</span>
              <span>{live.path}</span>
              {live.updated_at && <span>更新于 {formatWhen(live.updated_at)}</span>}
            </div>
          </div>
          <div className="note-body">{live.body.trim() ? <Markdown text={live.body} /> : <p className="note-empty">还没写内容。点“编辑”补上，或在聊天里告诉我。</p>}</div>
          <p className="note-foot">聊天时我会自己补充这篇；说错了就在这里改。</p>
        </div>
      ) : (
        <div className="note-form enter">
          <div className="form-field"><span>类别</span>
            <div className="seg" role="radiogroup" aria-label="类别">
              {Object.keys(NOTE_KINDS).map((k) => (
                <button key={k} role="radio" aria-checked={form.kind === k} className={`chip ${form.kind === k ? "on" : ""}`}
                  onClick={() => setForm({ ...form, kind: k })}>{noteKindLabel(k)}</button>
              ))}
            </div></div>
          <label className="form-field"><span>名字</span>
            <input value={form.path} autoFocus={!live} placeholder="比如：妈妈、学校、考研计划" onChange={(e) => setForm({ ...form, path: e.target.value })} />
            {form.path.trim() && preview !== form.path.trim() && <small key={preview} className="note-preview">会存成 {preview}</small>}
          </label>
          <label className="form-field"><span>标题（可不填）</span>
            <input value={form.title} placeholder="默认和名字一样" onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="form-field"><span>内容（Markdown）</span>
            <textarea className="note-editor" value={form.body} placeholder={"# 妈妈\n- 生日 6 月 1 日\n- 在老家开花店"}
              onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
        </div>
      )}
    </Sheet>
  );
}

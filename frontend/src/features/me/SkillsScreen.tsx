import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { Skill } from "../../lib/types";
import { IconChevron, IconPlus, IconSearch, IconSpark } from "../../ui/icons";
import { Hint, Page, PageHeader, SearchField, Section, Segmented, Sheet, Skeleton, Toggle, stagger } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";
import Markdown from "../../ui/Markdown";
import { SKILL_SEARCH_FROM, SKILL_STARTERS, filterSkills, fromBuiltin, isOn, skillSummary } from "./skillLibrary";

// 三种出身见 lib/types.ts Skill：内置原样是阅读态（步骤渲染成 Markdown）可“复制一份来改”，自定义版可“恢复默认”，自己写的可删除。
// 每个技能都能停用（行尾开关 / 弹层开关）：留在库里变淡，模型不再看到它。
// 版式（v0.75，与 App 同）：摘要小标签 + 一句说明；≥7 条给搜索；“我的”为空给起步模板；行错峰入场；
// 编辑只有真改了才能存，步骤可“编辑 / 预览”，带着改动关闭先确认。
const PATH = "/api/catalog/skills";
type Draft = Partial<Skill>;
const same = (a: Draft, b: Draft) => (a.name ?? "") === (b.name ?? "") && (a.description ?? "") === (b.description ?? "") && (a.body ?? "") === (b.body ?? "");

export default function SkillsScreen() {
  const skills = useResource<Skill>(PATH);
  const [open, setOpen] = useState<Draft | null>(null);
  const [orig, setOrig] = useState<Draft>({}); // 弹层打开时 / 最近一次服务器返回的内容：用来判断有没有没保存的改动
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<"edit" | "preview">("edit");

  const show = (d: Draft, base: Draft = d) => { setOpen(d); setOrig(base); setPreview("edit"); };
  const dirty = !!open && !open.builtin && !same(open, orig);
  const canSave = dirty && !!open?.name?.trim() && !!open?.description?.trim();

  const close = async () => {
    if (dirty && !(await confirmDialog({ title: "放弃没保存的改动？", text: "刚才改的内容不会保存。", action: "放弃" }))) return;
    setOpen(null);
  };

  const save = async () => {
    if (!open || !canSave) return;
    const body = { name: open.name!.trim(), description: open.description!.trim(), body: open.body ?? "" };
    if (open.id) await http.put(`${PATH}/${open.id}`, body); else await http.post(PATH, body);
    await skills.reload();
    setOpen(null);
  };

  const [busy, setBusy] = useState(false);
  /** customize / reset：服务器返回新条目，列表重拉、弹层换成它。 */
  const act = async (id: string, action: "customize" | "reset") => {
    if (action === "reset" && !(await confirmDialog({ title: `恢复「${open?.name}」的默认做法？`, text: "你的改动会丢掉。", action: "恢复默认" }))) return;
    setBusy(true);
    try {
      const s = await http.post<Skill>(`${PATH}/${id}/${action}`, {});
      await skills.reload();
      show(s);
    } finally { setBusy(false); }
  };

  /** 启用/停用：开关先动（乐观），失败拨回。 */
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const toggle = async (s: Skill, on: boolean) => {
    setPending((p) => ({ ...p, [s.id]: on }));
    try {
      const x = await skills.act(s.id, on ? "enable" : "disable");
      setOpen((o) => (o?.id === s.id ? { ...o, enabled: x.enabled } : o)); // 只换开关，弹层里没保存的输入不动
    } finally {
      setPending(({ [s.id]: _, ...rest }) => rest);
    }
  };
  const onOf = (s: Skill) => pending[s.id] ?? isOn(s);

  const { mine, builtin } = filterSkills(skills.items, query);
  const searching = !!query.trim();
  const readonly = !!open?.builtin;
  const summary = skillSummary(skills.items);
  let n = 0; // 整页错峰序号

  const rows = (items: Skill[]) => (
    <div className="list">
      {items.map((s) => (
        <div key={s.id} className={`row enter ${onOf(s) ? "" : "row-off"}`} style={stagger(++n)}>
          <button className="skill-row" onClick={() => show(s)}>
            <span className="row-icon"><IconSpark /></span>
            <span className="row-body"><span className="row-title">{s.name}</span><span className="row-sub">{s.description}</span></span>
            {s.customized && <span className="chip on">已自定义</span>}
            <span className="row-trail"><IconChevron /></span>
          </button>
          <Toggle on={onOf(s)} label={`启用「${s.name}」`} onChange={(v) => { if (!(s.id in pending)) toggle(s, v); }} />
        </div>
      ))}
    </div>
  );

  return (
    <Page header={<PageHeader title="技能" back action={
      <button className="icon-btn" onClick={() => show({ name: "", description: "", body: "" })} aria-label="新建技能"><IconPlus /></button>} />}>
      <div className="page-intro enter">
        <span key={skills.loading ? "" : summary} className="page-hero-label enter">{skills.loading ? "" : summary}</span>
        <p className="desc">技能是我做某类事的固定方法。我会在合适的时候按它做；停用的留在库里，我看不到。</p>
      </div>
      {skills.loading ? <Skeleton /> : (
        <>
          {skills.items.length >= SKILL_SEARCH_FROM && <SearchField className="skill-search" value={query} onChange={setQuery} placeholder="搜索技能" />}
          {searching && !mine.length && !builtin.length && (
            <Hint icon={<IconSearch size={26} />} title="没有匹配的技能" text="换个词试试，名称、用途和步骤都会搜。"
              action={<button className="btn btn-ghost" onClick={() => setQuery("")}>清除搜索</button>} />
          )}
          {(!searching || mine.length > 0) && (
            <Section title={`我的${mine.length ? ` · ${mine.length}` : ""}`}>
              {mine.length ? rows(mine) : (
                <div className="list starters enter">
                  <div className="row-title">还没有自己写的</div>
                  <p className="row-sub">在这里写，或在聊天里说“把刚才的做法存成技能”。也可以从一个开始改：</p>
                  <div className="starter-list">
                    {SKILL_STARTERS.map((st) => (
                      <button key={st.name} className="btn btn-ghost" onClick={() => show({ ...st }, {})}><IconPlus size={16} />{st.name}</button>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          )}
          {builtin.length > 0 && <Section title={`内置 · ${builtin.length}`}>{rows(builtin)}</Section>}
        </>
      )}
      {open && (
        <Sheet title={readonly ? "内置技能" : open.id ? "编辑技能" : "新建技能"} onClose={close} actions={readonly
          ? <>
            <button className="btn btn-ghost" onClick={() => setOpen(null)}>关闭</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => act(open.id!, "customize")}>复制一份来改</button>
          </>
          : <>
            {open.customized && <button className="btn btn-danger push-left" disabled={busy} onClick={() => act(open.id!, "reset")}>恢复默认</button>}
            {open.id && !fromBuiltin(open) && <button className="btn btn-danger push-left" onClick={async () => { await skills.remove(open.id!); setOpen(null); }}>删除</button>}
            <button className="btn btn-ghost" onClick={close}>取消</button>
            <button className="btn btn-primary" disabled={!canSave} onClick={save}>保存</button>
          </>}>
          {open.id && (
            <div className="skill-toggle">
              <span className="row-sub">{onOf(open as Skill) ? "启用：我会在合适的时候按它做" : "已停用：我看不到它，也不会用它"}</span>
              <Toggle on={onOf(open as Skill)} label={`启用「${open.name}」`} onChange={(v) => { if (!(open.id! in pending)) toggle(open as Skill, v); }} />
            </div>
          )}
          {fromBuiltin(open) && (
            <p key={String(open.customized)} className={`skill-origin${open.customized ? " on" : ""}`}>
              {readonly ? "内置技能随服务器更新，不能直接改。想按自己的习惯来，就复制一份：之后我只按你的版本做。"
                : "这是内置技能的自定义版，我会按你改的做。不满意随时恢复默认。"}
            </p>
          )}
          {readonly ? (
            <div key="read" className="enter">
              <h3 className="skill-name">{open.name}</h3>
              <p className="desc">{open.description}</p>
              <div className="skill-read">{open.body?.trim() ? <Markdown text={open.body} /> : <span className="row-sub">（没有写步骤）</span>}</div>
            </div>
          ) : (
            <div key="form" className="enter">
              <label className="form-field"><span>名称</span>
                <input value={open.name ?? ""} onChange={(e) => setOpen({ ...open, name: e.target.value })} placeholder="写周报" /></label>
              <label className="form-field"><span>什么时候用</span>
                <input value={open.description ?? ""} onChange={(e) => setOpen({ ...open, description: e.target.value })} placeholder="我让你写周报时" /></label>
              <div className="skill-body-head">
                <span>做法（Markdown）</span>
                <Segmented value={preview} onChange={setPreview} label="做法" options={[{ value: "edit", label: "编辑" }, { value: "preview", label: "预览" }]} />
              </div>
              {preview === "preview" ? (
                <div key="p" className="skill-read enter">{open.body?.trim() ? <Markdown text={open.body} /> : <span className="row-sub">还没有写步骤</span>}</div>
              ) : (
                <textarea key="e" className="skill-body-input enter" aria-label="做法" value={open.body ?? ""} onChange={(e) => setOpen({ ...open, body: e.target.value })}
                  placeholder={"1. 先列本周完成的事\n2. 再列下周计划\n3. 语气简洁，不超过 200 字"} />
              )}
            </div>
          )}
        </Sheet>
      )}
    </Page>
  );
}

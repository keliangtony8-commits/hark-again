import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { Skill } from "../../lib/types";
import { IconChevron, IconPlus, IconSpark } from "../../ui/icons";
import { Page, PageHeader, Section, Sheet, Skeleton, Toggle } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

// 三种出身见 lib/types.ts Skill：内置原样只读可“复制一份来改”，自定义版可“恢复默认”，自己写的可删除。
// 每个技能都能停用（行尾开关 / 弹层开关）：留在库里变淡，模型不再看到它。
const PATH = "/api/catalog/skills";
type Draft = Partial<Skill>;
const fromBuiltin = (s: Draft) => !!(s.builtin || s.customized);
const isOn = (s: Draft) => s.enabled !== false;

export default function SkillsScreen() {
  const skills = useResource<Skill>(PATH);
  const [open, setOpen] = useState<Draft | null>(null);

  const save = async () => {
    if (!open?.name?.trim() || !open.description?.trim()) return;
    const body = { name: open.name.trim(), description: open.description.trim(), body: open.body ?? "" };
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
      setOpen(s);
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

  const groups = [
    { title: "我的", items: skills.items.filter((s) => !fromBuiltin(s)) },
    { title: "内置", items: skills.items.filter(fromBuiltin) },
  ];
  const readonly = !!open?.builtin;

  return (
    <Page header={<PageHeader title="技能" back action={
      <button className="icon-btn" onClick={() => setOpen({ name: "", description: "", body: "" })} aria-label="新建技能"><IconPlus /></button>} />}>
      <p className="desc">技能是我做某类事的方法。聊天里说“把这个做法存成技能”，或在这里直接写。</p>
      {skills.loading ? <Skeleton /> : groups.map((g) => (
        <Section key={g.title} title={g.title}>
          <div className="list">
            {g.items.length === 0 ? (
              <div className="row"><div className="row-body"><div className="row-sub">还没有，点右上角 + 新建</div></div></div>
            ) : g.items.map((s) => (
              <div key={s.id} className={`row ${onOf(s) ? "" : "row-off"}`}>
                <button className="skill-row" onClick={() => setOpen(s)}>
                  <span className="row-icon"><IconSpark /></span>
                  <span className="row-body"><span className="row-title">{s.name}</span><span className="row-sub">{s.description}</span></span>
                  {s.customized && <span className="chip on">已自定义</span>}
                  <span className="row-trail"><IconChevron /></span>
                </button>
                <Toggle on={onOf(s)} label={`启用「${s.name}」`} onChange={(v) => { if (!(s.id in pending)) toggle(s, v); }} />
              </div>
            ))}
          </div>
        </Section>
      ))}
      {open && (
        <Sheet title={readonly ? open.name ?? "" : open.id ? "编辑技能" : "新建技能"} onClose={() => setOpen(null)} actions={readonly
          ? <>
            <button className="btn btn-ghost" onClick={() => setOpen(null)}>关闭</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => act(open.id!, "customize")}>复制一份来改</button>
          </>
          : <>
            {open.customized && <button className="btn btn-danger push-left" disabled={busy} onClick={() => act(open.id!, "reset")}>恢复默认</button>}
            {open.id && !fromBuiltin(open) && <button className="btn btn-danger push-left" onClick={async () => { await skills.remove(open.id!); setOpen(null); }}>删除</button>}
            <button className="btn btn-ghost" onClick={() => setOpen(null)}>取消</button>
            <button className="btn btn-primary" disabled={!open.name?.trim() || !open.description?.trim()} onClick={save}>保存</button>
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
            <>
              <p className="desc">{open.description}</p>
              <pre className="skill-body">{open.body}</pre>
            </>
          ) : (
            <>
              <label className="form-field"><span>名称</span>
                <input value={open.name ?? ""} onChange={(e) => setOpen({ ...open, name: e.target.value })} placeholder="写周报" /></label>
              <label className="form-field"><span>什么时候用</span>
                <input value={open.description ?? ""} onChange={(e) => setOpen({ ...open, description: e.target.value })} placeholder="我让你写周报时" /></label>
              <label className="form-field"><span>做法</span>
                <textarea value={open.body ?? ""} onChange={(e) => setOpen({ ...open, body: e.target.value })}
                  placeholder={"1. 先列本周完成的事\n2. 再列下周计划\n3. 语气简洁，不超过 200 字"} /></label>
            </>
          )}
        </Sheet>
      )}
    </Page>
  );
}

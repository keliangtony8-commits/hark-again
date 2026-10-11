import { useState } from "react";
import type { Project } from "../../lib/types";

const EMOJIS = ["📁", "📚", "💼", "✈️", "🏠", "💡", "🧪", "🎯", "💻", "🎓"];
type Values = Pick<Project, "name" | "emoji" | "rules">;

/** 新建和编辑共用一个表单。 */
export default function ProjectForm({ initial, submitLabel, onSubmit, onCancel, onDelete }: {
  initial?: Values; submitLabel: string; onSubmit: (v: Values) => Promise<void>; onCancel: () => void; onDelete?: () => void;
}) {
  const [v, setV] = useState<Values>(initial ?? { name: "", emoji: "📁", rules: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => { setBusy(true); try { await onSubmit(v); } finally { setBusy(false); } };

  return (
    <>
      <div className="form-field"><span>图标</span>
        <div className="emoji-pick">
          {EMOJIS.map((e) => (
            <button key={e} className={v.emoji === e ? "on" : ""} onClick={() => setV({ ...v, emoji: e })}>{e}</button>
          ))}
        </div>
      </div>
      <label className="form-field"><span>名称</span>
        <input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="比如：考研数学" autoFocus /></label>
      <label className="form-field"><span>项目规则</span>
        <textarea value={v.rules} onChange={(e) => setV({ ...v, rules: e.target.value })}
          placeholder={"在这个项目里我应该怎么做？\n比如：回答用中文；每次给出处；代码用 Python。"} />
        <small>每次在项目里对话，这些规则都会自动生效。</small></label>
      <div className="sheet-actions">
        {onDelete && <button className="btn btn-danger push-left" onClick={onDelete}>删除项目</button>}
        <button className="btn btn-ghost" onClick={onCancel}>取消</button>
        <button className="btn btn-primary" disabled={!v.name.trim() || busy} onClick={submit}>{submitLabel}</button>
      </div>
    </>
  );
}

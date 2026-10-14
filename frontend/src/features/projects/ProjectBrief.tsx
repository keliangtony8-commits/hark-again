import { useEffect, useState } from "react";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import { BRIEF_MAX } from "../../lib/projects";
import type { Project } from "../../lib/types";
import { IconDoc, IconEdit } from "../../ui/icons";
import { Hint, Sheet } from "../../ui/kit";
import Markdown from "../../ui/Markdown";
import { confirmDialog } from "../../ui/dialog";

/** 项目档案：项目的长期记忆（目标、决定、文件、固定做法）。助手在对话里用 project_brief 工具自己维护，这里查看和手改。
 *  打开时先拉一次最新的项目（助手可能刚改过）；保存走 PATCH {brief}，服务器盖“谁改的/何时”的戳。与 App ProjectBriefScreen 同结构。 */
export default function ProjectBrief({ project, onSaved, onClose }: { project: Project; onSaved: (p: Project) => void; onClose: () => void }) {
  const [p, setP] = useState(project);
  const [draft, setDraft] = useState<string | null>(null); // null = 查看
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const brief = p.brief ?? "";
  const dirty = draft !== null && draft.trim() !== brief;
  const n = draft?.trim().length ?? 0;

  useEffect(() => { http.get<Project>(`/api/projects/${project.id}`).then((x) => { setP(x); onSaved(x); }).catch(() => {}); }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const discardOk = () => !dirty || confirmDialog({ title: "放弃这次改动？", text: "档案会保持原样。", action: "放弃" });
  const close = async () => { if (await discardOk()) onClose(); };
  const cancel = async () => { if (await discardOk()) setDraft(null); };
  const save = async () => {
    setBusy(true); setError("");
    try {
      const x = await http.patch<Project>(`/api/projects/${p.id}`, { brief: draft });
      setP(x); onSaved(x); setDraft(null);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); } finally { setBusy(false); }
  };

  const stamp = brief && p.brief_updated_at
    ? `${p.brief_by === "assistant" ? "助手更新于" : "你编辑于"} ${formatWhen(p.brief_updated_at)}` : "";

  return (
    <Sheet title="项目档案" onClose={close} actions={draft === null ? (
      <button className="btn btn-primary" onClick={() => setDraft(brief)}><IconEdit />{brief ? "编辑档案" : "自己写"}</button>
    ) : (<>
      <button className="btn btn-ghost" onClick={cancel} disabled={busy}>取消</button>
      <button className="btn btn-primary" onClick={save} disabled={busy || !dirty || n > BRIEF_MAX}>保存</button>
    </>)}>
      {stamp && draft === null && <div className={`brief-stamp${p.brief_by === "assistant" ? " ai" : ""}`}>{stamp}</div>}
      <div className="brief-body" key={draft === null ? "view" : "edit"}>
        {draft !== null ? (
          <label className="form-field">
            <textarea className="brief-editor" value={draft} autoFocus onChange={(e) => setDraft(e.target.value)}
              placeholder={"## 目标\n12 月考研，目标 211 软件工程\n\n## 固定做法\n- 每晚复盘当天错题"} />
            <small className={n > BRIEF_MAX ? "danger" : ""}>Markdown，用小标题分段 · {n} / {BRIEF_MAX}</small>
          </label>
        ) : brief ? (
          <div className="brief-view"><Markdown text={brief} /></div>
        ) : (
          <Hint icon={<IconDoc size={26} />} title="档案还是空的" text="在项目里聊聊你的目标，我会自己建一份；也可以现在先写几句。" />
        )}
      </div>
      {error && <p className="brief-error">{error}</p>}
      <p className="brief-note">这是我在此项目中的长期记忆：目标、已定决策、重要文件与固定流程。我会随工作自动更新，你也可以直接编辑。</p>
    </Sheet>
  );
}

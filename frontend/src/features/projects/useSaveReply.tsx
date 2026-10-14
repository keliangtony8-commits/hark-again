import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import { SAVE_REPLY_LABEL, saveTargets, savedReplyText, type SavedReply } from "../../lib/saveReply";
import type { Project } from "../../lib/types";
import { IconFolder } from "../../ui/icons";
import { Sheet, Skeleton, stagger } from "../../ui/kit";
import { PERSONAL_WORKSPACE, isPersonalWorkspace, workspaceFilesTitle } from "../../lib/workspace";

/** 回复动作菜单里的“存成文件”（v1.15；§I 起从操作条挪进“⋯”菜单；与 App saveReplyToProject 同款）——网页唯一入口。
 *  项目对话 → 一点就存进本项目；主聊天 → 弹层里选“我的文件”或项目（我的文件最前，项目最近活跃在前）。
 *  结果（note）由 MessageView 画在回复下的状态行：“已存进「…」· 文件名”（项目可点去项目页）或一行原因。 */
export function useSaveReply(messageId: string, projectId?: string) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<SavedReply | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);

  const save = async (pid: string) => {
    setPicking(false); setBusy(true); setErr(null);
    try { setDone(await http.post<SavedReply>(`/api/messages/${messageId}/save-to-project`, { project_id: pid })); }
    catch (e) { setDone(null); setErr(e instanceof Error ? e.message : "没存上，稍后再试"); }
    finally { setBusy(false); }
  };

  // 主聊天：一个项目都没有就不用选，直接存进我的文件（和 App 一致）；拿不到项目列表时弹层里照样能选我的文件
  const choose = async () => {
    setBusy(true);
    const n = await http.get<Project[]>("/api/projects").then((p) => p.length, () => -1);
    setBusy(false);
    if (n === 0) save(PERSONAL_WORKSPACE); else setPicking(true);
  };

  const note = done
    ? (isPersonalWorkspace(done.project_id)
      ? <span key={done.path} className="msg-saved fade-in" role="status">{savedReplyText(done.project_name, done.name)}</span>
      : <Link key={done.path} className="msg-saved fade-in" to={`/projects/${done.project_id}`} title="去项目里看看">
          {savedReplyText(done.project_name, done.name)}
        </Link>)
    : err ? <span key={err} className="msg-saved is-err fade-in" role="status">{err}</span> : null;
  return {
    busy, note,
    start: () => { if (!busy) void (projectId ? save(projectId) : choose()); },
    picker: picking ? createPortal(<ProjectPicker onPick={save} onClose={() => setPicking(false)} />, document.body) : null,
  };
}

function ProjectPicker({ onPick, onClose }: { onPick: (pid: string) => void; onClose: () => void }) {
  const [list, setList] = useState<Project[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    http.get<Project[]>("/api/projects").then((p) => setList(saveTargets(p))).catch((e) => setErr(String(e.message ?? e)));
  }, []);
  return (
    <Sheet title="存到哪里" onClose={onClose}>
      <p className="pick-note">存成一份 Markdown，之后的对话都能引用。</p>
      {list === null && !err ? <Skeleton />
        : (
          <div className="list" role="list" aria-label="存到哪里">
            <button className="row enter" style={stagger(0)} onClick={() => onPick(PERSONAL_WORKSPACE)}>
              <span className="row-icon" aria-hidden><IconFolder /></span>
              <span className="row-body"><span className="row-title">{workspaceFilesTitle(PERSONAL_WORKSPACE)}</span><span className="row-sub">主聊天的云端电脑</span></span>
            </button>
            {err && <p className="pick-note is-warn">项目列表没加载出来：{err}</p>}
            {(list ?? []).map((p, i) => {
              const at = p.last_active_at ?? p.updated_at;
              return (
                <button key={p.id} className="row enter" style={stagger(i + 1)} onClick={() => onPick(p.id)}>
                  <span className="row-icon" aria-hidden>{p.emoji}</span>
                  <span className="row-body"><span className="row-title">{p.name}</span></span>
                  {at && <span className="row-hint">{formatWhen(at)}</span>}
                </button>
              );
            })}
          </div>
        )}
    </Sheet>
  );
}

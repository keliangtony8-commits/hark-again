import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import { SAVE_REPLY_LABEL, saveTargets, savedReplyText, type SavedReply } from "../../lib/saveReply";
import type { Project } from "../../lib/types";
import { IconFolder, IconSaveTo } from "../../ui/icons";
import { Hint, Sheet, Skeleton, stagger } from "../../ui/kit";

/** 回复操作条上的“存到项目文件”（v1.15，与 App saveReplyToProject 同款）——网页唯一入口。
 *  项目对话 → 一点就存进本项目；主聊天 → 先在弹层里选项目（最近活跃在前）。
 *  存好 → 键旁边一行“已存进「项目」· 文件名”，点它去项目页；失败 → 同一位置一行原因。 */
export default function SaveReplyButton({ messageId, projectId }: { messageId: string; projectId?: string }) {
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

  return (
    <>
      <button className="icon-btn sm" aria-label={SAVE_REPLY_LABEL} title={SAVE_REPLY_LABEL} disabled={busy}
        onClick={() => (projectId ? save(projectId) : setPicking(true))}><IconSaveTo /></button>
      {done && (
        <Link key={done.path} className="msg-saved fade-in" to={`/projects/${done.project_id}`} title="去项目里看看">
          {savedReplyText(done.project_name, done.name)}
        </Link>
      )}
      {err && <span key={err} className="msg-saved is-err fade-in" role="status">{err}</span>}
      {picking && createPortal(<ProjectPicker onPick={save} onClose={() => setPicking(false)} />, document.body)}
    </>
  );
}

function ProjectPicker({ onPick, onClose }: { onPick: (pid: string) => void; onClose: () => void }) {
  const [list, setList] = useState<Project[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    http.get<Project[]>("/api/projects").then((p) => setList(saveTargets(p))).catch((e) => setErr(String(e.message ?? e)));
  }, []);
  return (
    <Sheet title="存到哪个项目" onClose={onClose}>
      <p className="pick-note">存成一份 Markdown，项目里的对话都能引用。</p>
      {err ? <Hint icon={<IconFolder size={26} />} title="加载失败" text={err} />
        : list === null ? <Skeleton />
        : list.length === 0 ? <Hint icon={<IconFolder size={26} />} title="还没有项目" text="先在“项目”里建一个，再回来存。" />
        : (
          <div className="list" role="list" aria-label="项目">
            {list.map((p, i) => {
              const at = p.last_active_at ?? p.updated_at;
              return (
                <button key={p.id} className="row enter" style={stagger(i)} onClick={() => onPick(p.id)}>
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

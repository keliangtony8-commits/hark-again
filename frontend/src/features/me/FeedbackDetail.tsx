import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import type { FeedbackItem } from "../../lib/feedback";
import { copyLink } from "../../lib/pages";
import { confirmDialog } from "../../ui/dialog";
import { IconChat, IconCheck, IconCloudOff, IconCopy, IconRefresh, IconTrash } from "../../ui/icons";
import { Hint, Page, PageHeader, PageIntro, Skeleton, stagger } from "../../ui/kit";
import Markdown from "../../ui/Markdown";
import { FEEDBACK_PATH } from "./FeedbackScreen";

/** 反馈详情（v2.64，= App FeedbackDetailScreen）：整份报告就是“复制报告”出去的那段 Markdown，所见即所贴；
 *  一排：复制报告 · 打开对话 · 标为已解决 / 重新打开；页头删除。 */
export default function FeedbackDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [f, setF] = useState<FeedbackItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => http.get<FeedbackItem>(`${FEEDBACK_PATH}/${id}`).then(setF).catch((e) => setError(e instanceof Error ? e.message : "读不到")), [id]);
  useEffect(() => { void load(); }, [load]);

  const resolved = f?.status === "resolved";
  const toggle = async () => {
    if (!f) return;
    setBusy(true);
    try { setF(await http.patch<FeedbackItem>(`${FEEDBACK_PATH}/${f.id}`, { status: resolved ? "open" : "resolved" })); }
    catch (e) { setError(e instanceof Error ? e.message : "没改成"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!f || !(await confirmDialog({ title: "删除这份反馈？", text: f.message_id ? "那条回复上的评价也会一起取消。" : undefined }))) return;
    await http.del(`${FEEDBACK_PATH}/${f.id}`).catch(() => {});
    nav("/me/feedback", { replace: true });
  };
  const open = () => f?.conversation_id && nav(f.project_id ? `/projects/${f.project_id}` : "/chat", { state: { open: f.conversation_id } });

  return (
    <Page header={<PageHeader title="反馈详情" back action={f && <button className="icon-btn" aria-label="删除" title="删除" onClick={() => void remove()}><IconTrash /></button>} />}>
      {error && !f ? <Hint icon={<IconCloudOff />} title="读不到这份反馈" text="可能已经删了，或者网络断了" action={<button className="btn btn-ghost" onClick={() => { setError(null); void load(); }}>重试</button>} />
        : !f ? <Skeleton /> : (<>
          <PageIntro summary={[f.kind_label, formatWhen(f.created_at)].filter(Boolean).join(" · ")} line={resolved ? "已解决" : "还没解决"} />
          {error && <p className="desc" role="alert">{error}</p>}
          <div className="pills enter" style={stagger(1)}>
            <button className="btn btn-primary btn-sm" onClick={async () => setCopied(await copyLink(f.markdown ?? ""))}>
              <span key={copied ? "ok" : "copy"} className="icon-pop">{copied ? <IconCheck size={16} /> : <IconCopy />}</span>{copied ? "已复制" : "复制报告"}</button>
            {f.conversation_id && <button className="btn btn-ghost btn-sm" onClick={open}><IconChat size={16} />打开对话</button>}
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void toggle()}>
              {resolved ? <><IconRefresh />重新打开</> : <><IconCheck size={16} />标为已解决</>}</button>
          </div>
          <div className="glass-card feedback-report enter" style={stagger(2)}><Markdown text={f.markdown ?? ""} /></div>
        </>)}
    </Page>
  );
}

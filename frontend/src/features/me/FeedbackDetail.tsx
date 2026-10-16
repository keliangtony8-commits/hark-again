import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSwr } from "../../hooks/useSwr";
import { http } from "../../lib/api";
import { swrPatch, swrRemove } from "../../lib/swr";
import { formatWhen } from "../../lib/format";
import type { FeedbackItem, FeedbackList } from "../../lib/feedback";
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
  const path = `${FEEDBACK_PATH}/${id}`;
  const { data: f, error: loadError, reload, mutate } = useSwr<FeedbackItem>(path);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  // 改了 / 删了一条：列表的缓存跟着改（回列表时不闪回旧状态），没缓存就不管
  const patchList = (fn: (items: FeedbackItem[]) => FeedbackItem[]) => swrPatch<FeedbackList>(FEEDBACK_PATH, (l) => ({ ...l, items: fn(l.items) }));

  const resolved = f?.status === "resolved";
  const toggle = async () => {
    if (!f) return;
    setBusy(true);
    try {
      const x = await http.patch<FeedbackItem>(`${FEEDBACK_PATH}/${f.id}`, { status: resolved ? "open" : "resolved" });
      mutate(x);
      patchList((items) => items.map((i) => (i.id === x.id ? { ...i, status: x.status } : i)));
    }
    catch (e) { setError(e instanceof Error ? e.message : "没改成"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!f || !(await confirmDialog({ title: "删除这份反馈？", text: f.message_id ? "那条回复上的评价也会一起取消。" : undefined }))) return;
    await http.del(`${FEEDBACK_PATH}/${f.id}`).catch(() => {});
    patchList((items) => items.filter((i) => i.id !== f.id));
    swrRemove(path);
    nav("/me/feedback", { replace: true });
  };
  const open = () => f?.conversation_id && nav(f.project_id ? `/projects/${f.project_id}` : "/chat", { state: { open: f.conversation_id } });

  return (
    <Page header={<PageHeader title="反馈详情" back action={f && <button className="icon-btn" aria-label="删除" title="删除" onClick={() => void remove()}><IconTrash /></button>} />}>
      {loadError ? <Hint icon={<IconCloudOff />} title="读不到这份反馈" text="可能已经删了，或者网络断了" action={<button className="btn btn-ghost" onClick={() => void reload()}>重试</button>} />
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

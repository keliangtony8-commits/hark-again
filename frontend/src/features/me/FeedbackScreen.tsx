import { useState } from "react";
import { useSwr } from "../../hooks/useSwr";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import { FEEDBACK_GOOD, groupFeedback, type FeedbackItem, type FeedbackList } from "../../lib/feedback";
import { IconFeedback, IconThumbDown, IconThumbUp } from "../../ui/icons";
import { ListGroup, ListRow, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard } from "../../ui/kit";

export const FEEDBACK_PATH = "/api/feedback";

export const feedbackIcon = (f: FeedbackItem) =>
  f.kind === FEEDBACK_GOOD ? <IconThumbUp size={20} /> : f.kind === "problem" ? <IconFeedback /> : <IconThumbDown size={20} />;

/** 反馈（v2.64，= App features/me/feedback_screen.dart；对标 Hark 设置 → Feedback）：
 *  “报告问题” + 回看在回复下点过 👍 / 👎 的报告。版式同 Pages：页头摘要 → 空时起步卡 → 待处理 / 有用的回复 / 已解决（带数量）。
 *  点一行进详情（FeedbackDetail，删除在那里）。报告里存什么只在后端 app/feedback.py。 */
export default function FeedbackScreen() {
  const { data: list, error: loadError, reload } = useSwr<FeedbackList>(FEEDBACK_PATH);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [writing, setWriting] = useState<string | null>(null);
  const error = submitError ?? loadError?.message ?? null;

  const submit = async () => {
    const note = writing?.trim();
    if (!note) return;
    try { await http.post(FEEDBACK_PATH, { note }); setWriting(null); setSubmitError(null); await reload(); }
    catch (e) { setSubmitError(e instanceof Error ? e.message : "提交失败"); }
  };
  const items = list?.items ?? [];
  const g = groupFeedback(items);
  let n = 0;
  const rows = (fs: FeedbackItem[]) => (
    <ListGroup>
      {fs.map((f) => (
        <ListRow key={f.id} to={`/me/feedback/${f.id}`} off={f.status === "resolved"} enter={++n} icon={feedbackIcon(f)} title={f.excerpt || f.kind_label}
          sub={[f.kind_label, formatWhen(f.created_at), f.status === "resolved" ? "已解决" : ""].filter(Boolean).join(" · ")} />
      ))}
    </ListGroup>
  );

  return (
    <Page header={<PageHeader title="反馈" back action={<button className="btn btn-ghost btn-sm" onClick={() => setWriting("")}><IconFeedback size={16} />报告问题</button>} />}>
      <PageIntro loading={!list && !error} summary={g.todo.length ? `${g.todo.length} 条待处理` : "没有待处理的"}
        line="回复下点 👎 会连同提问、回复和每一步记录存一份报告；在这里回看、复制给要修它的人，修好了标成已解决。" />
      {error && <p className="desc" role="alert">{error}</p>}
      {!list && !error ? <Skeleton /> : (<>
        {items.length === 0 && (
          <StarterCard title="还没有反馈" text="哪里用着不顺，直接告诉我；对某条回复不满意，就在它下面点 👎。">
            <button className="btn btn-primary" onClick={() => setWriting("")}><IconFeedback size={16} />报告问题</button>
          </StarterCard>
        )}
        {g.todo.length > 0 && <Section title={`待处理 · ${g.todo.length}`}>{rows(g.todo)}</Section>}
        {g.good.length > 0 && <Section title={`有用的回复 · ${g.good.length}`}>{rows(g.good)}</Section>}
        {g.done.length > 0 && <Section title={`已解决 · ${g.done.length}`}>{rows(g.done)}</Section>}
      </>)}
      {writing !== null && (
        <Sheet title="报告问题" onClose={() => setWriting(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setWriting(null)}>取消</button>
          <button className="btn btn-primary" disabled={!writing.trim()} onClick={() => void submit()}>提交</button>
        </>}>
          <p className="desc">请描述问题及出现步骤，便于排查。</p>
          <label className="form-field"><span>遇到了什么问题</span>
            <textarea rows={4} autoFocus value={writing} placeholder="比如：首页卡片一直不刷新" onChange={(e) => setWriting(e.target.value)} /></label>
        </Sheet>
      )}
    </Page>
  );
}

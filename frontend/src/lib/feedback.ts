// 反馈（v2.64，= App models/feedback.dart）：/api/feedback 的数据和文字规则。
// 报告里存什么、一条回复几份评价只在后端 app/feedback.py。

export const FEEDBACK_GOOD = "good";
/** 👎 的原因（顺序 = 原因单里的顺序，和 App feedbackReasons 一致）。 */
export const FEEDBACK_REASONS: { kind: string; label: string }[] = [
  { kind: "wrong", label: "答错了" },
  { kind: "incomplete", label: "没做完" },
  { kind: "stuck", label: "响应缓慢或无响应" },
  { kind: "other", label: "别的问题" },
];

export interface FeedbackItem {
  id: string; kind: string; kind_label: string; excerpt: string; status: "open" | "resolved" | string;
  message_id: string | null; conversation_id: string | null; project_id?: string | null;
  created_at: string | null; resolved_at?: string | null;
  note?: string; markdown?: string; snapshot?: Record<string, unknown>;
}
export interface FeedbackList { items: FeedbackItem[]; open: number }

export const isBadFeedback = (kind?: string | null) => !!kind && kind !== FEEDBACK_GOOD;
export const feedbackPath = (messageId: string) => `/api/messages/${messageId}/feedback`;

/** 打完评价的一句：👍 谢谢；👎 告诉他报告存在哪。 */
export function feedbackToast(kind: string | null): string {
  if (kind === null) return "已取消评价";
  return kind === FEEDBACK_GOOD ? "谢谢，记下了" : "已记下，可在“我的 → 反馈”里查看";
}

/** “我的”入口副标题。 */
export const feedbackRowSubtitle = (l: FeedbackList | null) =>
  !l || l.open === 0 ? "报告问题，回看评价过的回复" : `${l.open} 条没解决`;

/** 分组：待处理（👎 + 问题报告）/ 有用的回复 / 已解决。 */
export function groupFeedback(items: FeedbackItem[]) {
  const open = items.filter((f) => f.status !== "resolved");
  return {
    todo: open.filter((f) => f.kind !== FEEDBACK_GOOD),
    good: open.filter((f) => f.kind === FEEDBACK_GOOD),
    done: items.filter((f) => f.status === "resolved"),
  };
}

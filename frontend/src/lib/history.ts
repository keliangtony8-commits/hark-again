// 历史对话分组（纯函数）：置顶 / 今天 / 昨天 / 7 天内 / 更早。与 App 的 features/chat/history.dart 保持同一规则。
import type { ConversationSummary } from "./types";

/** 搜索框防抖，与 App 的 Timing.searchDebounce 一致。 */
export const SEARCH_DEBOUNCE_MS = 300;

export type HistoryGroup = { label: string; items: ConversationSummary[] };

const LABELS = ["置顶", "今天", "昨天", "7 天内", "更早"] as const;
const day = (t: Date) => new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();

export function groupConversations(list: ConversationSummary[], now = new Date()): HistoryGroup[] {
  const today = day(now);
  const buckets = new Map<string, ConversationSummary[]>(LABELS.map((l) => [l, []]));
  for (const c of list) {
    const t = new Date(c.updated_at);
    const days = isNaN(t.getTime()) ? 999 : Math.round((today - day(t)) / 86_400_000);
    const label = c.pinned ? "置顶" : days <= 0 ? "今天" : days === 1 ? "昨天" : days < 7 ? "7 天内" : "更早";
    buckets.get(label)!.push(c);
  }
  return [...buckets].filter(([, items]) => items.length).map(([label, items]) => ({ label, items }));
}

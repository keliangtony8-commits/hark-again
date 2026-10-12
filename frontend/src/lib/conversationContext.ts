// 对话记忆（GET /api/conversations/{id}/context、POST …/compact，后端 agent/context.py 是唯一规则）。
// 与 App 的 models/conversation_context.dart + features/chat/conversation_memory.dart 措辞一致。

export interface ConversationContext {
  messages: number;
  summarized: number;
  raw: number;
  raw_chars: number;
  budget: number;
  summary: string;
  compactable: number;
}

export interface CompactResult extends ConversationContext {
  status: "compressed" | "noop" | "inflated";
  before: number;
  after: number;
}

/** 字数：一万以下原样，以上 “1.2 万字”。 */
export function formatChars(n: number): string {
  return n < 10000 ? `${n} 字` : `${(n / 10000).toFixed(1)} 万字`;
}

export const contextFill = (c: ConversationContext) => (c.budget > 0 ? c.raw_chars / c.budget : 0);
export const contextTight = (c: ConversationContext) => contextFill(c) >= 0.8;

export const contextLine = (c: ConversationContext) =>
  `最近 ${c.raw} 条原文 · 约 ${formatChars(c.raw_chars)}，上限 ${formatChars(c.budget)}`;

export const summaryLine = (c: ConversationContext) => (c.summarized > 0 ? `更早的 ${c.summarized} 条已压成摘要` : null);

export function compactToast(before: ConversationContext, r: CompactResult): string {
  if (r.status === "compressed") {
    return `已把 ${r.summarized - before.summarized} 条较早消息压成摘要（约 ${formatChars(r.before)} → ${formatChars(r.after)}）`;
  }
  return r.status === "inflated" ? "摘要反而比原文长，保持原样" : "已经很精简，没有可整理的";
}

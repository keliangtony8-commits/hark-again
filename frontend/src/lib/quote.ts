// 引用回复（§J / §C，= App models/message.dart MessageQuote）：从一条消息取引用、引用条上显示的那行字。规则在后端 app/reply_quote.py。
import type { Message, MessageQuote } from "./types";
import { copyText } from "./copy";

export const QUOTE_SNIPPET = 120; // = 后端 reply_quote.SNIPPET
export const QUOTE_MISSING = "原消息已删除";

/** 点“回复”时：纯文字（没有就用附件名），压成一行、截断。 */
export function quoteOf(m: Message): MessageQuote {
  const names = m.blocks.flatMap((b) => (b.type === "file" && b.name ? [b.name] : [])).join("、");
  let t = m.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim() || (names ? `[附件] ${names}` : "") || copyText(m.blocks);
  t = t.split(/\s+/).filter(Boolean).join(" ");
  return { id: m.id, role: m.role, text: t.length > QUOTE_SNIPPET ? `${t.slice(0, QUOTE_SNIPPET - 1)}…` : t };
}

export const quoteLine = (q: MessageQuote) => (q.missing ? QUOTE_MISSING : q.text ?? "");

/** 已落库（有服务器 id）、生成完的消息才能被引用：本机 id 服务器不认。 */
export const quotable = (m: Message) => !m.pending && !m.outbox && !m.id.startsWith("local-") && m.id !== "pending";

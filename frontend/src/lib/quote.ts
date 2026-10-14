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

/** 这条是不是 id：本地 id 或认领后的服务器 id。 */
export const isId = (m: Message, id?: string | null) => !!id && (m.id === id || m.serverId === id);

/** 第 i 条顶上画不画引用行（§C，= App showsQuote）：用户自己引用的一定画；助手回复只在原话不“紧挨着”时画——
 *  往上一串连续用户消息（一口气发的、途中发的）里有原话 = 紧挨着，不画；中间隔了别的回复（问进度、并行回答）才画。 */
export function showsQuote(ms: Message[], i: number): boolean {
  const q = ms[i].quote;
  if (!q) return false;
  if (ms[i].role === "user") return true;
  for (let j = i - 1; j >= 0 && ms[j].role === "user"; j--) if (isId(ms[j], q.id)) return false;
  return true;
}

/** 已落库（有服务器 id）、生成完的消息才能被引用：本机 id 服务器不认。 */
export const quotable = (m: Message) => !m.pending && !m.outbox && !m.id.startsWith("local-") && m.id !== "pending";

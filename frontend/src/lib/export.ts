import { endLabel } from "./messageStatus";
import { copyText } from "./copy";
import type { Message } from "./types";

/**
 * 整个对话导出成 Markdown（和 App 的 models/export.dart 同一套规则）。
 * 每条消息正文复用 copyText，所以“复制一条”和“导出整段”写法一致；只导出已进服务器的消息。
 */
export function conversationMarkdown(title: string, messages: Message[], at = new Date()): string {
  const kept = messages
    .filter((m) => !m.pending && !m.outbox)
    .map((m) => [m, copyText(m.blocks)] as const)
    .filter(([, body]) => body);
  const parts = [
    `# ${title.trim() || "新对话"}`,
    `> 导出于 ${stamp(at)} · ${kept.length} 条消息`,
    ...kept.flatMap(([m, body]) => [m.role === "user" ? "## 我" : "## 助手", endLabel(m) ? `${body}\n\n*（${endLabel(m)}）*` : body]),
  ];
  return parts.join("\n\n") + "\n";
}

/** 导出文件名：文件系统不认的字符换成下划线，太长截断。 */
export function exportFileName(title: string): string {
  // eslint-disable-next-line no-control-regex
  let name = title.trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").replace(/\s+/g, " ");
  if (!name) name = "对话";
  const chars = [...name];
  if (chars.length > 60) name = chars.slice(0, 60).join("");
  return `${name}.md`;
}

/** 让浏览器把一段文本存成文件。 */
export function downloadText(fileName: string, text: string, mime = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = Object.assign(document.createElement("a"), { href: url, download: fileName });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function stamp(t: Date): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${two(t.getMonth() + 1)}-${two(t.getDate())} ${two(t.getHours())}:${two(t.getMinutes())}`;
}

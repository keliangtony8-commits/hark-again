import type { Block } from "./types";

/**
 * “复制”一条回复得到的 Markdown（和 App 的 copyText、后端 blocks_to_text 同一套规则，表格转成 Markdown 表）。
 * 只复制内容：审批卡、订单卡、浏览器画面这类过程卡片不进剪贴板。
 */
export function copyText(blocks: Block[]): string {
  return blocks.map((b): string => {
    switch (b.type) {
      case "text": return b.text.trim();
      case "code": return "```" + (b.language ?? "") + "\n" + b.source + "\n```";
      case "table": return [
        ...(b.title ? [`**${b.title}**`] : []),
        `| ${b.columns.join(" | ")} |`,
        `|${b.columns.map(() => " --- ").join("|")}|`,
        ...b.rows.map((r) => `| ${r.join(" | ")} |`),
        ...(b.note ? [b.note] : []),
      ].join("\n");
      case "links": return b.items.map((i) => `- ${i.title ?? i.label ?? i.url} ${i.url}`).join("\n");
      case "page": return `${b.title} ${b.url}`;
      case "preview": return `${b.title || `端口 ${b.port}`} ${b.url}`;
      case "stats": return b.items.map((i) => `${i.label}：${i.value}${i.note ? `（${i.note}）` : ""}`).join("\n");
      case "file": return `[文件：${b.name}]`;
      case "draft": return b.body.trim();
      case "summary": return [`**${b.title}**`, ...(b.subtitle ? [b.subtitle] : []), b.markdown.trim()].join("\n\n");
      case "images": return b.items.map((i) => `- ${i.caption ?? "图片"} ${i.url}`).join("\n");
      case "products": return [
        ...(b.title ? [`**${b.title}**`] : []),
        ...b.items.map((i) => "- " + [i.name, i.price, i.meta, i.url].filter(Boolean).join(" ")),
        ...(b.pick ? [b.pick] : []),
      ].join("\n");
      default: return "";
    }
  }).filter(Boolean).join("\n\n");
}

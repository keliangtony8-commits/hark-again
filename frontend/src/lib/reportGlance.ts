import type { HomeCard, InboxItem } from "./types";

/** 报告卡的“一眼”（v1.07，= App HomeCard.glance / InboxItem.glance）：服务端投递时取出 headline（摘要卡标题）
 *  + gist（一句话，backend app/report_gist.py），客户端只拼 `headline · gist`。 */
const join = (x: { headline?: string | null; gist?: string | null }) =>
  [x.headline, x.gist].map((s) => (s ?? "").trim()).filter(Boolean).join(" · ");

/** 收件箱行副标题：没有 headline/gist（老服务器 / 老卡）就退回第一段正文，去掉 Markdown 记号，截 80 字。 */
export function cardGlance(c: HomeCard): string {
  const g = join(c);
  if (g) return g;
  const t = c.blocks.filter((b) => b.type === "text").map((b) => (b.type === "text" ? b.text : "")).join("\n")
    .replace(/[#*_`>|-]/g, "").replace(/\s+/g, " ").trim();
  return !t ? "点开查看结果" : t.length > 80 ? `${t.slice(0, 80)}…` : t;
}

/** 横幅第二行；都没有为 null（只显示标题）。 */
export const itemGlance = (i: InboxItem): string | null => join(i) || null;

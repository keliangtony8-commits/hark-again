// 项目首屏的纯规则（v1.10，App features/projects/project_home.dart 同规则）。
import type { ConversationSummary, Project } from "../../lib/types";

/** 首屏最多列几条最近对话。 */
export const PROJECT_RECENT_MAX = 3;

/** 置顶优先，其余按更新时间新→旧（没有时间的排后，顺序稳定），取前 max 条。 */
export function projectRecent(list: ConversationSummary[], max = PROJECT_RECENT_MAX): ConversationSummary[] {
  const t = (c: ConversationSummary) => (c.updated_at ? new Date(c.updated_at).getTime() : 0) || 0;
  return list.map((c, i) => ({ c, i }))
    .sort((a, b) => (a.c.pinned === b.c.pinned ? 0 : a.c.pinned ? -1 : 1) || t(b.c) - t(a.c) || a.i - b.i)
    .slice(0, max).map((x) => x.c);
}

/** 档案第一行正文（跳过标题、去掉列表符号）。 */
function briefLine(brief = ""): string {
  for (const l of brief.split("\n")) {
    const s = l.trim().replace(/^([-*+]|\d+\.)\s+/, "");
    if (s && !s.startsWith("#")) return s;
  }
  return "";
}

/** 名字下面那一行：规则第一行 > 档案第一行 > 引导语。 */
export function projectLine(p: Project): string {
  const rules = p.rules.trim().split("\n")[0].trim();
  return rules || briefLine(p.brief) || "还没有规则和档案，写下来助手每次都会照着做";
}

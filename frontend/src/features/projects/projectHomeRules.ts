// 项目页的纯规则（App features/projects/project_home.dart / projects_screen.dart 同规则）。
// 名字不能改回 projectHome.ts：它和同目录组件 ProjectHome.tsx 只差大小写，
// Windows / macOS 上 tsc 会当成同一个文件（TS1149），v2.90.2 前一直在报这个错。
import { formatSize } from "../../lib/files";
import type { ConversationSummary, Project, ProjectFile } from "../../lib/types";

/** 项目首屏的对话顺序（v2.93 §Q 列全部）：置顶优先，其余按更新时间新→旧（没有时间的排后，顺序稳定）。 */
export function projectConversations(list: ConversationSummary[]): ConversationSummary[] {
  const t = (c: ConversationSummary) => (c.updated_at ? new Date(c.updated_at).getTime() : 0) || 0;
  return list.map((c, i) => ({ c, i }))
    .sort((a, b) => (a.c.pinned === b.c.pinned ? 0 : a.c.pinned ? -1 : 1) || t(b.c) - t(a.c) || a.i - b.i)
    .map((x) => x.c);
}

/** v2.93 §Q 列表里哪些项目用正文色（其余变灰）：按最近活动排第一的那个，以及进行中 / 等你回复的（= App projectIsCurrent）。
 *  “已完成”和很久没动的退到背景；只看第一个会把另一个正在跑的项目也压灰。 */
export const projectIsCurrent = (index: number, p: Project) => index === 0 || p.status === "running" || p.status === "waiting";

/** 文件行副标题：在子文件夹里就带上文件夹，再接大小（文件面板、引用文件选择器、输入框 @ 提及共用）。 */
export function projectFileLine(f: ProjectFile): string {
  const slash = f.path.lastIndexOf("/");
  return [slash > 0 ? f.path.slice(0, slash) : "", formatSize(f.size)].filter(Boolean).join(" · ");
}

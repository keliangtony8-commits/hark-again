// 项目页的纯规则（App features/projects/projects_screen.dart 同规则）。
// 文件名沿用 v2.90.2 起的 projectHomeRules.ts（v2.95 项目首屏 ProjectHome 已删，不再有大小写撞名问题，只是不改名省得动引用）。
import { formatSize } from "../../lib/files";
import type { Project, ProjectFile } from "../../lib/types";

export const activeAt = (p: Project) => p.last_active_at ?? p.updated_at;

/** 最近有动静的排前面（= App byActivity；项目列表和项目切换栏共用）。 */
export const byActivity = (list: Project[]) => [...list].sort((a, b) => (Date.parse(activeAt(b) ?? "") || 0) - (Date.parse(activeAt(a) ?? "") || 0));

/** v2.93 §Q 列表里哪些项目用正文色（其余变灰）：按最近活动排第一的那个，以及进行中 / 等你回复的（= App projectIsCurrent）。
 *  “已完成”和很久没动的退到背景；只看第一个会把另一个正在跑的项目也压灰。 */
export const projectIsCurrent = (index: number, p: Project) => index === 0 || p.status === "running" || p.status === "waiting";

/** 文件行副标题：在子文件夹里就带上文件夹，再接大小（文件面板、引用文件选择器、输入框 @ 提及共用）。 */
export function projectFileLine(f: ProjectFile): string {
  const slash = f.path.lastIndexOf("/");
  return [slash > 0 ? f.path.slice(0, slash) : "", formatSize(f.size)].filter(Boolean).join(" · ");
}

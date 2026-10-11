// 项目首屏的纯规则（v1.10，App features/projects/project_home.dart 同规则）。
import { formatSize } from "../../lib/files";
import type { ConversationSummary, Project, ProjectFile } from "../../lib/types";

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

/** 首屏最多列几个文件（v1.11）。 */
export const PROJECT_FILES_MAX = 3;

/** 最近的文件：按修改时间新→旧（没有时间的排后，顺序稳定），取前 max 个。 */
export function projectRecentFiles(list: ProjectFile[], max = PROJECT_FILES_MAX): ProjectFile[] {
  return list.map((f, i) => ({ f, i }))
    .sort((a, b) => (b.f.modified ?? 0) - (a.f.modified ?? 0) || a.i - b.i)
    .slice(0, max).map((x) => x.f);
}

/** 文件行副标题：在子文件夹里就带上文件夹，再接大小。 */
export function projectFileLine(f: ProjectFile): string {
  const slash = f.path.lastIndexOf("/");
  return [slash > 0 ? f.path.slice(0, slash) : "", formatSize(f.size)].filter(Boolean).join(" · ");
}

/** 项目文件下载地址的路径部分（每段编码）。 */
export const projectFilePath = (pid: string, f: ProjectFile) => `/api/projects/${pid}/files/${f.path.split("/").map(encodeURIComponent).join("/")}`;

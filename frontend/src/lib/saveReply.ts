// 把回复存成项目文件（v1.15）：规则与 App features/projects/save_reply.dart 一致。服务器 reply_files.py 决定文件名和内容。
import type { Project } from "./types";

export const SAVE_REPLY_LABEL = "存到项目文件";

/** POST /api/messages/{id}/save-to-project 的回执。 */
export type SavedReply = { project_id: string; project_name: string; path: string; name: string; size: number; mime: string };

const activeAt = (p: Project) => p.last_active_at ?? p.updated_at ?? null;

/** 选项目时的顺序：最近活跃在前，没有时间的排后，其余保持原顺序。 */
export function saveTargets(projects: Project[]): Project[] {
  return projects.map((p, i) => ({ p, i })).sort((a, b) => {
    const x = activeAt(a.p), y = activeAt(b.p);
    if (!x || !y) return x === y ? a.i - b.i : x ? -1 : 1;
    return (Date.parse(y) - Date.parse(x)) || a.i - b.i;
  }).map(({ p }) => p);
}

/** 存好后那一行字。 */
export const savedReplyText = (projectName: string, fileName: string) => `已存进「${projectName}」· ${fileName}`;

// 本对话全部文件（v1.33）：服务器 app/conversation_files.py 收拢一段对话里出现过的所有文件，这里只有展示规则。
// App models/conversation_files.dart 同义。
import { fileKind, formatSize } from "./files";
import { PERSONAL_WORKSPACE, workspaceFilePath } from "./workspace";

/** 来源 → 叫法；顺序 = 筛选条顺序。 */
export const FILE_ORIGINS: Record<string, string> = {
  delivered: "交给你的",
  sent: "你发的",
  downloaded: "网页下载",
  to_web: "传到网页",
  written: "助手写的",
};

export const fileOriginLabel = (o: string) => FILE_ORIGINS[o] ?? "文件";

export type ConversationFile = {
  key: string; name: string; mime: string; size: number; source: "upload" | "project"; id: string;
  project_id?: string | null; origin: string; message_id?: string; at?: string | null; gone?: boolean;
};
export type ConversationFiles = { count: number; available: number; size: number; zip_max?: number; files: ConversationFile[] };

export const conversationFilesPath = (cid: string) => `/api/conversations/${cid}/files`;
export const conversationZipPath = (cid: string) => `/api/conversations/${cid}/files.zip`;

/** 列表里出现过的来源及数量；只有一种时不显示筛选条。 */
export const fileOriginCounts = (d: ConversationFiles): [string, number][] =>
  Object.keys(FILE_ORIGINS).map((o) => [o, d.files.filter((f) => f.origin === o).length] as [string, number]).filter(([, n]) => n > 0);

export const canZip = (d: ConversationFiles) => d.available > 0 && (!d.zip_max || d.size <= d.zip_max);

export const zipNote = (d: ConversationFiles) => {
  if (d.available === 0) return "文件均已删除，无法打包";
  if (!canZip(d)) return `一共 ${formatSize(d.size)}，超过打包上限 ${formatSize(d.zip_max ?? 0)}，请逐个下载`;
  return `${d.available} 个文件 · ${formatSize(d.size)}`;
};

export const conversationFileLine = (f: ConversationFile) => f.gone
  ? `${fileOriginLabel(f.origin)} · ${f.source === "project" ? "已从工作区删除或挪走" : "存储里已清掉"}`
  : [fileOriginLabel(f.origin), fileKind(f.name, f.mime), formatSize(f.size)].filter(Boolean).join(" · ");

/** 下载路径（未带 token，由 fileUrl 补上）：上传快照 / 工作区文件，和文件卡同一套接口。 */
export const conversationFilePath = (f: ConversationFile) => f.source === "project"
  ? workspaceFilePath(f.project_id || PERSONAL_WORKSPACE, f.id)
  : `/api/uploads/${encodeURIComponent(f.id)}`;

import { workspaceFilesTitle } from "./workspace";
import { fileUrl } from "./api";
import type { FileBlock, OutgoingFile, ProjectFile } from "./types";

export const formatSize = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : n < 1024 ** 3 ? `${(n / 1024 ** 2).toFixed(1)} MB`
    : `${(n / 1024 ** 3).toFixed(1).replace(/\.0$/, "")} GB`;

export const isImage = (mime: string) => mime.startsWith("image/");

/** 文件块 → 下载地址。上传和项目文件走不同接口，统一在这里换算。 */
export const blockUrl = (b: FileBlock) =>
  b.source === "upload"
    ? fileUrl(`/api/uploads/${b.id}`)
    : fileUrl(`/api/projects/${b.project_id}/files/${b.id.split("/").map(encodeURIComponent).join("/")}`);

/** 要发出的文件统一成文件块（上传 → source=upload）。 */
export const asFileBlock = (f: OutgoingFile): FileBlock => ("type" in f ? f : { type: "file", source: "upload", ...f });

/** 项目文件在消息里的样子：source=project，id = 相对路径（与 App projectFileBlock 一致）。 */
export const projectFileBlock = (pid: string, f: ProjectFile): FileBlock =>
  ({ type: "file", source: "project", id: f.path, name: f.name, mime: f.mime, size: f.size, project_id: pid });

/** 输入框附件名片第二行——唯一规则（App Attachment.sub 同义）：上传中 / 失败原因 / [项目文件 / 我的文件 · ]大小。 */
export const attachSub = (f: { upload?: { size: number }; ref?: FileBlock; error?: string }) =>
  f.error ? "上传失败" : f.ref ? `${workspaceFilesTitle(f.ref.project_id)} · ${formatSize(f.ref.size)}` : f.upload ? formatSize(f.upload.size) : "上传中…";

/** 一条消息最多带几个文件（上传 + 引用合计，和服务器 ws.MAX_FILES 一致）。 */
export const MAX_MESSAGE_FILES = 10;

export const extOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE");

const KIND_BY_EXT: Record<string, string> = {
  pdf: "PDF 文档", doc: "Word 文档", docx: "Word 文档", md: "文档", txt: "文本",
  xls: "表格", xlsx: "表格", csv: "表格", ppt: "演示文稿", pptx: "演示文稿", key: "演示文稿",
  zip: "压缩包", gz: "压缩包", tgz: "压缩包", tar: "压缩包", "7z": "压缩包", rar: "压缩包",
  html: "网页", json: "数据", svg: "矢量图",
};

/** 文件卡第二行的“是什么”——唯一规则（App ui/format.dart fileKind 同义）：先看扩展名，再看 mime 大类，都不认识 = 空。 */
export const fileKind = (name: string, mime: string) => {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  if (KIND_BY_EXT[ext]) return KIND_BY_EXT[ext];
  for (const [p, k] of [["image/", "图片"], ["audio/", "音频"], ["video/", "视频"], ["text/", "文本"]] as const)
    if (mime.startsWith(p)) return k;
  return "";
};

/** 文件卡第二行：[种类 · ]大小[ · 我的文件/项目文件]（App fileSubtitle 同义）。 */
export const fileSubtitle = (b: FileBlock) =>
  [fileKind(b.name, b.mime), formatSize(b.size), b.source === "project" ? workspaceFilesTitle(b.project_id) : ""]
    .filter(Boolean).join(" · ");

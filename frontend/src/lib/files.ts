import { fileUrl } from "./api";
import type { FileBlock, OutgoingFile, ProjectFile } from "./types";

export const formatSize = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;

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

/** 一条消息最多带几个文件（上传 + 引用合计，和服务器 ws.MAX_FILES 一致）。 */
export const MAX_MESSAGE_FILES = 10;

export const extOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE");

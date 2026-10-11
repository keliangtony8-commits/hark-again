import { fileUrl } from "./api";
import type { FileBlock } from "./types";

export const formatSize = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;

export const isImage = (mime: string) => mime.startsWith("image/");

/** 文件块 → 下载地址。上传和项目文件走不同接口，统一在这里换算。 */
export const blockUrl = (b: FileBlock) =>
  b.source === "upload"
    ? fileUrl(`/api/uploads/${b.id}`)
    : fileUrl(`/api/projects/${b.project_id}/files/${b.id.split("/").map(encodeURIComponent).join("/")}`);

export const extOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE");

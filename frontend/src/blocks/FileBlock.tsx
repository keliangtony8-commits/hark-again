import { blockUrl, extOf, formatSize, isImage } from "../lib/files";
import type { FileBlock as T } from "../lib/types";
import { IconDownload } from "../ui/icons";

export default function FileBlock({ block }: { block: T }) {
  const url = blockUrl(block);
  if (isImage(block.mime)) {
    return <a className="card blk-image" href={url} target="_blank" rel="noreferrer"><img src={url} alt={block.name} loading="lazy" /></a>;
  }
  return (
    <a className="card blk-file" href={url} target="_blank" rel="noreferrer" download={block.name}>
      <span className="blk-file-ext">{extOf(block.name)}</span>
      <span className="blk-link-body">
        <div className="blk-link-title">{block.name}</div>
        <div className="blk-link-host">{formatSize(block.size)}{block.source === "project" ? " · 项目文件" : ""}</div>
      </span>
      <span className="blk-file-dl"><IconDownload /></span>
    </a>
  );
}

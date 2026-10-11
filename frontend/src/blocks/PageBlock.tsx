import { useState } from "react";
import { copyLink, previewUrl } from "../lib/pages";
import type { PageBlock as T } from "../lib/types";
import { IconCopy, IconExternal, IconLayout } from "../ui/icons";

/** 生成的网页：缩略预览 + 打开 + 复制分享链接。 */
export default function PageBlock({ block }: { block: T }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="card blk-page">
      <div className="blk-page-frame">
        <iframe src={previewUrl(block.slug)} title={block.title} sandbox="allow-scripts" loading="lazy" tabIndex={-1} />
      </div>
      <div className="blk-page-bar">
        <span className="blk-page-icon"><IconLayout size={18} /></span>
        <div className="blk-link-body"><div className="blk-link-title">{block.title}</div><div className="blk-link-host">{block.url.replace(/^https?:\/\//, "")}</div></div>
        <button className="icon-btn" aria-label="复制链接" onClick={async () => setCopied(await copyLink(block.url))}>{copied ? "✓" : <IconCopy />}</button>
        <a className="icon-btn" href={block.url} target="_blank" rel="noreferrer" aria-label="打开"><IconExternal /></a>
      </div>
    </div>
  );
}

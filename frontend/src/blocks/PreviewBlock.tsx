import { useState } from "react";
import { copyLink } from "../lib/pages";
import { PREVIEW_SANDBOX, portTitle, previewExpired, previewExpiry, shortCommand } from "../lib/preview";
import type { PreviewBlock as T } from "../lib/types";
import { IconCopy, IconExternal, IconGlobe } from "../ui/icons";

/** 端口预览卡（v1.30，= App blocks/preview_block.dart）：标题 + 端口·程序 + 有效期；打开 / 复制链接；
 *  电脑端多一个“在这里看”，卡里展开实时页面（iframe 沙盒同服务器 CSP）。过期后只剩一句“让我重新生成”。 */
export default function PreviewBlock({ block }: { block: T }) {
  const [copied, setCopied] = useState(false);
  const [inline, setInline] = useState(false);
  const [nonce, setNonce] = useState(0);
  const expired = previewExpired(block.expires_at);
  const expiry = previewExpiry(block.expires_at);
  const line = [`端口 ${block.port}`, block.command ? shortCommand(block.command) : ""].filter(Boolean).join(" · ");
  return (
    <div className="card blk-preview">
      <div className="blk-page-bar">
        <span className={`blk-preview-icon${expired ? " is-off" : ""}`}><IconGlobe size={18} /></span>
        <div className="blk-link-body">
          <div className="blk-link-title">{portTitle(block.port, block.title)}</div>
          <div className="blk-link-host">{line}</div>
          {expiry && <div className={`blk-preview-exp${expired ? " is-off" : ""}`}>{expiry}</div>}
        </div>
        {!expired && <>
          <button className="icon-btn" aria-label="复制链接" onClick={async () => setCopied(await copyLink(block.url))}>{copied ? "✓" : <IconCopy />}</button>
          <a className="icon-btn" href={block.url} target="_blank" rel="noreferrer" aria-label="在新标签页打开"><IconExternal /></a>
        </>}
      </div>
      {expired ? <p className="blk-handoff-line">链接已过期。服务还在跑的话，让我重新生成一条。</p> : (
        <div className="blk-preview-actions">
          {inline && <button className="btn btn-sm btn-ghost" onClick={() => setNonce((n) => n + 1)}>刷新</button>}
          <button className="btn btn-sm btn-ghost" aria-expanded={inline} onClick={() => setInline((v) => !v)}>{inline ? "收起" : "在这里看"}</button>
        </div>
      )}
      {inline && !expired && (
        <div className="blk-preview-frame">
          <iframe key={nonce} src={block.url} title={portTitle(block.port, block.title)} sandbox={PREVIEW_SANDBOX} />
        </div>
      )}
    </div>
  );
}

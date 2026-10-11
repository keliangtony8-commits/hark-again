import { useState } from "react";
import { copyText } from "../lib/copy";
import type { DraftBlock as D, ImagesBlock as I, SummaryBlock as S } from "../lib/types";
import CopyButton from "../ui/CopyButton";
import { IconChevronDown, IconEdit, IconImageOff, IconShare } from "../ui/icons";
import Markdown from "../ui/Markdown";

// 内容成品类的卡（= App blocks/content_blocks.dart）：草稿（拿去发）、摘要（自己读）、图片（看样子）。

/** 草稿：再深一层的小块，原样文字，右上 复制 / 分享（浏览器支持系统分享时才有）。 */
export function DraftBlock({ block }: { block: D }) {
  const canShare = typeof navigator !== "undefined" && "share" in navigator;
  return (
    <section className="blk-draft" aria-label={`草稿：${block.title}`}>
      <div className="blk-draft-head">
        <IconEdit size={16} />
        <span className="blk-draft-title">草稿 · {block.title}</span>
        <CopyButton text={block.body} label="复制草稿" />
        {canShare && (
          <button className="icon-btn sm" aria-label="分享草稿" title="分享草稿"
            onClick={() => navigator.share({ title: block.title, text: block.body }).catch(() => {})}>
            <IconShare size={16} />
          </button>
        )}
      </div>
      <div className="blk-draft-body">{block.body}</div>
    </section>
  );
}

const FOLD_CHARS = 600, FOLD_LINES = 14; // 和 App SummaryBlockView.foldable 相同
export const foldable = (md: string) => md.length > FOLD_CHARS || (md.match(/\n/g)?.length ?? 0) > FOLD_LINES;

/** 摘要：一张卡 = 一份文档（小字来源 + 标题 + Markdown）；很长时折起，展开交叉淡入整篇。 */
export function SummaryBlock({ block }: { block: S }) {
  const [open, setOpen] = useState(false);
  const fold = foldable(block.markdown);
  return (
    <article className="card blk-summary">
      <header className="blk-summary-head">
        <div>
          <h3 className="blk-summary-title">{block.title}</h3>
          {block.subtitle && <div className="blk-summary-sub">{block.subtitle}</div>}
        </div>
        <CopyButton text={copyText([block])} label="复制全文" />
      </header>
      <div key={String(open)} className={"blk-summary-body fade-in" + (fold && !open ? " folded" : "")}>
        <Markdown text={block.markdown} />
      </div>
      {fold && (
        <button className="blk-summary-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "收起" : "展开全文"}<span className={"turn" + (open ? " open" : "")}><IconChevronDown size={16} /></span>
        </button>
      )}
    </article>
  );
}

/** 图片：单张 4:3 铺满，多张横排滑动；下好了淡入，坏图留占位；点开新标签页看原图。 */
export function ImagesBlock({ block }: { block: I }) {
  const items = block.items.filter((i) => /^https?:\/\//i.test(i.url));
  if (!items.length) return null;
  return (
    <div className={"blk-images" + (items.length === 1 ? " single" : "")}>
      {items.map((it, i) => <Figure key={it.url} url={it.url} caption={it.caption} i={i} />)}
    </div>
  );
}

function Figure({ url, caption, i }: { url: string; caption?: string | null; i: number }) {
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  return (
    <figure className="blk-figure enter" style={{ ["--i" as string]: i }}>
      <a className="blk-figure-frame" href={url} target="_blank" rel="noopener noreferrer"
        aria-label={`图片${caption ? "：" + caption : ""}，打开原图`}>
        {state === "bad"
          ? <span className="blk-figure-bad"><IconImageOff /></span>
          : <img src={url} alt={caption ?? ""} loading="lazy" referrerPolicy="no-referrer" className={state === "ok" ? "ok" : ""}
              onLoad={() => setState("ok")} onError={() => setState("bad")} />}
      </a>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

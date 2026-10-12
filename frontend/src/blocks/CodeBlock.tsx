import { useLayoutEffect, useRef, useState } from "react";
import type { CodeBlock as T } from "../lib/types";

/** 代码 / 命令输出卡。live = 命令还在跑：标题旁一个呼吸点 + “运行中”，不给复制（内容还在变），输出区贴着最新一行。 */
export default function CodeBlock({ block }: { block: T }) {
  const [copied, setCopied] = useState(false);
  const pre = useRef<HTMLPreElement>(null);
  useLayoutEffect(() => {
    if (block.live && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [block.live, block.source]);
  const copy = async () => {
    await navigator.clipboard.writeText(block.source);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className={`card blk-code${block.live ? " live" : ""}`}>
      <div className="card-head">
        <span className="blk-code-title">{block.title ?? block.language ?? "代码"}</span>
        {block.live
          ? <span className="blk-code-running" role="status"><span className="job-dot" />运行中</span>
          : <button className="blk-code-copy" onClick={copy}>{copied ? "已复制" : "复制"}</button>}
      </div>
      <pre ref={pre}><code>{block.source || "等待输出…"}</code></pre>
    </div>
  );
}

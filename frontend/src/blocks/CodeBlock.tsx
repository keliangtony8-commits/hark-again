import { useState } from "react";
import type { CodeBlock as T } from "../lib/types";

export default function CodeBlock({ block }: { block: T }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(block.source);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="card blk-code">
      <div className="card-head">
        <span>{block.title ?? block.language ?? "代码"}</span>
        <button className="blk-code-copy" onClick={copy}>{copied ? "已复制" : "复制"}</button>
      </div>
      <pre><code>{block.source}</code></pre>
    </div>
  );
}

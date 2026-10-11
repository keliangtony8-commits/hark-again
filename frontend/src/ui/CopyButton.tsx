import { useEffect, useState } from "react";
import { IconCheck, IconCopy } from "./icons";

/** 复制键（= App kit CopyAction）：点后 1.5 秒内显示对勾（图标原地 pop 换），不弹提示。回复操作行、草稿卡、摘要卡共用。 */
export default function CopyButton({ text, label = "复制" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1500); return () => clearTimeout(t); }, [copied]);
  return (
    <button className="icon-btn sm" aria-label={copied ? "已复制" : label} title={copied ? "已复制" : label}
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); }}>
      <span key={copied ? "y" : "n"} className="icon-pop">{copied ? <IconCheck size={16} /> : <IconCopy />}</span>
    </button>
  );
}

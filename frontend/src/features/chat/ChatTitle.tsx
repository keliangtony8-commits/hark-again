import { useState } from "react";
import { useConversationUsage } from "../../hooks/useConversationUsage";
import { formatMoney, formatTokens, type ConversationUsage, usageLine } from "../../lib/usage";
import { Sheet } from "../../ui/kit";
import ModelUsageList from "../me/ModelUsageList";
import ConversationFilesSheet from "./ConversationFilesSheet";
import ShareSheet from "./ShareSheet";

/** 聊天顶栏标题 + 下面一行本对话用量（“¥0.012 · 3.4K token”），点那行弹出按模型明细。与 App 的 ChatTitle 同规则。 */
export default function ChatTitle({ title, conversationId, streaming }: { title: string; conversationId: string | null; streaming: boolean }) {
  const { usage } = useConversationUsage(conversationId, streaming);
  const [open, setOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [files, setFiles] = useState(false);
  const line = usage ? usageLine(usage) : null;
  return (
    <div className="chat-top-title">
      <div className="chat-top-name">{title}</div>
      {line && (
        <button key={line} className="chat-usage" onClick={() => setOpen(true)} aria-label={`本对话用量 ${line}`}>{line}</button>
      )}
      {open && usage && <UsageSheet usage={usage} onClose={() => setOpen(false)}
        onShare={() => { setOpen(false); setSharing(true); }}
        onFiles={() => { setOpen(false); setFiles(true); }} />}
      {files && conversationId && <ConversationFilesSheet conversationId={conversationId} onClose={() => setFiles(false)} />}
      {sharing && conversationId && <ShareSheet conversationId={conversationId} onClose={() => setSharing(false)} />}
    </div>
  );
}

function UsageSheet({ usage: u, onClose, onShare, onFiles }: { usage: ConversationUsage; onClose: () => void; onShare: () => void; onFiles: () => void }) {
  const t = u.total;
  const money = u.priced.length > 0;
  const prompt = t.models.reduce((s, m) => s + m.prompt_tokens, 0);
  const completion = t.models.reduce((s, m) => s + m.completion_tokens, 0);
  const unpriced = t.models.some((m) => !u.priced.includes(m.model));
  return (
    <Sheet title="本对话用量" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onFiles}>全部文件</button>
      <button className="btn btn-ghost" onClick={onShare}>分享为网页</button>
      <button className="btn btn-ghost" onClick={onClose}>关闭</button></>}>
      <div className="usage">
        <div className="usage-hero list">
          <div className="usage-big">{money ? formatMoney(t.cost, u.currency) : `${formatTokens(t.tokens)} token`}</div>
          <div className="usage-note">{t.calls} 次调用 · 输入 {formatTokens(prompt)} · 输出 {formatTokens(completion)}</div>
        </div>
        <ModelUsageList models={t.models} priced={u.priced} currency={u.currency} />
        <p className="usage-hint">
          包含这个对话里的回复、滚动摘要等所有模型调用。
          {!money ? "服务器还没配置 MODEL_PRICES，只统计 token。" : unpriced ? "“未定价”的模型只统计 token。" : ""}
        </p>
      </div>
    </Sheet>
  );
}

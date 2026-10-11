// 推理模型“思考”的两种样子（与 App features/chat/thought_view.dart 同一套）：
// ThinkingCard = 生成中、正文未到：跳点 + 思考中 + 右侧秒数 + 最新两行；
// ThoughtSummary = 正文一来就收成回复上方一行“已思考 N 秒 ›”，点开看全部思考（只留尾部 2000 字）。服务器不存，刷新就没了。
import { useEffect, useState } from "react";
import { THOUGHT_KEEP } from "../../hooks/useChat";
import type { Message } from "../../lib/types";
import { IconChevron, IconSpark } from "../../ui/icons";

/** “8 秒” / “1 分 5 秒”；不足 1 秒按 1 秒。与 App thinkDuration 相同。 */
export function thinkDuration(ms: number): string {
  const s = ms <= 1000 ? 1 : Math.round(ms / 1000);
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
}

export function ThinkingCard({ message }: { message: Message }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, []);
  return (
    <div className="thought ai-card" role="status" aria-label="正在思考">
      <div className="thought-head">
        <span className="thinking"><span /><span /><span /></span>思考中
        {message.thinkFrom && <span className="thought-time">{thinkDuration(Date.now() - message.thinkFrom)}</span>}
      </div>
      <div className="thought-tail" aria-hidden><p>{(message.thought ?? "").replace(/\s+/g, " ").trim()}</p></div>
    </div>
  );
}

export function ThoughtSummary({ message }: { message: Message }) {
  const [open, setOpen] = useState(false);
  const time = message.thinkFrom && message.thinkTo ? message.thinkTo - message.thinkFrom : null;
  const label = time == null ? "思考过程" : `已思考 ${thinkDuration(time)}`;
  const body = ((message.thought ?? "").length >= THOUGHT_KEEP ? "…" : "") + (message.thought ?? "").trim();
  return (
    <div className="thought-sum">
      <button className={`thought-toggle ${open ? "open" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconSpark size={14} />{label}<IconChevron size={14} />
      </button>
      {open && <div className="thought-full">{body}</div>}
    </div>
  );
}

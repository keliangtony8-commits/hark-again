import { useEffect, useState } from "react";
import { http } from "../../lib/api";
import {
  compactToast, contextFill, contextLine, contextTight, summaryLine,
  type CompactResult, type ConversationContext,
} from "../../lib/conversationContext";

/** 对话记忆卡（本对话用量 Sheet 里）：原文占预算多少、较早多少条已压成摘要（可展开）、“整理上文”手动压缩。
 *  与 App 的 ConversationMemoryCard 同规则；正在回复时后端 409，原因原样显示在卡片下方。 */
export default function ConversationMemory({ conversationId }: { conversationId: string }) {
  const [ctx, setCtx] = useState<ConversationContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    http.get<ConversationContext>(`/api/conversations/${conversationId}/context`)
      .then((c) => { if (live) setCtx(c); })
      .catch(() => { if (live) setCtx(null); });
    return () => { live = false; };
  }, [conversationId]);

  if (!ctx || ctx.messages === 0) return null;
  const fill = contextFill(ctx);
  const tight = contextTight(ctx);
  const summary = summaryLine(ctx);

  const compact = async () => {
    setBusy(true);
    try {
      const r = await http.post<CompactResult>(`/api/conversations/${conversationId}/compact`, {});
      setNote(compactToast(ctx, r));
      setCtx(r);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "整理失败，稍后再试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ctx-card list">
      <div className="ctx-head">
        <span className="ctx-title">对话记忆</span>
        <span key={ctx.raw_chars} className={`ctx-pct${tight ? " is-warn" : ""}`}>{Math.round(fill * 100)}%</span>
      </div>
      <div className={`meter thin${tight ? " meter-near" : ""}`} role="img" aria-label={`原文占上限 ${Math.round(fill * 100)}%`}>
        <span className="ctx-fill" style={{ transform: `scaleX(${Math.min(1, fill)})` }} />
      </div>
      <div key={contextLine(ctx)} className="usage-note ctx-line">{contextLine(ctx)}</div>
      {summary && (
        <div className="ctx-summary-row">
          <span className="usage-note">{summary}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? "收起摘要" : "查看摘要"}
          </button>
        </div>
      )}
      {open && ctx.summary && <div key={ctx.summary.length} className="ctx-summary">{ctx.summary}</div>}
      <div className="ctx-foot">
        <span className="ctx-hint">
          {ctx.compactable > 0 ? `把最后一问之前的 ${ctx.compactable} 条并进摘要，之后每轮更省 token` : "已经很精简"}
        </span>
        <button className="btn" disabled={busy || ctx.compactable === 0} onClick={compact}>
          {busy ? "整理中…" : "整理上文"}
        </button>
      </div>
      {note && <div key={note} className="share-note ctx-note" role="status">{note}</div>}
    </div>
  );
}

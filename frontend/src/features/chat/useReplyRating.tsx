import { useEffect, useState } from "react";
import { http } from "../../lib/api";
import { FEEDBACK_GOOD, FEEDBACK_REASONS, feedbackPath, feedbackToast, isBadFeedback } from "../../lib/feedback";
import { IconThumbDown, IconThumbUp } from "../../ui/icons";
import { type MenuItem, Sheet } from "../../ui/kit";

/** 回复评价（v2.64，= App features/chat/reply_rating.dart）——网页唯一入口；§I 起是“⋯”菜单里的两项（items），不再是两颗图标。
 *  有用：点一下记下、已记过就是“取消“有用””；不好：弹原因单（必选一个原因 + 可选一句补充），已经不好再点 = 取消。
 *  先在本机换上，服务器没收下换回原样；结果（note）由 MessageView 画在回复下的状态行。报告里存什么只在后端 app/feedback.py。 */
export function useReplyRating(messageId: string, initial?: string | null) {
  const [kind, setKind] = useState<string | null>(initial ?? null);
  const [note, setNote] = useState<{ text: string; err?: boolean } | null>(null);
  const [asking, setAsking] = useState(false);
  useEffect(() => setKind(initial ?? null), [initial]);

  const send = async (next: string | null, extra?: string) => {
    const old = kind;
    setKind(next); setAsking(false);
    try {
      if (next === null) await http.del(feedbackPath(messageId));
      else await http.post(feedbackPath(messageId), { kind: next, ...(extra ? { note: extra } : {}) });
      setNote({ text: feedbackToast(next) });
    } catch (e) {
      setKind(old);
      setNote({ text: e instanceof Error ? e.message : "评价没记下，稍后再试", err: true });
    }
  };

  const up = kind === FEEDBACK_GOOD;
  const down = isBadFeedback(kind);
  const items: MenuItem[] = [
    { label: up ? "取消“有用”" : "有用", icon: <IconThumbUp />, onSelect: () => void send(up ? null : FEEDBACK_GOOD) },
    { label: down ? "取消评价" : "不好", icon: <IconThumbDown />, onSelect: () => (down ? void send(null) : setAsking(true)) },
  ];
  return {
    items,
    note: note ? <span key={note.text} className={`msg-saved fade-in${note.err ? " is-err" : ""}`} role="status">{note.text}</span> : null,
    sheet: asking ? <ReasonSheet onPick={(k, t) => void send(k, t)} onClose={() => setAsking(false)} /> : null,
  };
}

function ReasonSheet({ onPick, onClose }: { onPick: (kind: string, note: string) => void; onClose: () => void }) {
  const [kind, setKind] = useState<string | null>(null);
  const [text, setText] = useState("");
  return (
    <Sheet title="哪里不好？" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!kind} onClick={() => kind && onPick(kind, text.trim())}>提交</button>
    </>}>
      <p className="desc">会连同这条回复和每一步的记录存一份报告，在“我的 → 反馈”里能看到。</p>
      <div className="rate-reasons">
        {FEEDBACK_REASONS.map((r) => (
          <button key={r.kind} className={`chip ${kind === r.kind ? "on" : ""}`} aria-pressed={kind === r.kind} onClick={() => setKind(r.kind)}>{r.label}</button>
        ))}
      </div>
      <label className="form-field"><span>补充一句（可不填）</span>
        <textarea rows={3} value={text} placeholder="比如：应该先问我要哪天的票" onChange={(e) => setText(e.target.value)} /></label>
    </Sheet>
  );
}

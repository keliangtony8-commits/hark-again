import { type RefObject, useEffect, useRef, useState } from "react";
import { distanceToBottom } from "./useStickToBottom";

/** 显隐节奏（= App Timing.pillHold / Motion.pillReveal / Motion.pillHide）。 */
export const PILL_HOLD_MS = 1500;
export const PILL_REVEAL = 24;
export const PILL_HIDE = 4;

/**
 * v2.91 §N 项目对话的标题药丸（= App features/chat/title_pill.dart）：浮在标题栏下方，写这段对话的总结标题（列表同一个 title）。
 * 浮出：进入一段已有对话；往上翻看历史累计 >24px；标题被重新总结（旧标题非空且变了）。
 * 收起：往下滑 >4px、停 1.5 秒、回到底部。新建对话（还没标题）、占位标题出现都不弹。
 * 滚动只走 passive 监听 + rAF 合帧，只在显隐翻转时 setState（不跟着每帧渲染）。换对话时贴底那一跳不算“回到底部”。
 */
export default function TitlePill({ scroller, conversationId, title }: { scroller: RefObject<HTMLDivElement>; conversationId: string | null; title: string }) {
  const [shown, setShown] = useState(false);
  const on = useRef(false);
  const idle = useRef(0);
  const settling = useRef(false);
  const prev = useRef<{ id: string | null; title: string }>({ id: null, title: "" });

  const set = (v: boolean) => { if (on.current !== v) { on.current = v; setShown(v); } };
  const arm = () => { clearTimeout(idle.current); idle.current = window.setTimeout(() => set(false), PILL_HOLD_MS); };
  const hide = () => { clearTimeout(idle.current); set(false); };
  const show = () => { set(true); arm(); };

  useEffect(() => {
    const p = prev.current;
    prev.current = { id: conversationId, title };
    if (p.id !== conversationId) {
      if (!conversationId || !title) { hide(); return; }
      settling.current = true;   // 换对话：ChatView 把列表贴到底（pin），这一跳不算用户滑回底部
      show();
      let r2 = 0;
      const r1 = requestAnimationFrame(() => { r2 = requestAnimationFrame(() => { settling.current = false; }); });
      return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2); settling.current = false; };
    }
    if (p.title && title && p.title !== title) show();   // 话题变了、标题被重新总结
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, title]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    let last = el.scrollTop, up = 0, down = 0, frame = 0;
    const tick = () => {
      frame = 0;
      const top = el.scrollTop, d = last - top;   // d > 0 = 往上翻看历史
      last = top;
      if (settling.current || d === 0) return;
      if (distanceToBottom(el) <= 2) { up = down = 0; hide(); return; }   // 回到底部
      if (d > 0) { down = 0; up += d; if (up > PILL_REVEAL) set(true); }
      else { up = 0; down -= d; if (down > PILL_HIDE) { hide(); return; } }   // 往下滑
      if (on.current) arm();
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(tick); };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => { el.removeEventListener("scroll", onScroll); cancelAnimationFrame(frame); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scroller]);

  useEffect(() => () => clearTimeout(idle.current), []);

  return (
    <div className="title-pill-slot" aria-hidden={!shown || !title}>
      <div className={`title-pill glass raised ${shown && title ? "shown" : ""}`}>{title}</div>
    </div>
  );
}

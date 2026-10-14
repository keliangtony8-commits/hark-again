import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { fileUrl, http } from "../lib/api";
import {
  SCREEN_FAST, TAKEOVER_DRAG_SLOP, TAKEOVER_HINT, TAKEOVER_INPUT_MS, TAKEOVER_KEYS, TAKEOVER_KEYS_HINT, browserScreenLabel, handoffStateLine, takeoverPoint,
} from "../lib/browserView";
import type { BrowserBlock as T } from "../lib/types";
import { IconBack, IconClose, IconRefresh, IconSend } from "../ui/icons";
import { HandoffBar } from "./HandoffBar";

/** v2.82 浏览器接管页（docs/home-redesign.md §H，= App blocks/browser_takeover.dart）：全屏遮罩，卡片只做预览 + 入口。
 *  电脑端手势：点一下 = 点网页；滚轮 = 滚网页（攒 TAKEOVER_INPUT_MS 发一次）；按住移动超过 TAKEOVER_DRAG_SLOP = 拖动（down → move… → up，滑块验证码）；
 *  画面获得焦点时直接打字：可见字符当文字、TAKEOVER_KEYS 原样转发、粘贴 = 文字；中文输入法用底栏的输入框（空着发送 = 回车）。
 *  Esc / 关闭键关页。助手在等你时顶部出 HandoffBar，答完关页（onAnswer 返回 false = 没连上，留着）。 */
export default function BrowserTakeover({ block, onAnswer, onClose }: {
  block: T; onAnswer?: (done: boolean) => boolean; onClose: () => void;
}) {
  const session = block.session || "main";
  const stage = useRef<HTMLDivElement>(null);
  const [tick, setTick] = useState(0);
  const [touched, setTouched] = useState(false);
  const [offline, setOffline] = useState(false);
  const [keys, setKeys] = useState("");
  const pending = useRef({ dx: 0, dy: 0, at: null as { x: number; y: number } | null, text: "", move: null as { x: number; y: number } | null });
  const flushTimer = useRef<number | null>(null);
  const press = useRef<{ x: number; y: number; dragging: boolean } | null>(null);

  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) setTick((t) => t + 1); }, SCREEN_FAST);
    stage.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); onClose(); } };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { clearInterval(id); document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; if (flushTimer.current) clearTimeout(flushTimer.current); };
  }, [onClose]);

  const post = async (path: string, body: Record<string, unknown>) => {
    try { await http.post(path, { ...body, session }); } catch { /* 画面会说明一切；下一次操作再试 */ }
    setTick((t) => t + 1);
  };

  const at = (e: { clientX: number; clientY: number }) => {
    const r = stage.current!.getBoundingClientRect();
    return takeoverPoint(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
  };

  const flush = () => {
    flushTimer.current = null;
    const p = pending.current;
    if (p.move) { http.post("/api/browser/mouse", { ...p.move, kind: "move", session }).catch(() => undefined); p.move = null; }
    if (Math.abs(p.dx) >= 1 || Math.abs(p.dy) >= 1) {
      post("/api/browser/scroll", { ...(p.at ?? { x: 0.5, y: 0.5 }), dx: Math.round(p.dx), dy: Math.round(p.dy) });
      p.dx = p.dy = 0;
    }
    if (p.text) { post("/api/browser/keyboard", { text: p.text }); p.text = ""; }
  };
  const schedule = () => { if (flushTimer.current == null) flushTimer.current = window.setTimeout(flush, TAKEOVER_INPUT_MS); };

  // 鼠标：按下记下位置；移动超过阈值 = 开始拖（down），之后 move；松开：拖过 = up，没拖 = 点一下
  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setTouched(true);
    stage.current?.focus();
    press.current = { x: e.clientX, y: e.clientY, dragging: false };
  };
  const onMove = (e: React.MouseEvent) => {
    const p = press.current;
    if (!p) return;
    if (!p.dragging && Math.hypot(e.clientX - p.x, e.clientY - p.y) > TAKEOVER_DRAG_SLOP) {
      const start = at({ clientX: p.x, clientY: p.y });
      if (!start) { press.current = null; return; }
      p.dragging = true;
      post("/api/browser/mouse", { ...start, kind: "down" });
    }
    if (p.dragging) { const to = at(e); if (to) { pending.current.move = to; schedule(); } }
  };
  const onUp = (e: React.MouseEvent) => {
    const p = press.current;
    press.current = null;
    if (!p) return;
    const pt = at(e);
    if (p.dragging) {
      if (flushTimer.current) { clearTimeout(flushTimer.current); flush(); }
      if (pt) post("/api/browser/mouse", { ...pt, kind: "up" });
    } else if (pt) post("/api/browser/mouse", pt);
  };

  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => { // 非被动：要 preventDefault，别让外层页面滚
      e.preventDefault();
      setTouched(true);
      const k = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
      pending.current.dx += e.deltaX * k;
      pending.current.dy += e.deltaY * k;
      pending.current.at = at(e) ?? pending.current.at;
      schedule();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" || e.nativeEvent.isComposing) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return; // 粘贴走 onPaste；其他快捷键留给浏览器
    if (TAKEOVER_KEYS.has(e.key)) {
      e.preventDefault();
      flush();
      post("/api/browser/keyboard", { key: e.key });
    } else if (e.key.length === 1) {
      e.preventDefault();
      pending.current.text += e.key;
      schedule();
    }
    setTouched(true);
  };
  const onPaste = (e: React.ClipboardEvent) => {
    const t = e.clipboardData.getData("text");
    if (!t) return;
    e.preventDefault();
    pending.current.text += t;
    schedule();
  };

  const sendKeys = () => { const t = keys; setKeys(""); post("/api/browser/keyboard", t ? { text: t } : { key: "Enter" }); };
  const answer = (done: boolean) => {
    if (!onAnswer) return;
    if (!onAnswer(done)) { setOffline(true); return; }
    onClose();
  };

  const h = block.handoff ?? null;
  const line = h && h.state !== "pending" ? handoffStateLine(h) : "";
  const src = `${fileUrl("/api/browser/screen")}&session=${encodeURIComponent(session)}&t=${tick}`;
  return createPortal(
    <div className="takeover" role="dialog" aria-modal="true" aria-label={`接管 ${block.site ?? "云浏览器"}`}>
      <div className="takeover-head">
        <button className="icon-btn" aria-label="关闭" title="关闭（Esc）" onClick={onClose}><IconClose /></button>
        <b className="takeover-site">{block.site ?? "云浏览器"}</b>
        <i className="live-dot" />
      </div>
      {h && h.state === "pending" && <HandoffBar key={h.id} reason={h.reason} offline={offline} onAnswer={onAnswer ? answer : undefined} />}
      {line && <p className="blk-handoff-line">{line}</p>}
      <div ref={stage} className="takeover-stage" tabIndex={0} role="img" aria-label={browserScreenLabel(true, false, block.site)}
        onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={(e) => press.current?.dragging && onUp(e)}
        onKeyDown={onKeyDown} onPaste={onPaste}>
        <img className="takeover-screen" alt="" src={src} draggable={false} />
      </div>
      <p className={`takeover-hint ${touched ? "gone" : ""}`}>{TAKEOVER_HINT}</p>
      <div className="takeover-bar glass">
        <button className="icon-btn" aria-label="后退" title="后退" onClick={() => post("/api/browser/nav", { action: "back" })}><IconBack /></button>
        <button className="icon-btn" aria-label="刷新" title="刷新" onClick={() => post("/api/browser/nav", { action: "reload" })}><IconRefresh /></button>
        <input value={keys} onChange={(e) => setKeys(e.target.value)} placeholder={TAKEOVER_KEYS_HINT} type="text" autoComplete="off"
          onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && sendKeys()} />
        <button className="send-btn" onClick={sendKeys} aria-label="发到网页"><IconSend /></button>
      </div>
    </div>,
    document.body,
  );
}

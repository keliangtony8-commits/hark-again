import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { BrowserLive } from "../lib/browserLive";
import {
  TAKEOVER_DRAG_SLOP, TAKEOVER_HINT, TAKEOVER_INPUT_MS, TAKEOVER_KEYS, TAKEOVER_KEYS_HINT, browserScreenLabel, handoffStateLine, takeoverFit, takeoverHold, takeoverPoint,
} from "../lib/browserView";
import type { BrowserBlock as T } from "../lib/types";
import { IconBack, IconClose, IconRefresh, IconSend } from "../ui/icons";
import { useSkyCover } from "../ui/Sky";
import { HandoffBar } from "./HandoffBar";
import { LiveScreen } from "./LiveScreen";

/** v2.82 浏览器接管页（docs/home-redesign.md §H，= App blocks/browser_takeover.dart）：全屏遮罩，卡片只做预览 + 入口。
 *  电脑端手势：点一下 = 点网页（带真实按住时长 hold）；滚轮 = 滚网页（攒 TAKEOVER_INPUT_MS 发一次）；按住移动超过 TAKEOVER_DRAG_SLOP = 拖动（down → move… → up，滑块验证码）；
 *  鼠标没按住时移动 = 悬停（同样攒着发 move：悬停菜单、人机验证看得到鼠标移过来）；
 *  画面获得焦点时直接打字：可见字符当文字、TAKEOVER_KEYS 原样转发、粘贴 = 文字；中文输入法用底栏的输入框（空着发送 = 回车）。
 *  Esc / 关闭键关页。助手在等你时顶部出 HandoffBar，答完关页（onAnswer 返回 false = 没连上，留着）。
 *  v2.89：画面和输入走卡片的同一条实时连接（live，推流），开着时 hold 住并报画面宽度。 */
export default function BrowserTakeover({ block, live, onAnswer, onClose }: {
  block: T; live: BrowserLive; onAnswer?: (done: boolean) => boolean; onClose: () => void;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  useSkyCover(root); // 整屏实色：进场完成后壁纸柔光停渲染（v3.3 B4）
  const [touched, setTouched] = useState(false);
  const [offline, setOffline] = useState(false);
  const [keys, setKeys] = useState("");
  const pending = useRef({ dx: 0, dy: 0, at: null as { x: number; y: number } | null, text: "", move: null as { x: number; y: number } | null });
  const flushTimer = useRef<number | null>(null);
  const press = useRef<{ x: number; y: number; dragging: boolean } | null>(null);
  const downAt = useRef(0); // pointerdown 的时刻：触屏上兼容 mousedown 要到抬手才补发，按住时长得从这里量

  useEffect(() => {
    live.hold();
    const report = () => { const r = stage.current?.getBoundingClientRect(); if (r) live.view(takeoverFit(r.width, r.height).width * devicePixelRatio); };
    report();
    window.addEventListener("resize", report);
    stage.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); onClose(); } };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { live.release(); window.removeEventListener("resize", report); document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; if (flushTimer.current) clearTimeout(flushTimer.current); };
  }, [onClose, live]);

  /** 一条接管输入；没连上就丢掉（画面上写着“正在重连…”）。 */
  const post = (m: Record<string, unknown>) => { live.send(m); };

  /** 屏上一点 → 网页 0–1：按画面框本身（.takeover-screen，CSS 里 contain 好的那个）换算，不再按舞台推算它在哪。 */
  const at = (e: { clientX: number; clientY: number }) => {
    const el = stage.current!.querySelector(".takeover-screen") ?? stage.current!;
    const r = el.getBoundingClientRect();
    return takeoverPoint(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
  };

  const flush = () => {
    flushTimer.current = null;
    const p = pending.current;
    if (p.move) { post({ t: "mouse", kind: "move", ...p.move }); p.move = null; }
    if (Math.abs(p.dx) >= 1 || Math.abs(p.dy) >= 1) {
      post({ t: "wheel", ...(p.at ?? { x: 0.5, y: 0.5 }), dx: Math.round(p.dx), dy: Math.round(p.dy) });
      p.dx = p.dy = 0;
    }
    if (p.text) { post({ t: "text", text: p.text }); p.text = ""; }
  };
  const schedule = () => { if (flushTimer.current == null) flushTimer.current = window.setTimeout(flush, TAKEOVER_INPUT_MS); };

  // 鼠标：按下记下位置；移动超过阈值 = 开始拖（down），之后 move；松开：拖过 = up，没拖 = 点一下
  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setTouched(true);
    stage.current?.focus();
    press.current = { x: e.clientX, y: e.clientY, dragging: false };
    pending.current.move = null; // 还没发的悬停不能落在按下之后（会变成按住拖回去）
    if (!downAt.current) downAt.current = e.timeStamp; // 没有 pointerdown 的老浏览器
  };
  const onMove = (e: React.MouseEvent) => {
    const p = press.current;
    if (!p) { const to = at(e); if (to) { pending.current.move = to; schedule(); } return; } // 悬停
    if (!p.dragging && Math.hypot(e.clientX - p.x, e.clientY - p.y) > TAKEOVER_DRAG_SLOP) {
      const start = at({ clientX: p.x, clientY: p.y });
      if (!start) { press.current = null; return; }
      p.dragging = true;
      post({ t: "mouse", kind: "down", ...start });
    }
    if (p.dragging) { const to = at(e); if (to) { pending.current.move = to; schedule(); } }
  };
  const onUp = (e: React.MouseEvent) => {
    const p = press.current;
    const pressedAt = downAt.current;
    press.current = null;
    downAt.current = 0;
    if (!p) return;
    const pt = at(e);
    if (p.dragging) {
      if (flushTimer.current) { clearTimeout(flushTimer.current); flush(); }
      if (pt) post({ t: "mouse", kind: "up", ...pt });
    } else if (pt) {
      pending.current.move = null; // 悬停的最后一下不要晚于这次点
      post({ t: "mouse", kind: "click", ...pt, hold: takeoverHold(pressedAt, e.timeStamp) });
    }
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
      post({ t: "key", key: e.key });
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

  const sendKeys = () => { const t = keys; setKeys(""); post(t ? { t: "text", text: t } : { t: "key", key: "Enter" }); };
  const answer = (done: boolean) => {
    if (!onAnswer) return;
    if (!onAnswer(done)) { setOffline(true); return; }
    onClose();
  };

  const h = block.handoff ?? null;
  const line = h && h.state !== "pending" ? handoffStateLine(h) : "";
  return createPortal(
    <div ref={root} className="takeover" role="dialog" aria-modal="true" aria-label={`接管 ${block.site ?? "云浏览器"}`}>
      <div className="takeover-head">
        <button className="icon-btn" aria-label="关闭" title="关闭（Esc）" onClick={onClose}><IconClose /></button>
        <b className="takeover-site">{block.site ?? "云浏览器"}</b>
        <i className="live-dot" />
      </div>
      {h && h.state === "pending" && <HandoffBar key={h.id} reason={h.reason} offline={offline} onAnswer={onAnswer ? answer : undefined} />}
      {line && <p className="blk-handoff-line">{line}</p>}
      <div ref={stage} className="takeover-stage" tabIndex={0} role="img" aria-label={browserScreenLabel(true, block.site)}
        onPointerDown={(e) => { downAt.current = e.timeStamp; }} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={(e) => press.current?.dragging && onUp(e)}
        onKeyDown={onKeyDown} onPaste={onPaste}>
        <LiveScreen live={live} site={block.site} className="takeover-screen" />
      </div>
      <p className={`takeover-hint ${touched ? "gone" : ""}`}>{TAKEOVER_HINT}</p>
      <div className="takeover-bar glass">
        <button className="icon-btn" aria-label="后退" title="后退" onClick={() => post({ t: "nav", action: "back" })}><IconBack /></button>
        <button className="icon-btn" aria-label="刷新" title="刷新" onClick={() => post({ t: "nav", action: "reload" })}><IconRefresh /></button>
        <input value={keys} onChange={(e) => setKeys(e.target.value)} placeholder={TAKEOVER_KEYS_HINT} type="text" autoComplete="off"
          onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && sendKeys()} />
        <button className="send-btn" onClick={sendKeys} aria-label="发到网页"><IconSend /></button>
      </div>
    </div>,
    document.body,
  );
}

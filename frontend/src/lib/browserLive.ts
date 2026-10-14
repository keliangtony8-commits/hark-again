// 浏览器实时画面的连接（v2.89 §M，= App blocks/browser_live.dart；取代 v2.82 截图轮询 + 点按 HTTP）：
// 一条 WS /api/browser/live，下行 JPEG 帧（画面变了才推），上行接管输入（0–1 坐标，格式见 docs/protocol.md）。
// 卡片拥有它，接管页复用同一个；hold()/release() 计数：卡片可见或接管页开着才连；网页隐藏就断，回来重连（服务器先补最后一帧）。
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { auth, server } from "./api";
import { liveRetryDelay, liveStateAfterClose, type LiveState } from "./browserView";

export class BrowserLive {
  state: LiveState = "connecting";
  /** 最新一帧的 blob: 地址（旧的随新帧释放）。 */
  frame: string | null = null;
  opening: boolean;
  private ws: WebSocket | null = null;
  private retry: number | null = null;
  private attempt = 0;
  private holds = 0;
  private px = 0;
  private reopening = false;
  private listeners = new Set<() => void>();
  private onVis = () => (document.hidden ? this.hang() : this.resume());

  constructor(private session: string, opening: boolean, private connect = (url: string) => new WebSocket(url)) {
    this.opening = opening;
  }

  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  private emit() { this.listeners.forEach((f) => f()); }
  private set(s: LiveState) { if (s !== this.state) { this.state = s; this.emit(); } }

  setOpening(v: boolean) {
    if (v === this.opening) return;
    this.opening = v;
    if (!v && this.state === "reconnecting" && !this.ws) this.dial(); // 打开完成：马上连
  }

  hold() {
    if (this.holds++ === 0) { document.addEventListener("visibilitychange", this.onVis); this.dial(); }
  }

  release() {
    if (this.holds === 0 || --this.holds > 0) return;
    document.removeEventListener("visibilitychange", this.onVis);
    this.hang();
  }

  /** closed / down 时的“重新打开”：带 open=1，服务器用存好的登录回到最后网址。 */
  reopen = () => { this.reopening = true; this.attempt = 0; this.hang(); this.set("connecting"); this.dial(); };

  /** 画面的物理像素宽：服务器按它缩小帧。同一个值不重发。 */
  view(px: number) {
    const v = Math.round(px);
    if (v <= 0 || v === this.px) return;
    this.px = v;
    this.send({ t: "view", px: v });
  }

  /** 接管输入；没连上返回 false（画面上写着“正在重连…”）。 */
  send(m: Record<string, unknown>): boolean {
    if (!this.ws || this.state !== "live" || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(m));
    return true;
  }

  private url() {
    const q = new URLSearchParams({ token: auth.get() ?? "", session: this.session });
    if (this.reopening) q.set("open", "1");
    return server.wsUrl(`/api/browser/live?${q}`);
  }

  private dial() {
    if (this.retry != null) { clearTimeout(this.retry); this.retry = null; }
    if (this.holds === 0 || document.hidden || this.ws) return;
    const ws = this.connect(this.url());
    this.reopening = false;
    ws.binaryType = "blob";
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.attempt = 0;
      this.set("live");
      if (this.px > 0) ws.send(JSON.stringify({ t: "view", px: this.px }));
    };
    ws.onmessage = (e) => {
      if (this.ws !== ws || !(e.data instanceof Blob)) return;
      const prev = this.frame;
      this.frame = URL.createObjectURL(e.data.type ? e.data : new Blob([e.data], { type: "image/jpeg" }));
      if (prev) URL.revokeObjectURL(prev); // 一帧一个地址：旧的立刻释放
      this.state = "live";
      this.emit();
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.ws = null;
      const next = liveStateAfterClose(e.code, this.opening);
      this.set(next);
      if (next === "reconnecting" && this.holds > 0 && !document.hidden) this.retry = window.setTimeout(() => this.dial(), liveRetryDelay(this.attempt++));
    };
  }

  private hang() {
    if (this.retry != null) { clearTimeout(this.retry); this.retry = null; }
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  private resume() {
    if (this.state === "closed" || this.state === "down") return; // 等用户点“重新打开”
    this.set("reconnecting");
    this.dial();
  }
}

/** 卡片用：一个会话一条连接；active = 卡片可见 / 服务没坏。 */
export function useBrowserLive(session: string, opening: boolean, active: boolean) {
  const live = useMemo(() => new BrowserLive(session, opening), [session]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { live.setOpening(opening); }, [live, opening]);
  useEffect(() => {
    if (!active) return;
    live.hold();
    return () => live.release();
  }, [live, active]);
  useEffect(() => () => { if (live.frame) URL.revokeObjectURL(live.frame); }, [live]);
  return live;
}

/** 订阅连接状态和最新帧（重画用）。 */
export function useLiveSnapshot(live: BrowserLive) {
  const state = useSyncExternalStore(live.subscribe, () => live.state);
  const frame = useSyncExternalStore(live.subscribe, () => live.frame);
  return { state, frame };
}

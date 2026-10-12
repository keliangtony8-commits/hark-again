import type { ServerEvent } from "./types";
import { auth, notifyUnauthorized, server } from "./api";

/** 连接状态：connecting = 首次连接/重连中，open = 可发，down = 断开（等待重连）。 */
export type LinkStatus = "connecting" | "open" | "down";

/** 重连节奏（同 App core/chat_socket.dart + tokens Timing；取自 Codex remote_control next_reconnect_delay，Apache-2.0，modified）：
 *  1 s 起翻倍、封顶 10 s、乘 [0.5, 1] 抖动；连上满 60 s 才清零退避；服务器回过 pong 后 60 s 没收到任何东西 = 死线，主动重连。 */
const BACKOFF_MIN = 1000, BACKOFF_MAX = 10_000, STABLE_MS = 60_000, PING_MS = 25_000, DEAD_MS = 60_000;

export function reconnectDelay(attempt: number, jitter = Math.random()): number {
  const base = Math.min(BACKOFF_MIN * 2 ** Math.min(Math.max(attempt, 0), 10), BACKOFF_MAX);
  return base * (0.5 + 0.5 * Math.min(Math.max(jitter, 0), 1));
}

/**
 * 带自动重连的 WebSocket（对应 App 的 core/chat_socket.dart）。
 * 只管线路：报告连接状态、send() 写不出去就返回 false。不排队——
 * 消息的发送状态（待发送/失败）和断线续传（turn.resume）只归 useChat 管，避免两处各排一份队。
 */
export class ChatSocket {
  private ws?: WebSocket;
  private retry = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private ping?: ReturnType<typeof setInterval>;
  private closed = false;
  private heartbeat = false;   // 服务器回过 pong（老服务器不回，不能按“多久没收到”误判）
  private lastRx = Date.now();
  private openedAt = 0;
  status: LinkStatus = "connecting";

  constructor(private onEvent: (e: ServerEvent) => void, private onStatus: (s: LinkStatus) => void = () => {}) {
    this.connect();
  }

  private setStatus(s: LinkStatus) {
    if (s === this.status) return;
    this.status = s;
    this.onStatus(s);
  }

  private connect() {
    clearTimeout(this.timer);
    const ws = new WebSocket(server.wsUrl(`/ws?token=${encodeURIComponent(auth.get() ?? "")}`));
    this.ws = ws;
    ws.onopen = () => {
      this.openedAt = this.lastRx = Date.now();
      this.setStatus("open");
      clearInterval(this.ping);
      this.ping = setInterval(() => this.beat(ws), PING_MS);
    };
    ws.onmessage = (m) => {
      this.lastRx = Date.now();
      const e = JSON.parse(m.data);
      if (e.type === "pong") { this.heartbeat = true; return; }
      this.onEvent(e);
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;          // reconnectNow() / 死线换掉的旧连接
      this.lost();
      if (e.code === 4401) return notifyUnauthorized();
      if (this.closed) return;
      this.schedule();
    };
  }

  private beat(ws: WebSocket) {
    if (this.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
    if (this.heartbeat && Date.now() - this.lastRx > DEAD_MS) {
      this.ws = undefined;                 // 线死了系统还没报：丢掉它重连
      ws.close();
      this.lost();
      this.schedule();
      return;
    }
    ws.send(JSON.stringify({ type: "ping" }));
  }

  private lost() {
    clearInterval(this.ping);
    if (this.openedAt && Date.now() - this.openedAt >= STABLE_MS) this.retry = 0;
    this.openedAt = 0;
    this.setStatus("down");
  }

  private schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(), reconnectDelay(this.retry++));
  }

  /** 写出一条；线不通返回 false，由调用方决定排队还是报错。 */
  send(payload: object): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(payload));
    return true;
  }

  /** 用户点“重试”：跳过退避立刻重连。 */
  reconnectNow() {
    if (this.closed || this.ws?.readyState === WebSocket.OPEN) return;
    this.retry = 0;
    const old = this.ws;
    this.ws = undefined;
    old?.close();
    this.connect();
  }

  close() { this.closed = true; clearTimeout(this.timer); clearInterval(this.ping); this.ws?.close(); }
}

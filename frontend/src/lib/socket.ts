import type { ServerEvent } from "./types";
import { auth, notifyUnauthorized, server } from "./api";

/** 连接状态：connecting = 首次连接/重连中，open = 可发，down = 断开（等待重连）。 */
export type LinkStatus = "connecting" | "open" | "down";

/**
 * 带自动重连的 WebSocket（对应 App 的 core/chat_socket.dart）。
 * 只管线路：报告连接状态、send() 写不出去就返回 false。不排队——
 * 消息的发送状态（待发送/失败）只归 useChat 的发件箱管，避免两处各排一份队。
 */
export class ChatSocket {
  private ws?: WebSocket;
  private retry = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private closed = false;
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
    ws.onopen = () => { this.retry = 0; this.setStatus("open"); };
    ws.onmessage = (m) => this.onEvent(JSON.parse(m.data));
    ws.onclose = (e) => {
      if (this.ws !== ws) return;          // reconnectNow() 换掉的旧连接
      if (e.code === 4401) return notifyUnauthorized();
      if (this.closed) return;
      this.setStatus("down");
      this.timer = setTimeout(() => this.connect(), Math.min(1000 * 2 ** this.retry++, 10000));
    };
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

  close() { this.closed = true; clearTimeout(this.timer); this.ws?.close(); }
}

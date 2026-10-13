// 账户连接（v2.36，后端 app/connector_accounts.py）：连接器状态 + 聊天连接卡的那一行和按钮。
// 与 App models/connect.dart 同规则：卡片按连接器列表实时状态说话，不信卡里的快照。
import { http } from "./api";
import type { ConnectBlock, Connector } from "./types";

export type ConnectStatus = "connected" | "expired" | "available" | "unconfigured";
export type ConnectTone = "action" | "done" | "warning" | "off";

/** 老服务器没有 status：按账户 / 配置推。 */
export const connectorStatus = (c: Connector): ConnectStatus =>
  (c.status as ConnectStatus | undefined) ?? (c.account != null ? "connected" : c.configured ? "available" : "unconfigured");

const who = (head: string, account?: string | null) => (account ? `${head} · ${account}` : head);

export function connectCardState(b: ConnectBlock, live?: Connector | null): { line: string; button: string | null; tone: ConnectTone } {
  if (!live) return { line: b.desc ?? "", button: b.reconnect ? "重新连接" : `连接 ${b.name}`, tone: "action" };
  switch (connectorStatus(live)) {
    case "connected": return { line: who("已连接", live.account), button: b.reconnect ? "换个账户" : null, tone: "done" };
    case "expired": return { line: who("授权失效", live.account), button: "重新连接", tone: "warning" };
    case "unconfigured": return { line: "服务器还没配置这个应用", button: null, tone: "off" };
    default: return { line: live.desc || b.desc || "", button: `连接 ${b.name}`, tone: "action" };
  }
}

/** 发起授权：问服务器要地址后整页跳过去，授权完回到 #/me/connectors。连接器页和连接卡都只调这里。 */
export async function startConnect(provider: string): Promise<void> {
  window.location.href = (await http.get<{ url: string }>(`/api/connectors/${provider}/start`)).url;
}

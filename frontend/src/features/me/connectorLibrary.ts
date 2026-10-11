// 连接器页与保险箱页的纯逻辑。与 App lib/features/me/connector_library.dart 同规则。
import type { Connector, McpServerInfo, VaultSecret } from "../../lib/types";

/** 已连接 → 可连接（服务器配好了）→ 未配置；同组保持服务器顺序。 */
export function sortAccounts(list: Connector[]): Connector[] {
  const rank = (c: Connector) => (c.account ? 0 : c.configured ? 1 : 2);
  return list.map((c, i) => ({ c, i })).sort((a, b) => rank(a.c) - rank(b.c) || a.i - b.i).map((x) => x.c);
}

/** MCP 服务器：有问题的排最前（要你处理的先看到），其余保持添加顺序。 */
export function sortServers(list: McpServerInfo[]): McpServerInfo[] {
  const rank = (s: McpServerInfo) => (mcpProblemText(s) ? 0 : 1);
  return list.map((s, i) => ({ s, i })).sort((a, b) => rank(a.s) - rank(b.s) || a.i - b.i).map((x) => x.s);
}

/** 页头小标签；servers 为 null = MCP 还在加载，先不说这部分。 */
export function connectorSummary(accounts: Connector[], servers: McpServerInfo[] | null): string {
  const n = accounts.filter((c) => c.account).length;
  const broken = servers ? servers.filter((s) => mcpProblemText(s)).length : 0;
  const parts = [n > 0 ? `已连接 ${n} 个账户` : "", servers && servers.length ? `${servers.length} 个 MCP 服务器` : "",
    broken ? `${broken} 个需要处理` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "还没有连接任何服务";
}

export function groupSecrets(list: VaultSecret[]) {
  return { logins: list.filter((s) => s.kind === "login"), keys: list.filter((s) => s.kind !== "login") };
}

export function vaultSummary(list: VaultSecret[]): string {
  const g = groupSecrets(list);
  const parts = [g.logins.length ? `${g.logins.length} 个网站登录` : "", g.keys.length ? `${g.keys.length} 个 API Key` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "保险箱是空的";
}

/** 脱敏说明：登录 → 用户名；Key → ••••末四位。 */
export const secretHint = (s: VaultSecret) => (s.kind === "login" ? s.username ?? "" : s.preview ? `••••${s.preview}` : "");

export const SECRET_KINDS = [
  { kind: "login", label: "网站登录", desc: "我在云浏览器里替你登录这个网站" },
  { kind: "api_key", label: "API Key", desc: "我调用这个服务时按域名带上它" },
] as const;

/** MCP 服务器行上的问题；不认识的值当没有（与 App McpServerItem.problemText 同一规则）。 */
export function mcpProblemText(s: McpServerInfo): string | null {
  return s.problem === "auth" ? "令牌被拒绝" : s.problem === "down" ? "连不上" : null;
}

// “连接的账号”页的纯逻辑。与 App lib/features/me/connector_library.dart 同规则。
import type { Connector, McpServerInfo, VaultSecret } from "../../lib/types";
import { connectorShown } from "../../lib/connect";

/** “账户”区要画的行：没配又没连过的不画（v2.90.2），已连接 → 可连接，同组保持服务器顺序。 */
export function sortAccounts(list: Connector[]): Connector[] {
  const rank = (c: Connector) => (c.account ? 0 : 1);
  return list.filter(connectorShown).map((c, i) => ({ c, i })).sort((a, b) => rank(a.c) - rank(b.c) || a.i - b.i).map((x) => x.c);
}

/** 服务器还没配、也没连过的服务商（部署者那一行与引导弹层列它们）。 */
export const missingSetup = (list: Connector[]) => list.filter((c) => c.setup && !c.account);

/** 部署者那一行的副标题：“配置 Google / GitHub 授权”。 */
export const setupLine = (missing: Connector[]) => `配置 ${missing.map((c) => c.name).join(" / ")} 授权`;

/** MCP 服务器：有问题的排最前（要你处理的先看到），其余保持添加顺序。 */
export function sortServers(list: McpServerInfo[]): McpServerInfo[] {
  const rank = (s: McpServerInfo) => (mcpProblemText(s) ? 0 : 1);
  return list.map((s, i) => ({ s, i })).sort((a, b) => rank(a.s) - rank(b.s) || a.i - b.i).map((x) => x.s);
}

/** 页头小标签：“已连接 2 个账户 · 1 个 MCP 服务器 · 3 项加密保存 · 1 个需要处理”；servers / secrets 为 null = 还在加载，先不说这部分。 */
export function connectorSummary(accounts: Connector[], servers: McpServerInfo[] | null, secrets: VaultSecret[] | null): string {
  const n = accounts.filter((c) => c.account).length;
  const broken = servers ? servers.filter((s) => mcpProblemText(s)).length : 0;
  const parts = [n > 0 ? `已连接 ${n} 个账户` : "", servers && servers.length ? `${servers.length} 个 MCP 服务器` : "",
    secrets && secrets.length ? `${secrets.length} 项加密保存` : "", broken ? `${broken} 个需要处理` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "还没有连接任何服务";
}

/** 网站登录 / API Key / 环境变量（注入电脑上的命令）严格分开。 */
export function groupSecrets(list: VaultSecret[]) {
  return {
    logins: list.filter((s) => s.kind === "login"),
    keys: list.filter((s) => s.kind !== "login" && s.kind !== "env"),
    envs: list.filter((s) => s.kind === "env"),
  };
}

/** 脱敏说明：登录 → 用户名；Key / 环境变量 → ••••末四位（短值不露）。 */
export const secretHint = (s: VaultSecret) => (s.kind === "login" ? s.username ?? "" : s.preview ? `••••${s.preview}` : "");

/** 行副标题：登录 / Key 用在哪些域名（Key 不走默认 Authorization 时再说带法，v2.52 后端 app/api_keys.py）；环境变量是程序里怎么读它。 */
export const secretWhere = (s: VaultSecret) => {
  if (s.kind === "env") return `电脑上的命令里读 $${s.name}`;
  const hosts = s.hosts.join("、");
  if (s.kind === "login") return hosts;
  if (s.query_param) return `${hosts} · 网址参数 ${s.query_param}`;
  return (s.header_name || "Authorization").toLowerCase() === "authorization" ? hosts : `${hosts} · 请求头 ${s.header_name}`;
};

export const RESERVED_ENV = new Set(["PATH", "HOME", "LANG", "SHELL", "TMPDIR", "USER", "LOGNAME", "TERM", "COLORTERM", "PWD",
  "OLDPWD", "HOSTNAME", "SHLVL", "IFS", "BASH_ENV", "ENV", "PS1", "LD_PRELOAD", "LD_LIBRARY_PATH", "STDIN_B64"]);

/** 规范化变量名：去空白、去开头的 $、转大写（与后端 command_env.check_name 同规则）。 */
export const envName = (raw: string) => raw.trim().replace(/^\$+/, "").toUpperCase();

/** 本地预检，合格返回 null（后端还会再查一次）。 */
export function envNameError(raw: string): string | null {
  const n = envName(raw);
  if (!/^[A-Z][A-Z0-9_]{1,63}$/.test(n)) return "变量名只能用大写字母、数字和下划线，字母开头";
  if (RESERVED_ENV.has(n)) return `${n} 是系统变量，不能覆盖`;
  return null;
}

/** 环境变量值至少几个字（太短没法在输出里可靠打码；后端 command_env.VALUE_MIN）。 */
export const ENV_VALUE_MIN = 6;

export const SECRET_KINDS = [
  { kind: "login", label: "网站登录", desc: "我在云浏览器里替你登录这个网站" },
  { kind: "api_key", label: "API Key", desc: "我调用这个服务时按域名带上它" },
  { kind: "env", label: "环境变量", desc: "由你电脑上运行的程序按名称读取，比如机器人 Token" },
] as const;

/** 页头 +“添加什么？”与起步卡共用的四类（v2.96 一页一个添加入口；= App addKinds）。 */
export const ADD_KINDS = [
  { kind: "mcp", label: "MCP 服务器", desc: "接入支持 MCP 的服务，我就能用它的工具" },
  ...SECRET_KINDS,
] as const;

/** MCP 服务器行上的问题；不认识的值当没有（与 App McpServerItem.problemText 同一规则）。 */
export function mcpProblemText(s: McpServerInfo): string | null {
  return s.problem === "auth" ? "令牌被拒绝" : s.problem === "down" ? "无法连接" : null;
}

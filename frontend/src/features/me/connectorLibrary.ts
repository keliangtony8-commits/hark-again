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

/** 网站登录 / API Key / 环境变量（注入电脑上的命令）严格分开。 */
export function groupSecrets(list: VaultSecret[]) {
  return {
    logins: list.filter((s) => s.kind === "login"),
    keys: list.filter((s) => s.kind !== "login" && s.kind !== "env"),
    envs: list.filter((s) => s.kind === "env"),
  };
}

export function vaultSummary(list: VaultSecret[]): string {
  const g = groupSecrets(list);
  const parts = [g.logins.length ? `${g.logins.length} 个网站登录` : "", g.keys.length ? `${g.keys.length} 个 API Key` : "",
    g.envs.length ? `${g.envs.length} 个环境变量` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "保险箱是空的";
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

/** MCP 服务器行上的问题；不认识的值当没有（与 App McpServerItem.problemText 同一规则）。 */
export function mcpProblemText(s: McpServerInfo): string | null {
  return s.problem === "auth" ? "令牌被拒绝" : s.problem === "down" ? "无法连接" : null;
}

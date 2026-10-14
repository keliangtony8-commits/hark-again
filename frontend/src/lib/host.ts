// 服务器主机模式（v1.49，= App models/host.dart）：后端 app/host_mode.py，接口 GET/PUT /api/host、DELETE /api/host/rules/{id}。
import { formatAgo } from "./format";
import type { ApprovalBlock, ApprovalOption } from "./types";

export const HOST_PATH = "/api/host";
export type HostRule = { id: string; prefix: string[]; text: string; uses: number; created_at?: string | null; last_used_at?: string | null };
export type HostInfo = { hostname?: string; os?: string; kernel?: string; uptime_seconds?: number | null };
export type HostStatus = { installed: boolean; enabled: boolean; reachable: boolean; host: HostInfo | null; rules: HostRule[] };

export const HOST_SECTION_TITLE = "服务器主机";
export const HOST_INSTALL_HINT = "在服务器上运行 sudo bash deploy/install.sh --host-agent 装好主机代理，再回来打开。";
export const HOST_ENABLE_TEXT = "打开后，我可在这台 VPS 本机以 root 运行命令：装系统软件、管服务、看系统日志、改配置。"
  + "每条命令都会先弹卡等你批准；你点过“以后都允许”的那类除外。随时可以在这里关掉。";
export const HOST_RULES_EMPTY = "还没有“以后都允许”的命令";
export const HOST_RULES_EMPTY_LINE = "在审批卡上选“以后都允许…”，那类命令以后就不再问你，定时任务也能用。";

export const hostCanToggle = (s: HostStatus) => s.installed || s.enabled;
export const hostToggleTitle = (s: HostStatus) => (s.enabled ? "主机模式已打开" : "主机模式已关闭");

export function hostUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return h > 0 ? `${d} 天 ${h} 小时` : `${d} 天`;
  if (h > 0) return `${h} 小时`;
  return `${m < 1 ? 1 : m} 分钟`;
}

export function hostDetail(s: HostStatus): string {
  if (!s.installed) return "还没装主机代理";
  if (!s.reachable) return "无法连接主机代理";
  const h = s.host ?? {};
  const parts = [h.hostname, h.os].filter((x): x is string => !!x);
  if (h.uptime_seconds != null) parts.push(`已开机 ${hostUptime(h.uptime_seconds)}`);
  return parts.length ? parts.join(" · ") : "主机代理在线";
}

export const hostHint = (s: HostStatus) => (s.installed && !s.reachable ? "无法连接" : null);

export function hostRuleDetail(r: HostRule, now?: Date): string {
  if (!r.uses) return r.created_at ? `${formatAgo(r.created_at, now)}加的，还没用过` : "还没用过";
  return `放行过 ${r.uses} 次${r.last_used_at ? ` · 上次 ${formatAgo(r.last_used_at, now)}` : ""}`;
}

export const hostRuleDeleteText = (r: HostRule) => `以后 ${r.text} 开头的命令又会先问你。`;

// ---------- 审批卡 ----------
export const approvalOnHost = (b: ApprovalBlock) => b.target === "host";

export function approvalGrantedLine(b: ApprovalBlock): string | null {
  if (b.state !== "approved" || !b.granted || b.granted === "once") return null;
  const o = (b.options ?? []).find((x) => x.id === b.granted);
  return o ? `已选：${o.label}` : null;
}

export const approvalExtraOptions = (b: ApprovalBlock): ApprovalOption[] => (b.options ?? []).slice(1);

export function approvalSemantics(b: ApprovalBlock): string {
  const where = approvalOnHost(b) ? `在服务器${b.host ? ` ${b.host}` : ""}上运行` : b.title;
  const state = { approved: "已批准", rejected: "已拒绝", expired: "已过期", pending: "等你确认" }[b.state];
  return `${where}：${b.detail}${b.note ? `，${b.note}` : ""}，${state}`;
}

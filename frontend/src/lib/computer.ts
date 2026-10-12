// 工作区的“电脑”（服务器 app/computer.py；App models/computer.dart 同一套规则）：状态词、说明行、内存比例、行尾小字、重启说明；
// v1.27 CPU、内存打满警示、程序行、磁盘拆分、清理、装过的工具。
import { formatSize } from "./files";
import type { ListeningPort } from "./preview";
import { jobDuration } from "./jobs";
import type { JobInfo } from "./types";

export type ComputerState = "running" | "stopped" | "none" | "unreachable";
export type ComputerStatus = {
  workspace: string; name: string;
  sandbox: { state: ComputerState; memory_used?: number | null; memory_limit?: number | null; started_at?: string | null;
    last_used_at?: string | null; idle_minutes?: number | null; outdated?: boolean;
    cpu_percent?: number | null; oom_kills?: number; processes?: ComputerProcess[] };
  disk_used: number; disk_partial: boolean; running_jobs: JobInfo[];
  storage?: ComputerStorage; tools?: InstalledTool[];
  ports?: ListeningPort[]; // v1.30 在监听的端口（只在运行中时有）
};
export type ComputerProcess = { pid: number; cpu: number; memory: number; elapsed: number; command: string };
export type ComputerStorage = { files: number; installed: number; logs: number; spill: number; cache: number; cleanable: number };
export type InstalledTool = { kind: "pip" | "npm" | string; name: string; version: string };
export type CleanupResult = { freed: number; status: ComputerStatus };

export const COMPUTER_POLL_MS = 5000;     // 有后台任务在跑时多久刷新一次（每次要问 Docker，别太密）
export const COMPUTER_MEMORY_TIGHT = 0.85; // 内存吃到多少算紧张

export const computerPath = (ws: string) => `/api/projects/${ws}/computer`;

export function computerStateLabel(s: ComputerState): string {
  switch (s) {
    case "running": return "运行中";
    case "stopped": return "休眠中";
    case "none": return "还没开机";
    default: return "连不上沙盒";
  }
}

export function computerMemoryRatio(c: ComputerStatus): number | null {
  const { state, memory_used: u, memory_limit: l } = c.sandbox;
  if (state !== "running" || u == null || l == null || l <= 0) return null;
  return Math.min(1, Math.max(0, u / l));
}

export function computerDetail(c: ComputerStatus): string {
  const disk = `文件 ${formatSize(c.disk_used)}${c.disk_partial ? "+" : ""}`;
  const sb = c.sandbox;
  switch (sb.state) {
    case "running":
      return [sb.cpu_percent != null ? `CPU ${Math.round(sb.cpu_percent)}%` : "", sb.memory_used != null ? `内存 ${formatSize(sb.memory_used)}${sb.memory_limit != null ? ` / ${formatSize(sb.memory_limit)}` : ""}` : "", disk]
        .filter(Boolean).join(" · ");
    case "stopped": return `${sb.idle_minutes != null ? `空闲 ${sb.idle_minutes} 分钟自动休眠，` : ""}用到时自动开机 · ${disk}`;
    case "none": return `第一次跑命令时开机 · ${disk}`;
    default: return `服务器上的沙盒服务没在跑，命令和后台任务暂时用不了 · ${disk}`;
  }
}

export function computerHint(c: ComputerStatus): string | null {
  if (c.running_jobs.length) return `${c.running_jobs.length} 个任务在跑`;
  if (c.sandbox.outdated && c.sandbox.state !== "unreachable") return "下次用到时更新";
  return c.sandbox.state === "running" ? "空闲" : null;
}

export const computerRestartText = (c: ComputerStatus) =>
  (c.running_jobs.length ? `会停掉 ${c.running_jobs.length} 个正在跑的后台任务。` : "") + "文件和装过的软件都在，下次用到时自动开机。";

export const computerSemantics = (c: ComputerStatus) =>
  `电脑${computerStateLabel(c.sandbox.state)}，${computerDetail(c)}${c.running_jobs.length ? `，${c.running_jobs.length} 个后台任务在跑` : ""}`;

export function computerOomNote(c: ComputerStatus): string | null {
  const n = c.sandbox.oom_kills ?? 0;
  if (c.sandbox.state !== "running" || n <= 0) return null;
  const cap = c.sandbox.memory_limit != null ? `（上限 ${formatSize(c.sandbox.memory_limit)}）` : "";
  return `内存不够，系统强制结束过 ${n} 个程序${cap}。分批处理或重启能缓过来`;
}

export function processTitle(p: ComputerProcess): string {
  const c = p.command.trim();
  const sp = c.indexOf(" ");
  const head = sp < 0 ? c : c.slice(0, sp);
  return (head.split("/").pop() ?? head) + (sp < 0 ? "" : c.slice(sp));
}

export const processLine = (p: ComputerProcess) =>
  `CPU ${Math.round(p.cpu)}% · 内存 ${formatSize(p.memory)} · 运行 ${jobDuration(p.elapsed)}`;

export const EMPTY_STORAGE: ComputerStorage = { files: 0, installed: 0, logs: 0, spill: 0, cache: 0, cleanable: 0 };

export type StorageKey = "files" | "installed" | "logs" | "spill" | "cache";
export function storageRows(st: ComputerStorage): [StorageKey, string, string, number][] {
  const rows: [StorageKey, string, string, number][] = [
    ["files", "文件", "你和我放进来的", st.files],
    ["installed", "装的软件", "pip / npm 装进 ~/.local 的", st.installed],
    ["logs", "任务日志", "后台任务的完整输出", st.logs],
    ["spill", "长输出存档", "太长没塞进对话的命令输出", st.spill],
    ["cache", "下载缓存", "pip / npm 的缓存", st.cache],
  ];
  return rows.filter(([k, , , n]) => k === "files" || n > 0);
}

export const cleanupLabel = (st: ComputerStorage) => (st.cleanable > 0 ? `清理 ${formatSize(st.cleanable)}` : null);
export const CLEANUP_TEXT = "删掉长输出存档、已结束任务的完整日志和下载缓存。文件、装的软件、正在跑的任务都不动；聊天里的任务卡照常能看结论。";
export const cleanupDone = (freed: number) => (freed > 0 ? `腾出了 ${formatSize(freed)}` : "没有可清理的了");

export function toolsSummary(tools: InstalledTool[]): string {
  if (!tools.length) return "还没装过，用到时我会 pip / npm 装进来";
  const pip = tools.filter((t) => t.kind === "pip").length, npm = tools.length - pip;
  return [pip ? `pip ${pip} 个` : "", npm ? `npm ${npm} 个` : ""].filter(Boolean).join(" · ");
}

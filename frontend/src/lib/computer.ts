// 工作区的“电脑”（服务器 app/computer.py；App models/computer.dart 同一套规则）：状态词、说明行、内存比例、行尾小字、重启说明。
import { formatSize } from "./files";
import type { JobInfo } from "./types";

export type ComputerState = "running" | "stopped" | "none" | "unreachable";
export type ComputerStatus = {
  workspace: string; name: string;
  sandbox: { state: ComputerState; memory_used?: number | null; memory_limit?: number | null; started_at?: string | null;
    last_used_at?: string | null; idle_minutes?: number | null; outdated?: boolean };
  disk_used: number; disk_partial: boolean; running_jobs: JobInfo[];
};

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
      return [sb.memory_used != null ? `内存 ${formatSize(sb.memory_used)}${sb.memory_limit != null ? ` / ${formatSize(sb.memory_limit)}` : ""}` : "", disk]
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

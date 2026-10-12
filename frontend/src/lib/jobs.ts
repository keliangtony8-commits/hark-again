// 后台任务卡的纯规则（App models/job.dart 同一套）：状态文案、语气、用时、日志尾巴、何时停止轮询。
import { formatSize } from "./files";
import type { JobBlock, JobInfo, JobState, JobUsage } from "./types";

export const JOB_FINAL: ReadonlySet<JobState> = new Set(["done", "failed", "timed_out", "cancelled", "lost"]);
export const JOB_POLL_MS = 2000;     // 运行中多久问一次进度
export const JOB_REPLY_WAIT_MS = 90_000; // 结束后等服务器“接着说”最多多久
export const JOB_LOG_LINES = 6;      // 卡片上显示日志最后几行

export const jobRunning = (j: Pick<JobInfo, "state">) => !JOB_FINAL.has(j.state);
export const jobAwaitingReply = (j: JobInfo) => !jobRunning(j) && j.followup === "pending";

/** 服务器护栏停的（连续没输出判定卡住 / 输出过大）：算出了问题，不是“已取消”。 */
export const jobAutoStopped = (j: Pick<JobInfo, "state" | "stop_reason">) => j.state === "cancelled" && !!j.stop_reason;

export type JobTone = "running" | "ok" | "problem" | "quiet";
export const jobTone = (s: JobState, autoStopped = false): JobTone =>
  autoStopped ? "problem" : s === "done" ? "ok" : s === "failed" || s === "timed_out" || s === "lost" ? "problem" : s === "cancelled" ? "quiet" : "running";

export function jobStateLabel(j: Pick<JobInfo, "state" | "exit_code" | "stop_reason" | "keep_alive" | "restart_at">): string {
  switch (j.state) {
    case "running": return j.keep_alive ? (j.restart_at ? "重启中" : "常驻 · 运行中") : "运行中";
    case "done": return "已完成";
    case "failed": return j.exit_code == null ? "失败" : `失败 · 退出码 ${j.exit_code}`;
    case "timed_out": return "超时被终止";
    case "cancelled": return jobAutoStopped(j) ? "已自动停止" : "已取消";
    case "lost": return "中断了";
  }
}

/** 卡片底部那行：状态词 · 已自动重启 N 次（常驻）· 助手在看结果（等它接着说）。 */
export const jobFootLabel = (j: JobInfo) => [jobStateLabel(j),
  ...(j.keep_alive && j.restarts ? [`已自动重启 ${j.restarts} 次`] : []),
  ...(jobAwaitingReply(j) ? ["助手在看结果"] : [])].join(" · ");

/** v1.90 占用（App models/job.dart 同一套）。解析宁缺毋错：字段缺 / 类型不对 / 负数 / 0 个进程 → null。 */
export function jobUsage(raw: unknown): JobUsage | null {
  if (!raw || typeof raw !== "object") return null;
  const { cpu, cpu_seconds, memory, processes } = raw as Record<string, unknown>;
  if (![cpu, cpu_seconds, memory, processes].every((v) => typeof v === "number" && Number.isFinite(v))) return null;
  const u = { cpu, cpu_seconds, memory, processes } as JobUsage;
  return u.cpu < 0 || u.cpu_seconds < 0 || u.memory < 0 || u.processes < 1 ? null : u;
}
/** CPU 到这么高（占配额 %）卡片上的条变警示色。 */
export const JOB_CPU_HOT = 90;
export const jobCpuLabel = (cpu: number) => (cpu >= 10 || cpu === 0 ? `${Math.round(cpu)}%` : `${cpu.toFixed(1)}%`);
export const jobMemoryLabel = (u: JobUsage) => [`内存 ${formatSize(u.memory)}`, ...(u.processes > 1 ? [`${u.processes} 个进程`] : [])].join(" · ");
export const jobUsageLabel = (u: JobUsage) => `CPU ${jobCpuLabel(u.cpu)} · ${jobMemoryLabel(u)}`;
export const jobUsageSemantics = (u: JobUsage) =>
  `占用 CPU ${jobCpuLabel(u.cpu)}，内存 ${formatSize(u.memory)}${u.processes > 1 ? `，${u.processes} 个进程` : ""}`;

/** “电脑”一节运行中任务那行的副标题：常驻的先说清，再是用时、占用和命令。 */
export const jobRowSubtitle = (j: JobInfo) => {
  const u = jobUsage(j.usage);
  return [
    ...(j.keep_alive ? [j.restart_at ? "重启中" : "常驻"] : []),
    ...(j.keep_alive && j.restarts ? [`已重启 ${j.restarts} 次`] : []),
    `运行 ${jobDuration(j.elapsed)}`, ...(u ? [jobUsageLabel(u)] : []), `$ ${j.command.split("\n")[0]}`].join(" · ");
};

const two = (n: number) => String(n).padStart(2, "0");
export function jobDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${two(s % 60)} 秒`;
  return `${Math.floor(s / 3600)} 小时 ${two(Math.floor((s % 3600) / 60))} 分`;
}

/** 读屏：一句话说清这张卡。 */
export const jobSemantics = (j: JobInfo, elapsed = j.elapsed) =>
  `${j.keep_alive ? "常驻任务" : "后台任务"} ${j.title}，${jobStateLabel(j)}${jobAutoStopped(j) ? `：${j.stop_reason}` : ""}` +
  `${j.keep_alive && j.restarts ? `，已自动重启 ${j.restarts} 次` : ""}，用时 ${jobDuration(elapsed)}` +
  `${jobRunning(j) && jobUsage(j.usage) ? `，${jobUsageSemantics(jobUsage(j.usage)!)}` : ""}`;

export function jobTailLines(tail: string, lines = JOB_LOG_LINES): string {
  const all = tail.replace(/\s+$/, "").split("\n");
  return all.length <= lines ? all.join("\n") : all.slice(-lines).join("\n");
}

/** 还没问过服务器时，用消息里落库的块先画出来。 */
export function jobFromBlock(b: JobBlock, now = Date.now()): JobInfo {
  const start = b.started_at ? Date.parse(b.started_at) : NaN;
  const end = b.finished_at ? Date.parse(b.finished_at) : now;
  return { id: b.id, title: b.title, command: b.command, state: b.state, exit_code: b.exit_code ?? null, followup: "none",
    elapsed: Number.isNaN(start) ? 0 : (end - start) / 1000, tail: b.tail ?? "", started_at: b.started_at, finished_at: b.finished_at,
    stop_reason: b.stop_reason ?? null, keep_alive: !!b.keep_alive, restarts: b.restarts ?? 0, restart_at: null };
}

// 后台任务卡的纯规则（App models/job.dart 同一套）：状态文案、语气、用时、日志尾巴、何时停止轮询。
import { changesTitle } from "./changes";
import { formatSize } from "./files";
import type { JobBlock, JobBox, JobDisk, JobInfo, JobState, JobUsage } from "./types";

export const JOB_FINAL: ReadonlySet<JobState> = new Set(["done", "failed", "timed_out", "cancelled", "lost"]);
export const JOB_POLL_MS = 2000;     // 运行中多久问一次进度
export const JOB_REPLY_WAIT_MS = 90_000; // 结束后等服务器“接着说”最多多久
export const JOB_LOG_LINES = 6;      // 卡片上显示日志最后几行

export const jobRunning = (j: Pick<JobInfo, "state">) => !JOB_FINAL.has(j.state);
export const jobAwaitingReply = (j: JobInfo) => !jobRunning(j) && j.followup === "pending";

/** 服务器护栏停的（连续没输出判定卡住 / 输出过大）：算出了问题，不是“已取消”。 */
export const jobAutoStopped = (j: Pick<JobInfo, "state" | "stop_reason">) => j.state === "cancelled" && !!j.stop_reason;

/** 卡片日志下面要写原因：护栏停的、内存超限 / 打满被结束的、常驻服务放弃重启的。 */
export const jobShowsReason = (j: Pick<JobInfo, "state" | "stop_reason">) => !jobRunning(j) && !!j.stop_reason;

/** v1.92 内存（App models/job.dart 同一套；阈值同后端 job_memory.NEAR / TIGHT）。 */
export const JOB_MEM_NEAR = 0.8;
export const JOB_BOX_TIGHT = 0.9;
const bytes = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);
export function jobBox(raw: unknown): JobBox | null {
  if (!raw || typeof raw !== "object") return null;
  const { used, limit } = raw as Record<string, unknown>;
  if (typeof used !== "number" || typeof limit !== "number" || !Number.isFinite(used) || !Number.isFinite(limit) || used < 0 || limit <= 0) return null;
  return { used: Math.min(used, limit), limit };
}
export const jobMemoryMax = (j: Pick<JobInfo, "memory_max">) => bytes(j.memory_max);
export const jobMemoryPeak = (j: Pick<JobInfo, "memory_peak">) => bytes(j.memory_peak);
export const jobMemoryNear = (j: JobInfo) => {
  const max = jobMemoryMax(j), u = jobUsage(j.usage);
  return max != null && u != null && u.memory >= max * JOB_MEM_NEAR;
};
export const jobBoxTight = (j: JobInfo) => {
  const b = jobBox(j.box);
  return jobRunning(j) && b != null && b.used >= b.limit * JOB_BOX_TIGHT;
};
export const jobBoxLabel = (b: JobBox) =>
  `这台电脑内存已用 ${Math.round((b.used * 100) / b.limit)}%（${formatSize(b.used)} / ${formatSize(b.limit)}），再涨系统会强制结束进程`;

/** v1.96 磁盘账（后端 app/job_disk.py；App models/job_disk.dart 同一套）。坏数据 → null。 */
export const JOB_DISK_LOG_SHOWN = 1 << 20;
const count = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null);
export function jobDisk(raw: unknown): JobDisk | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const log = count(r.log), written = count(r.written), files = count(r.files), overlap = r.overlap == null ? 0 : count(r.overlap);
  if (log == null || written == null || files == null || overlap == null) return null;
  const top = (Array.isArray(r.top) ? r.top : [])
    .filter((t): t is { path: string; size: number } => !!t && typeof t === "object" && typeof (t as { path?: unknown }).path === "string"
      && !!(t as { path: string }).path && typeof (t as { size?: unknown }).size === "number" && (t as { size: number }).size > 0)
    .slice(0, 3).map((t) => ({ path: t.path, size: t.size }));
  return { log, written, files, top, overlap, partial: r.partial === true };
}
export const jobDiskShown = (d: JobDisk | null): d is JobDisk => d != null && (d.files > 0 || d.log >= JOB_DISK_LOG_SHOWN);
export const jobDiskGroupName = (path: string) => (path === ".home/" ? "装的软件" : path);
export const jobDiskLabel = (d: JobDisk) => [
  ...(d.files > 0
    ? [`写入 ${formatSize(d.written)}${d.partial ? "+" : ""}`, `${d.files}${d.partial ? "+" : ""} 个文件`,
      ...(d.top.length ? [`最多 ${jobDiskGroupName(d.top[0].path)}`] : [])]
    : ["没写新文件"]),
  `日志 ${formatSize(d.log)}`,
  ...(d.overlap > 0 && d.files > 0 ? ["含同时段任务"] : []),
].join(" · ");
export function jobDiskDetail(d: JobDisk): string {
  const groups = d.top.map((t) => `${jobDiskGroupName(t.path)} ${formatSize(t.size)}`).join("、");
  const notes = [...(d.partial ? ["文件太多只数了一部分"] : []), ...(d.overlap > 0 ? [`同时段另有 ${d.overlap} 个任务运行，可能包含它们写入的内容`] : [])];
  const head = d.files > 0 ? `运行期间新写或改过 ${d.files} 个文件，共 ${formatSize(d.written)}${groups ? `：${groups}` : ""}` : "运行期间没有新写文件";
  return `${head}；日志 ${formatSize(d.log)}${notes.length ? `（${notes.join("；")}）` : ""}`;
}
export const jobDiskSemantics = (d: JobDisk) =>
  d.files > 0 ? `写入 ${formatSize(d.written)}，${d.files} 个文件，日志 ${formatSize(d.log)}` : `没写新文件，日志 ${formatSize(d.log)}`;

export type JobTone = "running" | "ok" | "problem" | "quiet";
export const jobTone = (s: JobState, autoStopped = false): JobTone =>
  autoStopped ? "problem" : s === "done" ? "ok" : s === "failed" || s === "timed_out" || s === "lost" ? "problem" : s === "cancelled" ? "quiet" : "running";

/** v2.25 取消的状态词：你停的 / 助手停的 / 不知道是谁（老任务）。App models/job.dart 同一套。 */
export const jobStopperLabel = (by?: string | null) => (by === "user" ? "已由你停止" : by === "agent" ? "已由助手停止" : "已取消");

export function jobStateLabel(j: Pick<JobInfo, "state" | "exit_code" | "stop_reason" | "keep_alive" | "restart_at"> & { stopped_by?: string | null }): string {
  switch (j.state) {
    case "running": return j.keep_alive ? (j.restart_at ? "重启中" : "常驻 · 运行中") : "运行中";
    case "done": return "已完成";
    case "failed": return j.exit_code == null ? "失败" : `失败 · 退出码 ${j.exit_code}`;
    case "timed_out": return "超时被终止";
    case "cancelled": return jobAutoStopped(j) ? "已自动停止" : jobStopperLabel(j.stopped_by);
    case "lost": return "中断了";
  }
}

/** 前台命令转进后台的任务，卡片底部和“电脑”一节都标这一句（App models/job.dart 同一句）。 */
export const JOB_PROMOTED_LABEL = "从前台转入";

/** v2.20 借了账户的任务标一句“用 GitHub 账户”（App models/job.dart 同一句）；没借 → null。坏形状当没借。 */
export const jobCredentials = (j: { credentials?: unknown }): string[] =>
  Array.isArray(j.credentials) ? j.credentials.filter((x): x is string => typeof x === "string") : [];
export const jobCredentialsLabel = (names: string[]) => (names.length ? `用 ${names.join("、")} 账户` : null);
const credBits = (j: JobInfo) => { const c = jobCredentialsLabel(jobCredentials(j)); return c ? [c] : []; };

/** 卡片底部那行：状态词 · 从前台转入 · 已自动重启 N 次（常驻）· 助手在看结果（等它接着说）。 */
export const jobFootLabel = (j: JobInfo) => [jobStateLabel(j),
  ...(j.promoted ? [JOB_PROMOTED_LABEL] : []),
  ...credBits(j),
  ...(j.keep_alive && j.restarts ? [`已自动重启 ${j.restarts} 次`] : []),
  ...(!jobRunning(j) && jobMemoryPeak(j) ? [`内存峰值 ${formatSize(jobMemoryPeak(j)!)}`] : []),
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
export const jobMemoryLabel = (u: JobUsage, max: number | null = null) =>
  [`内存 ${formatSize(u.memory)}${max != null ? ` / ${formatSize(max)}` : ""}`, ...(u.processes > 1 ? [`${u.processes} 个进程`] : [])].join(" · ");
export const jobUsageLabel = (u: JobUsage) => `CPU ${jobCpuLabel(u.cpu)} · ${jobMemoryLabel(u)}`;
export const jobUsageSemantics = (u: JobUsage) =>
  `占用 CPU ${jobCpuLabel(u.cpu)}，内存 ${formatSize(u.memory)}${u.processes > 1 ? `，${u.processes} 个进程` : ""}`;

/** “电脑”一节运行中任务那行的副标题：常驻的先说清，再是用时、占用和命令。 */
export const jobRowSubtitle = (j: JobInfo) => {
  const u = jobUsage(j.usage);
  return [
    ...(j.keep_alive ? [j.restart_at ? "重启中" : "常驻"] : []),
    ...(j.keep_alive && j.restarts ? [`已重启 ${j.restarts} 次`] : []),
    ...(j.promoted ? [JOB_PROMOTED_LABEL] : []),
    ...credBits(j),
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
  `${j.keep_alive ? "常驻任务" : "后台任务"} ${j.title}${j.promoted ? `（${JOB_PROMOTED_LABEL}）` : ""}，${jobStateLabel(j)}${jobShowsReason(j) ? `：${j.stop_reason}` : ""}` +
  `${j.keep_alive && j.restarts ? `，已自动重启 ${j.restarts} 次` : ""}${credBits(j).map((c) => `，${c}`).join("")}，用时 ${jobDuration(elapsed)}` +
  `${jobRunning(j) && jobUsage(j.usage) ? `，${jobUsageSemantics(jobUsage(j.usage)!)}` : ""}` +
  `${jobRunning(j) && jobMemoryMax(j) ? `，内存上限 ${formatSize(jobMemoryMax(j)!)}` : ""}` +
  `${jobBoxTight(j) ? `，${jobBoxLabel(jobBox(j.box)!)}` : ""}` +
  `${jobDiskShown(jobDisk(j.disk)) ? `，${jobDiskSemantics(jobDisk(j.disk)!)}` : ""}` +
  `${j.changes && j.changes.files?.length && !jobRunning(j) ? `，${changesTitle(j.changes, "job")}` : ""}`;

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
    stop_reason: b.stop_reason ?? null, stopped_by: b.stopped_by ?? null, keep_alive: !!b.keep_alive, restarts: b.restarts ?? 0, restart_at: null,
    memory_max: b.memory_max ?? null, memory_peak: b.memory_peak ?? null, disk: b.disk ?? null, promoted: !!b.promoted, changes: b.changes ?? null,
    credentials: jobCredentials(b) };
}

// 后台任务卡的纯规则（App models/job.dart 同一套）：状态文案、语气、用时、日志尾巴、何时停止轮询。
import type { JobBlock, JobInfo, JobState } from "./types";

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

export function jobStateLabel(j: Pick<JobInfo, "state" | "exit_code" | "stop_reason">): string {
  switch (j.state) {
    case "running": return "运行中";
    case "done": return "已完成";
    case "failed": return j.exit_code == null ? "失败" : `失败 · 退出码 ${j.exit_code}`;
    case "timed_out": return "超时被终止";
    case "cancelled": return jobAutoStopped(j) ? "已自动停止" : "已取消";
    case "lost": return "中断了";
  }
}

const two = (n: number) => String(n).padStart(2, "0");
export function jobDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${two(s % 60)} 秒`;
  return `${Math.floor(s / 3600)} 小时 ${two(Math.floor((s % 3600) / 60))} 分`;
}

/** 读屏：一句话说清这张卡。 */
export const jobSemantics = (j: JobInfo, elapsed = j.elapsed) =>
  `后台任务 ${j.title}，${jobStateLabel(j)}${jobAutoStopped(j) ? `：${j.stop_reason}` : ""}，用时 ${jobDuration(elapsed)}`;

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
    stop_reason: b.stop_reason ?? null };
}

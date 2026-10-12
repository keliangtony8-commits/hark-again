// 用户自己跑的命令（输入框 !命令，后端 app/user_shell.py）：纯规则。App models/shell.dart 同一套。
import { JOB_LOG_LINES, jobDuration, jobTailLines, type JobTone } from "./jobs";
import type { ShellBlock } from "./types";

export const SHELL_PREFIXES = ["!", "！"]; // 全角叹号也算（和后端 PREFIXES 一致）

/** 这段字会不会被当成命令：去掉首尾空白后以 ! / ！ 开头、后面还有东西。带附件的不算（调用方判断）。 */
export function shellCommandOf(text: string): string | null {
  const t = text.trim();
  if (!t || !SHELL_PREFIXES.includes(t[0])) return null;
  return t.slice(1).trim() || null;
}

export const shellTone = (state: ShellBlock["state"]): JobTone =>
  state === "running" ? "running" : state === "done" ? "ok" : state === "stopped" ? "quiet" : "problem";

export function shellStateLabel(b: Pick<ShellBlock, "state" | "exit_code">): string {
  switch (b.state) {
    case "running": return "运行中";
    case "done": return "已完成";
    case "failed": return b.exit_code == null ? "失败" : `失败 · 退出码 ${b.exit_code}`;
    case "timeout": return "超时被终止";
    case "stopped": return "已停止";
    case "refused": return "已拦下，没有执行";
    case "error": return "没拿到结果";
  }
}

/** 10 秒内带一位小数，再长按后台任务卡的写法；没有用时 = 空。 */
export function shellDuration(seconds?: number | null): string {
  if (seconds == null) return "";
  return seconds < 10 ? `${seconds.toFixed(1)} 秒` : jobDuration(seconds);
}

export const shellTail = (output: string, lines = JOB_LOG_LINES) => jobTailLines(output, lines);
export const shellHasMore = (output: string, lines = JOB_LOG_LINES) => output.replace(/\s+$/, "").split("\n").length > lines;

export function shellSemantics(b: ShellBlock): string {
  const d = shellDuration(b.seconds);
  return `你运行的命令 ${b.command}，${shellStateLabel(b)}${d ? `，用时 ${d}` : ""}${b.note ? `：${b.note}` : ""}`;
}

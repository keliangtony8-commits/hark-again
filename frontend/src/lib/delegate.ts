// 子助手卡的纯规则（v1.48）：和 App models/delegate.dart 同一套。
import type { DelegateBlock, DelegateState, DelegateTask } from "./types";

export const delegateEnded = (t: DelegateTask) => t.state !== "running";
export const delegateDone = (b: DelegateBlock) => b.tasks.filter((t) => t.state === "done").length;

/** 进行中 “1/3 完成”；全结束且都完成 “3 个都完成了”；全结束有没成的 “完成 2/3”。 */
export function delegateProgress(b: DelegateBlock): string {
  const n = b.tasks.length, d = delegateDone(b);
  if (b.tasks.every(delegateEnded)) return d === n ? `${n} 个都完成了` : `完成 ${d}/${n}`;
  return `${d}/${n} 完成`;
}

export const delegateStateLabel = (s: DelegateState) =>
  ({ running: "在做", done: "完成", partial: "交了半截", failed: "没成", stopped: "被停下" })[s] ?? "在做";

function duration(seconds: number): string {
  if (seconds < 1) return "不到 1 秒";
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return seconds % 60 === 0 ? `${Math.floor(seconds / 60)} 分` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}

/** 子任务标题下的一行：在做 “第 3 步 · 正在搜索”；完成 “7 步 · 42 秒”；没成 / 半截 给原因。 */
export function delegateTaskLine(t: DelegateTask): string {
  const steps = t.steps ?? 0;
  const took = [...(steps > 0 ? [`${steps} 步`] : []), ...(t.seconds != null ? [duration(t.seconds)] : [])].join(" · ");
  switch (t.state) {
    case "running":
      if (t.now) return steps > 0 ? `第 ${steps} 步 · ${t.now}` : t.now;
      return steps > 0 ? `第 ${steps} 步 · 在想` : "刚开始";
    case "done":
      return took || "完成";
    case "partial":
    case "failed":
      return t.note || delegateStateLabel(t.state);
    default:
      return "这一轮被停下了";
  }
}

export const delegateCanOpen = (t: DelegateTask) => delegateEnded(t) && !!t.result?.trim();

export const delegateSemantics = (b: DelegateBlock) =>
  [`子助手，${delegateProgress(b)}`, ...b.tasks.map((t) => `${t.title}，${delegateStateLabel(t.state)}，${delegateTaskLine(t)}`)].join("；");

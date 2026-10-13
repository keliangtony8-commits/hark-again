// 子助手卡的纯规则（v1.48）：和 App models/delegate.dart 同一套。
import type { AgentBlock, Block, DelegateBlock, DelegateState, DelegateTask } from "./types";

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

/** 子任务标题下的一行：在做 “第 3 步 · 正在搜索”；完成 “7 步 · 42 秒”；没成 / 半截 给原因。续问那次前面加“第 2 轮 · ”。 */
export function delegateTaskLine(t: DelegateTask): string {
  const line = taskLine(t);
  return (t.round ?? 1) > 1 ? `第 ${t.round} 轮 · ${line}` : line;
}

function taskLine(t: DelegateTask): string {
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

export const delegateHasResult = (t: DelegateTask) => delegateEnded(t) && !!t.result?.trim();

/** 能接着问（v1.97，后端 agent/subagent_threads.py）：这一轮结束、带编号（老卡片没有）、结束了。 */
export const delegateCanFollow = (b: DelegateBlock, t: DelegateTask) => !b.live && delegateEnded(t) && !!t.id;

/** 能展开：有结论，或者能追问。 */
export const delegateCanOpen = (b: DelegateBlock, t: DelegateTask) => delegateHasResult(t) || delegateCanFollow(b, t);

export const delegateFollowTitle = (title: string) => `追问「${title}」`;

export const agentChipLabel = (a: AgentBlock) => (a.target ? `追问 · ${a.title || "子任务"}` : a.name || "子助手");

export const agentChipSemantics = (a: AgentBlock) =>
  a.target ? `追问子助手 ${a.title ?? ""}${a.gone ? "，它的上下文已经不在了" : ""}` : `交给${a.name || "子助手"}`;

/** 消息里的追问标签 → user.message 的 follow / follow_title（服务器以库里的标题为准）。 */
export function followField(blocks: Block[]): { follow?: string; follow_title?: string } {
  const a = blocks.find((b): b is AgentBlock => b.type === "agent" && !!(b as AgentBlock).target);
  return a ? { follow: a.target!, ...(a.title ? { follow_title: a.title } : {}) } : {};
}

export const delegateSemantics = (b: DelegateBlock) =>
  [`子助手，${delegateProgress(b)}`, ...b.tasks.map((t) => `${t.title}，${delegateStateLabel(t.state)}，${delegateTaskLine(t)}${delegateCanFollow(b, t) ? "，可以追问" : ""}`)].join("；");

// 计划清单卡的纯规则（v1.47）：和 App models/plan.dart 同一套。
import type { PlanBlock, PlanItem, PlanStatus } from "./types";

export const planDone = (b: PlanBlock) => b.items.filter((i) => i.status === "completed").length;
export const planRatio = (b: PlanBlock) => (b.items.length ? planDone(b) / b.items.length : 0);
export const planFinished = (b: PlanBlock) => b.items.length > 0 && planDone(b) === b.items.length;
export const planCurrent = (b: PlanBlock): PlanItem | undefined => b.items.find((i) => i.status === "in_progress");

/** “2/5”；全做完 “5 步都完成了”；这一轮停了还没做完 “停在 2/5”。 */
export function planProgress(b: PlanBlock): string {
  const n = b.items.length, d = planDone(b);
  if (planFinished(b)) return `${n} 步都完成了`;
  if (b.settled) return `停在 ${d}/${n}`;
  return `${d}/${n}`;
}

/** 全做完且这一轮结束：默认收起成一行。 */
export const planCollapsedByDefault = (b: PlanBlock) => !!b.settled && planFinished(b);

export const planStatusLabel = (s: PlanStatus) => ({ pending: "待做", in_progress: "进行中", completed: "完成" })[s] ?? "待做";

export function planSemantics(b: PlanBlock): string {
  return [`计划，${planProgress(b)}`, ...(b.explanation ? [`调整原因：${b.explanation}`] : []),
    ...b.items.map((i, n) => `第${n + 1}步 ${i.content}，${planStatusLabel(i.status)}`)].join("；");
}

// 活动时间线（v1.28）规则，与 App models/activity.dart 同款；服务器形状见 backend/app/activity.py。
import type { ActivityStep, FileChange, ServerEvent } from "./types";

type StatusEvent = Extract<ServerEvent, { type: "tool.status" }>;

/** WS tool.status → 一步：新服务器带完整 step；老服务器只有 label/state，退化成只有标题。 */
export function stepFromStatus(e: StatusEvent): ActivityStep {
  if (e.step && e.step.id) return e.step;
  const title = e.label.startsWith("正在") ? e.label.slice(2) : e.label;
  return { id: e.id, tool: e.name, title, detail: "", state: e.state };
}

export function mergeStep(steps: ActivityStep[], s: ActivityStep): ActivityStep[] {
  const i = steps.findIndex((x) => x.id === s.id);
  return i < 0 ? [...steps, s] : steps.map((x, j) => (j === i ? s : x));
}

export const stepFailed = (s: ActivityStep) => s.state === "error" || s.state === "denied" || s.state === "stopped";

export function stepDuration(ms: number): string {
  if (ms < 1000) return `${(ms / 1000).toFixed(1)} 秒`;
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
}

/** 第一步开始到最后一步结束；有一步没时间 → null。 */
export function activitySpanMs(steps: ActivityStep[]): number | null {
  if (!steps.length || steps.some((s) => !s.at)) return null;
  const starts = steps.map((s) => Date.parse(s.at!));
  if (starts.some(Number.isNaN)) return null;
  const first = Math.min(...starts);
  const end = Math.max(...steps.map((s, i) => starts[i] + (s.ms ?? 0)));
  return end - first;
}

export function activitySummary(steps: ActivityStep[], pending = false): string {
  if (pending) return `已用 ${steps.length} 步`;
  const span = activitySpanMs(steps);
  return span == null ? `用了 ${steps.length} 步` : `用了 ${steps.length} 步 · ${stepDuration(span)}`;
}

export const STEP_STATE_LABEL: Record<ActivityStep["state"], string> = {
  running: "进行中", done: "完成", error: "没成功", denied: "没执行", stopped: "被停止",
};

/** 读屏：“新建，增加 3 行” / “增加 2 行，删除 1 行”（与 App FileChange.semantics 同款）。 */
export function changeSemantics(c: FileChange): string {
  return [c.created ? "新建" : "", `增加 ${c.added} 行`, c.removed > 0 ? `删除 ${c.removed} 行` : ""].filter(Boolean).join("，");
}

export type DiffKind = "hunk" | "add" | "remove" | "context" | "note";

/** diff 文本拆成行并标类型（界面按类型上色）。 */
export function diffLines(diff: string): [DiffKind, string][] {
  return diff.split("\n").map((l): [DiffKind, string] => [
    l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "remove" : l.startsWith("…") ? "note" : "context", l]);
}

export function stepSemantics(s: ActivityStep): string {
  return [[s.title, s.detail].filter(Boolean).join(" "), STEP_STATE_LABEL[s.state], s.note, s.change ? changeSemantics(s.change) : "",
    s.ms != null && s.state !== "running" ? `用时 ${stepDuration(s.ms)}` : ""].filter(Boolean).join("，");
}

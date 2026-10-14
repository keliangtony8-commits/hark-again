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

/** “12 秒” / “1 分 5 秒”；不到 1 秒 → null 不写（用户 10-14 16:01：满屏 “0.0 秒” 像计时坏了）。 */
export function stepDuration(ms: number): string | null {
  if (ms < 1000) return null;
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
  if (pending) return `已做 ${steps.length} 步`;
  const span = activitySpanMs(steps);
  const d = span == null ? null : stepDuration(span);
  return d == null ? `做了 ${steps.length} 步` : `做了 ${steps.length} 步 · ${d}`;
}

/** 时间线自己展开：一轮结束时最后一步是出错的（没补救回来）。其余默认收成一行（与 App activityOpensItself 同款）。 */
export const activityOpensItself = (steps: ActivityStep[], pending = false) =>
  !pending && steps.length > 0 && steps[steps.length - 1].state === "error";

export const STEP_STATE_LABEL: Record<ActivityStep["state"], string> = {
  running: "进行中", done: "完成", error: "没成功", denied: "没执行", stopped: "被停止",
};

/** 读屏：“新建，增加 3 行” / “增加 2 行，删除 1 行”（与 App FileChange.semantics 同款）。 */
export function changeSemantics(c: FileChange): string {
  return [c.created ? "新建" : "", c.moved_from ? `从 ${c.moved_from} 改名` : "", c.mode ?? "", `增加 ${c.added} 行`,
    c.removed > 0 ? `删除 ${c.removed} 行` : ""].filter(Boolean).join("，");
}

/** 行里显示的路径：改名的写成 “旧 → 新”（v1.69 apply_patch）。 */
export function changeLabel(c: FileChange): string {
  return c.moved_from ? `${c.moved_from} → ${c.path}` : c.path;
}

/** 这一步改了的文件：changes 列表（apply_patch 一步几个，v1.69）优先，否则单个 change。坏项跳过。 */
export function stepFiles(s: ActivityStep): FileChange[] {
  const list = Array.isArray(s.changes) ? s.changes : s.change ? [s.change] : [];
  return list.filter((c): c is FileChange => !!c && typeof c === "object" && typeof c.path === "string");
}

/** 行尾 “+N −M”：一个文件就是它；几个文件合计（路径空、没有 diff）。 */
export function stepChange(s: ActivityStep): FileChange | null {
  const files = stepFiles(s);
  if (files.length <= 1) return files[0] ?? null;
  return { path: "", diff: "", added: files.reduce((n, f) => n + f.added, 0), removed: files.reduce((n, f) => n + f.removed, 0) };
}

/** 有东西可展开：一个文件看 diff，几个文件看逐个文件。 */
export function stepExpandable(s: ActivityStep): boolean {
  const files = stepFiles(s);
  return files.length > 1 || !!files[0]?.diff;
}

/** 时间线一步里逐个文件的状态字：这一步删掉的写“已删除”。 */
export function stepFileTag(c: FileChange): string | null {
  return c.deleted ? "已删除" : null;
}

export type DiffKind = "hunk" | "add" | "remove" | "context" | "note";

/** diff 文本拆成行并标类型（界面按类型上色）。 */
export function diffLines(diff: string): [DiffKind, string][] {
  return diff.split("\n").map((l): [DiffKind, string] => [
    l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "remove" : l.startsWith("…") ? "note" : "context", l]);
}

export function stepSemantics(s: ActivityStep): string {
  return [[s.title, s.detail].filter(Boolean).join(" "), STEP_STATE_LABEL[s.state], s.note, stepFilesSemantics(s),
    s.ms != null && s.state !== "running" && stepDuration(s.ms) ? `用时 ${stepDuration(s.ms)}` : ""].filter(Boolean).join("，");
}

function stepFilesSemantics(s: ActivityStep): string {
  const files = stepFiles(s);
  const total = stepChange(s);
  if (!total) return "";
  return files.length > 1 ? `改了 ${files.length} 个文件，${changeSemantics(total)}` : changeSemantics(total);
}

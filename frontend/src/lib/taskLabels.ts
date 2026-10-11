// 定时任务的状态文案：列表行和详情页共用；与 App features/me/task_labels.dart 同规则同措辞。
import { describeCron, nextRunToday } from "./cron";
import { formatWhen } from "./format";
import type { ScheduledTask } from "./types";

/** 计划本身：每天 08:00 / 工作日 09:00 / 一次 · 明天 08:00。 */
export function scheduleLabel(t: ScheduledTask, now = new Date()): string {
  return t.run_at ? `一次 · ${formatWhen(t.run_at, now)}` : describeCron(t.cron);
}

/** 已完成（一次性跑过）/ 已暂停 / 马上运行（过期补跑或一分钟内）/ 下次 明天 08:00；cron 无效时为空。
 * 一次性任务的“下次”就是计划时刻，scheduleLabel 已经写了，这里不再重复。 */
export function nextRunLabel(t: ScheduledTask, now = new Date()): string {
  if (t.done) return "已完成";
  if (!t.active) return "已暂停";
  if (!t.next_run_at) return "";
  if (new Date(t.next_run_at).getTime() - now.getTime() < 60_000) return "马上运行";
  if (t.run_at) return "";
  return `下次 ${formatWhen(t.next_run_at, now)}`;
}

/** 列表行的状态：排队 > 上次失败 > 下次运行。 */
export function taskStateLabel(t: ScheduledTask, now = new Date()): string {
  if (t.run_requested) return "即将运行…";
  if (t.last_status === "error") return "上次失败";
  return nextRunLabel(t, now);
}

/** Home“今天”里的钟点：重复任务按 cron 今天的时刻；一次性任务今天要跑且没跑过才算。 */
export function todayAt(t: ScheduledTask, now = new Date()): string | null {
  if (!t.run_at) return nextRunToday(t.cron, now);
  if (t.done) return null;
  const at = new Date(t.run_at);
  if (at.toDateString() !== now.toDateString()) return null;
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

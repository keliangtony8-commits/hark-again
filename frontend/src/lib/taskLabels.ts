// 定时任务的状态文案：列表行和详情页共用；与 App features/me/task_labels.dart 同规则同措辞。
import { describeCron, nextRunToday } from "./cron";
import { formatWhen } from "./format";
import type { ScheduledTask } from "./types";

/** 计划本身：每天 08:00 / 工作日 09:00 / 一次 · 明天 08:00。 */
export function scheduleLabel(t: ScheduledTask, now = new Date()): string {
  return t.run_at ? `一次 · ${formatWhen(t.run_at, now)}` : describeCron(t.cron);
}

/** 连续失败被自动暂停（手动停的不算）。 */
export const autoPaused = (t: ScheduledTask) => !t.active && t.paused_reason === "failures";

/** 已完成（一次性跑过）/ 连续失败已暂停 / 已暂停 / 马上运行（过期补跑或一分钟内）/ 下次 明天 08:00；cron 无效时为空。
 * 一次性任务的“下次”就是计划时刻，scheduleLabel 已经写了，这里不再重复。 */
export function nextRunLabel(t: ScheduledTask, now = new Date()): string {
  if (t.done) return "已完成";
  if (autoPaused(t)) return "连续失败，已暂停";
  if (!t.active) return "已暂停";
  if (!t.next_run_at) return "";
  if (new Date(t.next_run_at).getTime() - now.getTime() < 60_000) return "马上运行";
  if (t.run_at) return "";
  return `下次 ${formatWhen(t.next_run_at, now)}`;
}

/** 列表行的状态：排队 > 自动暂停 > 连续失败 N 次 / 上次失败 > 下次运行。 */
export function taskStateLabel(t: ScheduledTask, now = new Date()): string {
  const streak = t.fail_streak ?? 0;
  if (t.run_requested) return "即将运行…";
  if (autoPaused(t)) return `连续失败 ${streak} 次，已暂停`;
  if (t.last_status === "error") return streak > 1 ? `连续失败 ${streak} 次` : "上次失败";
  return nextRunLabel(t, now);
}

/** 详情页说明条：只有被自动暂停时才有，告诉用户怎么恢复。 */
export function autoPauseNote(t: ScheduledTask): string | null {
  return autoPaused(t)
    ? `连着失败了 ${t.fail_streak ?? 0} 次，我先把它停了，免得一直白跑。改好后打开开关恢复；也可以先“立即运行”试一次，成功了会自动恢复。`
    : null;
}

/** Home“今天”里的钟点：重复任务按 cron 今天的时刻；一次性任务今天要跑且没跑过才算。 */
export function todayAt(t: ScheduledTask, now = new Date()): string | null {
  if (!t.run_at) return nextRunToday(t.cron, now);
  if (t.done) return null;
  const at = new Date(t.run_at);
  if (at.toDateString() !== now.toDateString()) return null;
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

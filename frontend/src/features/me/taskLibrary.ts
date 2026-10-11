// 定时任务页的纯逻辑：分组、页头摘要、“下一个”、起步模板。与 App features/me/task_library.dart 同规则同措辞。
import { formatWhen } from "../../lib/format";
import { autoPaused } from "../../lib/taskLabels";
import type { ScheduledTask } from "../../lib/types";

const failed = (t: ScheduledTask) => autoPaused(t) || (t.last_status === "error" && !t.run_requested);
/** 停下了、不需要用户做什么：手动暂停或一次性已完成（自动暂停的算“需要留意”，不变淡）。 */
export const taskIdle = (t: ScheduledTask) => !autoPaused(t) && (!t.active || !!t.done);
const idle = taskIdle;
const isPanel = (t: ScheduledTask) => t.output === "panel";

/** 分组：需要留意（启用且上次失败，或连续失败被自动暂停）/ 在跑 / Home 面板 / 已停下（暂停或一次性已完成）。前三组按下次运行先后。 */
export function groupTasks(list: ScheduledTask[]) {
  const at = (t: ScheduledTask) => (t.next_run_at ? new Date(t.next_run_at).getTime() : Infinity);
  const pick = (f: (t: ScheduledTask) => boolean) => list.filter(f).sort((a, b) => at(a) - at(b)); // sort 稳定：同刻保持服务器顺序
  return {
    attention: pick((t) => !idle(t) && failed(t)),
    running: pick((t) => !idle(t) && !failed(t) && !isPanel(t)),
    panels: pick((t) => !idle(t) && !failed(t) && isPanel(t)),
    idle: list.filter(idle),
  };
}

/** “6 个任务 · 4 个在跑 · 1 个需要留意”；空列表是一句引导。 */
export function taskSummary(list: ScheduledTask[]) {
  if (!list.length) return "到点我自己去做的事";
  const g = groupTasks(list);
  const live = list.filter((t) => t.active && !t.done).length;
  return [`${list.length} 个任务`, live === list.length ? "全部在跑" : `${live} 个在跑`,
    ...(g.attention.length ? [`${g.attention.length} 个需要留意`] : [])].join(" · ");
}

/** 下一个要跑的：[名称, “明天 08:00” | “马上”]；没有 = null。 */
export function nextUp(list: ScheduledTask[], now = new Date()): [string, string] | null {
  let best: ScheduledTask | null = null;
  for (const t of list) {
    if (idle(t) || !t.next_run_at) continue;
    if (!best || new Date(t.next_run_at) < new Date(best.next_run_at!)) best = t;
  }
  if (!best) return null;
  const soon = new Date(best.next_run_at!).getTime() - now.getTime() < 60_000;
  return [best.name, soon ? "马上" : formatWhen(best.next_run_at, now)];
}

/** 起步模板：空列表里给几颗，点了带内容打开新建表单（没点保存前什么都不存）。 */
export const TASK_STARTERS: { name: string; prompt: string; cron: string }[] = [
  { name: "今日简报", prompt: "帮我准备今天：天气、日程、待办和需要注意的事，简短一点。", cron: "0 8 * * *" },
  { name: "每周复盘", prompt: "回顾这周的对话和完成的事，按“完成 / 没做完 / 下周重点”写一段复盘。", cron: "0 21 * * 0" },
  { name: "睡前背单词", prompt: "给我 10 个考研英语高频词，带例句，最后出 3 道小测。", cron: "0 22 * * *" },
];

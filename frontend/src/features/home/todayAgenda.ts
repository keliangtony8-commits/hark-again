// Home“今天”：今天排着的定时任务按钟点排成一条日程（对标 Hark 主页“今天接下来是什么 + 当天其余按小时”）。
// 纯函数；与 App features/home/today_agenda.dart 同规则同措辞（测试见 App test/today_agenda_test.dart）。
import { cronTodayAt } from "../../lib/cron";
import type { ScheduledTask } from "../../lib/types";
import { autoPaused } from "../../lib/taskLabels";

/** Home“今天”段末的宽胶囊：开新对话让助手准备今天（后端 day_overview + 技能 prep-my-day 出简报卡）。与 App 同字。 */
export const PREP_DAY_LABEL = "帮我准备今天";
export const PREP_DAY_PROMPT = "帮我准备今天";

export type AgendaState = "done" | "failed" | "running" | "next" | "later" | "paused";
export type AgendaItem = { task: ScheduledTask; at: Date; state: AgendaState; time: string; faded: boolean };

const two = (n: number) => String(n).padStart(2, "0");
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** 今天这条任务排在几点：一次性 = 计划时刻正好在今天；重复 = cron 今天的时刻。 */
export function todaySlot(t: ScheduledTask, now = new Date()): Date | null {
  if (t.run_at) { const at = new Date(t.run_at); return sameDay(at, now) ? at : null; }
  return cronTodayAt(t.cron, now);
}

/** 只放报告类；手动停的不放，自动暂停的放；一次性跑完了也留着显示结果。按钟点排。 */
export function todayAgenda(tasks: ScheduledTask[], now = new Date()): AgendaItem[] {
  const slots = tasks
    .filter((t) => t.output !== "panel" && (t.active || autoPaused(t) || !!t.done))
    .map((t) => ({ t, at: todaySlot(t, now) }))
    .filter((x): x is { t: ScheduledTask; at: Date } => !!x.at)
    .sort((a, b) => a.at.getTime() - b.at.getTime());
  let nextGiven = false;
  return slots.map(({ t, at }) => {
    const state = ((): AgendaState => {
      if (autoPaused(t)) return "paused";
      if (t.run_requested) return "running";
      const last = t.last_run_at ? new Date(t.last_run_at) : null;
      if (t.done || (last && last.getTime() >= at.getTime())) return t.last_status === "error" ? "failed" : "done";
      if (at.getTime() <= now.getTime()) return "running";
      if (nextGiven) return "later";
      nextGiven = true;
      return "next";
    })();
    return { task: t, at, state, time: `${two(at.getHours())}:${two(at.getMinutes())}`, faded: state === "done" }; // 失败不变淡：警示字要看得见
  });
}

/** HH:MM（钟点列、摘要、“现在”标记共用）。 */
export const clockOf = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/** “现在”标记插在第几行之前：第一件钟点晚于此刻的那行；全在前或全在后 = null（贴在头尾只是噪音）。同 App agendaNowAt。 */
export function agendaNowAt(items: AgendaItem[], now: Date = new Date()): number | null {
  const i = items.findIndex((x) => x.at.getTime() > now.getTime());
  return i <= 0 ? null : i;
}

export const agendaHint = (i: AgendaItem) => ({ next: "下一个", running: "进行中…", done: "已完成" } as Partial<Record<AgendaState, string>>)[i.state] ?? "";
export const agendaProblem = (i: AgendaItem) => (i.state === "failed" ? "失败" : i.state === "paused" ? "已暂停" : null);

function repeat(cron: string): string {
  const f = cron.trim().split(/\s+/);
  if (f.length < 5) return "重复";
  if (f[4] === "1-5") return "工作日";
  if (f[4] !== "*") return "每周";
  if (f[2] !== "*") return "每月";
  return "每天";
}

export const agendaDetail = (i: AgendaItem) =>
  i.state === "paused" ? `连续失败 ${i.task.fail_streak ?? 0} 次，今天不会跑` : i.task.run_at ? "一次性" : repeat(i.task.cron);

export function agendaSummary(items: AgendaItem[]): string {
  if (items.length === 0) return "今天没有排定的任务";
  const next = items.find((i) => i.state === "next");
  const left = items.filter((i) => i.state === "next" || i.state === "later" || i.state === "running").length;
  if (left === 0) return `今天的 ${items.length} 件都跑完了`;
  return next ? `还剩 ${left} 件 · 下一个 ${next.time}` : `还剩 ${left} 件`;
}

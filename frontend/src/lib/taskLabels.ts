// 定时任务的状态文案：列表行和详情页共用；与 App features/me/task_labels.dart 同规则同措辞。
import { describeCron } from "./cron";
import { formatWhen } from "./format";
import type { ScheduledTask, TaskRun } from "./types";

/** 计划本身：每天 08:00 / 工作日 09:00 / 一次 · 明天 08:00。 */
export function scheduleLabel(t: ScheduledTask, now = new Date()): string {
  if (isLog(t)) return "你说一句就记一笔";
  return t.run_at ? `一次 · ${formatWhen(t.run_at, now)}` : describeCron(t.cron);
}

/** 连续失败被自动暂停（手动停的不算）。 */
export const autoPaused = (t: ScheduledTask) => !t.active && t.paused_reason === "failures";
/** 任务自己运行时按指令结束了自己（服务端 task_brief.ENDED：停用不删除） */
export const ended = (t: ScheduledTask) => !t.active && t.paused_reason === "ended";

/** 已完成（一次性跑过）/ 连续失败已暂停 / 已结束 / 已暂停 / 马上运行（过期补跑或一分钟内）/ 下次 明天 08:00；cron 无效时为空。
 * 一次性任务的“下次”就是计划时刻，scheduleLabel 已经写了，这里不再重复。 */
export function nextRunLabel(t: ScheduledTask, now = new Date()): string {
  if (isLog(t)) return ""; // 零点翻篇是内部的事，不当“下次运行”给人看
  if (t.done) return "已完成";
  if (autoPaused(t)) return "连续失败，已暂停";
  if (ended(t)) return "已结束";
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

export const isScript = (t: ScheduledTask) => t.kind === "script";
/** v2.55 记录面板（服务端 app/panel_log.py）：聊天里说一句就记一笔，内容按记下的笔算，不调模型；只能改标题。= App isLog */
export const isLog = (t: ScheduledTask) => t.kind === "log";
/** 到点交给模型的任务（定时脚本、记录面板都不调模型）。= App usesModel */
export const usesModel = (t: ScheduledTask) => !isScript(t) && !isLog(t);

/** 定时脚本“什么时候告诉我”三档（顺序即选择器顺序；与 App notifyLabels、后端 script_tasks.NOTIFY_LABELS 同措辞）。 */
export const NOTIFY_LABELS = { failure: "失败时告诉我", always: "每次都告诉我", change: "输出变了告诉我" } as const;
export const NOTIFY_HINTS = {
  failure: "成功了不打扰；失败时结果进 Home 收件箱。",
  always: "每次运行后将输出放入主页收件箱。",
  change: "输出和上次不一样才告诉你，适合盯网页、价格、库存。",
} as const;

/** 详情页那行“去向”：面板 / 收件箱 / 脚本（在哪跑 · 何时告诉）。 */
export function taskOutputLabel(t: ScheduledTask): string {
  if (isLog(t)) return "记录面板 · 不调用模型";
  if (t.output === "panel") return "刷新 Home 上的面板";
  if (!isScript(t)) return "结果放进 Home 收件箱";
  return `${t.project_id ? "在项目工作区中运行" : "在我的文件中运行"} · ${NOTIFY_LABELS[t.notify ?? "failure"]}`;
}

/** 详情页说明条：只有被自动暂停时才有，告诉用户怎么恢复。 */
export function autoPauseNote(t: ScheduledTask): string | null {
  return autoPaused(t)
    ? `已连续失败 ${t.fail_streak ?? 0} 次，已自动暂停。修改后打开开关即可恢复；也可先“立即运行”测试，成功后自动恢复。`
    : null;
}

/** v2.13 能跳过下一次：重复任务、开着（一次性的取消或改时间就行）。与 App ScheduledTask.canSkip 同规则。 */
export const canSkip = (t: ScheduledTask) => !isLog(t) && !t.run_at && t.active && !!t.next_run_at;

/** 跳过后“下次”下面一行：跳过了 明天 08:00 那次。 */
export const skipLabel = (t: ScheduledTask): string | null => (t.skipped_at ? `跳过了 ${formatWhen(t.skipped_at)} 那次` : null);

/** 运行记录一行的状态字（失败优先于没打扰你）。 */
export const isSilent = (r: TaskRun) => r.status !== "error" && r.silent_reason != null;
export const isWalled = (r: TaskRun) => r.status === "error" && !!r.wall_label;
export const runStateLabel = (r: TaskRun) =>
  r.status === "running" ? "正在运行" : isWalled(r) ? "碰壁" : r.status === "error" ? "失败" : isSilent(r) ? "没打扰你" : "成功";

/** v2.15 碰壁条下面的小字（= App wallHint）。 */
export const wallHint = (t: ScheduledTask) => t.wall_retrying ? "已经在重新运行，成功后这条会自动收起。"
  : !t.wall_fixable ? "不用你管，下次会自动再试。"
  : t.output === "panel" ? "面板先显示上一次的内容。处理完成后将自动重新运行，也可以点“重试”。" : "处理完成后将自动重新运行，也可以点“重试”。";

/** v2.19 存登录 / 连连接器之后的提示：服务端给了“已重新运行”那句就接在后面（= App withRetried）。 */
export const withRetried = (head: string, note?: string | null) => note ? `${head}。${note}` : head;

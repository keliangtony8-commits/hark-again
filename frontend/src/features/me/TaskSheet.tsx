import { useState } from "react";
import type { ScheduledTask } from "../../lib/types";
import { Sheet } from "../../ui/kit";
import SchedulePicker from "./SchedulePicker";
import TaskModelPicker from "./TaskModelPicker";

/** 表单的值：计划两个字段都带（cron 与 run_at 二选一，另一个为空），切换模式时服务端清掉另一个。 */
/** model / reasoning：任务自己的模型和思考强度，null = 默认（TaskModelPicker）。 */
export type TaskDraft = Pick<ScheduledTask, "name" | "prompt" | "cron" | "active"> & { run_at: string | null; model: string | null; reasoning: string | null };
export const EMPTY_TASK: TaskDraft = { name: "", prompt: "", cron: "0 8 * * *", run_at: null, active: true, model: null, reasoning: null };

/** 从已有任务得到草稿（只取可改的字段，不把只读字段 PATCH 回去）。 */
export const draftOf = (t: ScheduledTask): TaskDraft => ({ name: t.name, prompt: t.prompt, cron: t.cron, run_at: t.run_at ?? null, active: t.active,
  model: t.model ?? null, reasoning: t.reasoning ?? null });

/** 只取改了的字段（编辑时 PATCH 用；空对象 = 没改，不发请求）。面板改名由服务端同步到 Home 卡片。 */
export const changesOf = (before: TaskDraft, after: TaskDraft): Partial<TaskDraft> =>
  Object.fromEntries(Object.entries(after).filter(([k, v]) => before[k as keyof TaskDraft] !== v)) as Partial<TaskDraft>;

/** 新建/编辑定时任务（含面板）的唯一表单：列表页“新建”、详情页“编辑”、主页面板菜单“编辑面板”共用（= app task_form.dart）。
 *  panel：字段叫“标题/每次刷新查什么”，计划只能重复。onSave 抛错时表单留着。 */
export default function TaskSheet({ initial, title, onSave, onClose, panel = false }: {
  initial: TaskDraft; title: string; onSave: (d: TaskDraft) => Promise<void>; onClose: () => void; panel?: boolean;
}) {
  const [d, setD] = useState<TaskDraft>(initial);
  const valid = !!d.name.trim() && !!d.prompt.trim() && (!!d.run_at || !!d.cron.trim());
  return (
    <Sheet title={title} onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!valid} onClick={async () => { await onSave(d); onClose(); }}>保存</button>
    </>}>
      <label className="form-field"><span>{panel ? "标题" : "名称"}</span>
        <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder="今日简报" /></label>
      <label className="form-field"><span>{panel ? "每次刷新查什么、怎么展示" : "要我做什么"}</span>
        <textarea value={d.prompt} onChange={(e) => setD({ ...d, prompt: e.target.value })} placeholder="帮我准备今天…" /></label>
      <SchedulePicker repeatOnly={panel} value={{ cron: d.cron, run_at: d.run_at }} onChange={(p) => setD({ ...d, ...p })} />
      <TaskModelPicker value={{ model: d.model, reasoning: d.reasoning }} onChange={(m) => setD({ ...d, ...m })} />
    </Sheet>
  );
}

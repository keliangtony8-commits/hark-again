import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { scheduleLabel, taskStateLabel } from "../../lib/taskLabels";
import type { ScheduledTask } from "../../lib/types";
import { IconChevron, IconClock, IconPlus } from "../../ui/icons";
import { Hint, Page, PageHeader, Skeleton, Toggle } from "../../ui/kit";
import { TaskIcon } from "./SchedulePicker";
import TaskSheet, { EMPTY_TASK, type TaskDraft } from "./TaskSheet";

/** 定时任务列表：开关、新建；点一行进详情（TaskDetailScreen：运行记录、立即运行、编辑、删除）。
 *  上次失败的任务图标挂红点、副标题写“上次失败”。与 App tasks_screen.dart 同规则。 */
export default function TasksScreen() {
  const tasks = useResource<ScheduledTask>("/api/tasks");
  const nav = useNavigate();
  const [creating, setCreating] = useState<TaskDraft | null>(null);

  const sub = (t: ScheduledTask) => [
    t.output === "panel" ? "Home 面板" : null,
    scheduleLabel(t),
    taskStateLabel(t) || null,
  ].filter(Boolean).join(" · ");

  return (
    <Page header={<PageHeader title="定时任务" back action={
      <button className="icon-btn" onClick={() => setCreating(EMPTY_TASK)} aria-label="添加"><IconPlus /></button>} />}>
      {tasks.loading ? <Skeleton /> : tasks.items.length === 0 ? (
        <Hint icon={<IconClock size={26} />} title="还没有定时任务" text="比如每天 8 点的今日简报，或每周一的学习复盘。"
          action={<button className="btn btn-primary" onClick={() => setCreating({ ...EMPTY_TASK, name: "今日简报", prompt: "帮我准备今天：日程、待办、需要注意的事。" })}>
            <IconPlus />添加“今日简报”</button>} />
      ) : (
        <div className="list">
          {tasks.items.map((t) => {
            const failed = t.last_status === "error";
            return (
              <div key={t.id} className="row">
                <button className="task-row" onClick={() => nav(`/me/tasks/${t.id}`)}>
                  <span className={`row-icon dot-badge ${failed ? "on" : ""}`}>
                    <TaskIcon task={t} />
                    {failed && <span className="sr-only">上次运行失败</span>}
                  </span>
                  <span className="row-body">
                    <span className="row-title">{t.name}</span>
                    <span className={`row-sub ${failed && !t.run_requested ? "is-danger" : ""}`}>{sub(t)}</span>
                  </span>
                  <IconChevron />
                </button>
                <Toggle on={t.active} label={`启用「${t.name}」`} onChange={(v) => tasks.update(t.id, { active: v })} />
              </div>
            );
          })}
        </div>
      )}
      {creating && <TaskSheet title="新建任务" initial={creating} onClose={() => setCreating(null)}
        onSave={async (d) => { await tasks.create(d); }} />}
    </Page>
  );
}

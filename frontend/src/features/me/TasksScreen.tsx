import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { scheduleLabel, taskStateLabel } from "../../lib/taskLabels";
import type { ScheduledTask } from "../../lib/types";
import { IconChevron, IconPlus } from "../../ui/icons";
import { Page, PageHeader, Section, Skeleton, Toggle, stagger } from "../../ui/kit";
import { TaskIcon } from "./SchedulePicker";
import TaskSheet, { EMPTY_TASK, type TaskDraft } from "./TaskSheet";
import { TASK_STARTERS, groupTasks, nextUp, taskSummary } from "./taskLibrary";

/** 定时任务列表（面板也是任务）。版式（v0.77，与 App tasks_screen.dart 同）：
 *  页头 = 摘要小标签 + “下一个：早间简报 · 明天 08:00”；分组 需要留意 / 在跑 / Home 面板 / 已停下（变淡）；
 *  行错峰入场；空列表给起步模板。点一行进详情（运行记录、立即运行、编辑、删除）。 */
export default function TasksScreen() {
  const tasks = useResource<ScheduledTask>("/api/tasks");
  const nav = useNavigate();
  const [creating, setCreating] = useState<TaskDraft | null>(null);
  const g = groupTasks(tasks.items);
  const summary = taskSummary(tasks.items);
  const next = nextUp(tasks.items);
  const line = next ? `下一个：${next[0]} · ${next[1]}` : "到点我会自己去做，做完把结果发给你；面板按计划刷新。";
  let n = 0; // 整页错峰序号

  const rows = (items: ScheduledTask[]) => (
    <div className="list">
      {items.map((t) => {
        const failed = t.last_status === "error";
        const sub = [scheduleLabel(t), taskStateLabel(t) || null].filter(Boolean).join(" · ");
        return (
          <div key={t.id} className={`row enter ${!t.active || t.done ? "row-off" : ""}`} style={stagger(++n)}>
            <button className="task-row" onClick={() => nav(`/me/tasks/${t.id}`)}>
              <span className={`row-icon dot-badge ${failed ? "on" : ""}`}>
                <TaskIcon task={t} />
                {failed && <span className="sr-only">上次运行失败</span>}
              </span>
              <span className="row-body">
                <span className="row-title">{t.name}</span>
                <span className={`row-sub ${failed && !t.run_requested ? "is-danger" : ""}`}>{sub}</span>
              </span>
              <IconChevron />
            </button>
            <Toggle on={t.active} label={`启用「${t.name}」`} onChange={(v) => tasks.update(t.id, { active: v })} />
          </div>
        );
      })}
    </div>
  );

  return (
    <Page header={<PageHeader title="定时任务" back action={
      <button className="icon-btn" onClick={() => setCreating(EMPTY_TASK)} aria-label="新定时任务"><IconPlus /></button>} />}>
      <div className="page-intro enter">
        <span key={tasks.loading ? "" : summary} className="page-hero-label enter">{tasks.loading ? "" : summary}</span>
        <p key={tasks.loading ? "" : line} className="desc enter">{tasks.loading ? "\u00a0" : line}</p>
      </div>
      {tasks.loading ? <Skeleton /> : (
        <>
          {!tasks.items.length && (
            <div className="list starters enter">
              <div className="row-title">还没有定时任务</div>
              <p className="row-sub">在这里建，或在聊天里说“每天早上 8 点给我今天的天气和日程”。也可以从一个开始改：</p>
              <div className="starter-list">
                {TASK_STARTERS.map((st) => (
                  <button key={st.name} className="btn btn-ghost" onClick={() => setCreating({ ...EMPTY_TASK, ...st })}><IconPlus size={16} />{st.name}</button>
                ))}
              </div>
            </div>
          )}
          {g.attention.length > 0 && <Section title={`需要留意 · ${g.attention.length}`}>{rows(g.attention)}</Section>}
          {g.running.length > 0 && <Section title={`在跑 · ${g.running.length}`}>{rows(g.running)}</Section>}
          {g.panels.length > 0 && <Section title={`Home 面板 · ${g.panels.length}`}>{rows(g.panels)}</Section>}
          {g.idle.length > 0 && <Section title={`已停下 · ${g.idle.length}`}>{rows(g.idle)}</Section>}
        </>
      )}
      {creating && <TaskSheet title="新建任务" initial={creating} onClose={() => setCreating(null)}
        onSave={async (d) => { await tasks.create(d); }} />}
    </Page>
  );
}

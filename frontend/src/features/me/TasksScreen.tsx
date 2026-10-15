import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { autoPaused, scheduleLabel, taskStateLabel } from "../../lib/taskLabels";
import type { ScheduledTask } from "../../lib/types";
import { IconChevron, IconPlus, IconTerminal } from "../../ui/icons";
import { ListGroup, Page, PageHeader, PageIntro, Section, Skeleton, StarterCard, Toggle, stagger } from "../../ui/kit";
import { TaskIcon } from "./SchedulePicker";
import TaskSheet, { EMPTY_SCRIPT, EMPTY_TASK, type TaskDraft } from "./TaskSheet";
import { TASK_STARTERS, groupTasks, nextUp, taskIdle, taskSummary } from "./taskLibrary";

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
    <ListGroup>
      {items.map((t) => {
        const failed = t.last_status === "error";
        // 失败 / 自动暂停 = 这一行的问题：问题那几个字放前面染警示色（.row-problem），计划原色（App RowTile.problem 同义，v1.06）
        const problem = autoPaused(t) || (failed && !t.run_requested);
        const sub = [scheduleLabel(t), taskStateLabel(t) || null].filter(Boolean).join(" · ");
        return (
          <div key={t.id} className={`row enter ${taskIdle(t) ? "row-off" : ""}`} style={stagger(++n)}>
            <button className="task-row" onClick={() => nav(`/me/tasks/${t.id}`)}>
              <span className={`row-icon dot-badge ${failed ? "on" : ""}`}>
                <TaskIcon task={t} />
                {failed && <span className="sr-only">上次运行失败</span>}
              </span>
              <span className="row-body">
                <span className="row-title">{t.name}</span>
                {problem
                  ? <span className="row-sub"><span className="row-problem">{taskStateLabel(t)}</span> · {scheduleLabel(t)}</span>
                  : <span className="row-sub">{sub}</span>}
              </span>
              <IconChevron />
            </button>
            <Toggle on={t.active} label={`启用「${t.name}」`} onChange={(v) => tasks.update(t.id, { active: v })} />
          </div>
        );
      })}
    </ListGroup>
  );

  return (
    <Page header={<PageHeader title="定时任务" back action={<>
      {/* 定时脚本（到点直接跑命令、不调模型）单独一个入口，同 App */}
      <button className="icon-btn" onClick={() => setCreating(EMPTY_SCRIPT)} aria-label="新定时脚本"><IconTerminal /></button>
      <button className="icon-btn" onClick={() => setCreating(EMPTY_TASK)} aria-label="新定时任务"><IconPlus /></button>
    </>} />}>
      <PageIntro loading={tasks.loading} summary={summary} line={line} />
      {tasks.loading ? <Skeleton /> : (
        <>
          {!tasks.items.length && (
            <StarterCard title="还没有定时任务" text="在这里建，或在聊天里说“每天早上 8 点给我今天的天气和日程”。也可以从一个开始改：">
              {TASK_STARTERS.map((st) => (
                <button key={st.name} className="btn btn-ghost" onClick={() => setCreating({ ...EMPTY_TASK, ...st })}><IconPlus size={16} />{st.name}</button>
              ))}
            </StarterCard>
          )}
          {g.attention.length > 0 && <Section title={`需要留意 · ${g.attention.length}`}>{rows(g.attention)}</Section>}
          {g.running.length > 0 && <Section title={`运行中 · ${g.running.length}`}>{rows(g.running)}</Section>}
          {g.panels.length > 0 && <Section title={`Home 面板 · ${g.panels.length}`}>{rows(g.panels)}</Section>}
          {g.idle.length > 0 && <Section title={`已停用 · ${g.idle.length}`}>{rows(g.idle)}</Section>}
        </>
      )}
      {creating && <TaskSheet title={creating.kind === "script" ? "新定时脚本" : "新建任务"} initial={creating} onClose={() => setCreating(null)}
        onSave={async (d) => { await tasks.create(d); }} />}
    </Page>
  );
}

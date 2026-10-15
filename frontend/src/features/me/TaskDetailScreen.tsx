import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { useTaskRuns } from "../../hooks/useTaskRuns";
import { http } from "../../lib/api";
import { formatDuration, formatWhen } from "../../lib/format";
import WallNotice from "./WallNotice";
import { autoPauseNote, canSkip, isScript, isSilent, usesModel, isWalled, nextRunLabel, runStateLabel, scheduleLabel, skipLabel, taskOutputLabel } from "../../lib/taskLabels";
import TaskMemory from "./TaskMemory";
import { JobLog } from "../../blocks/JobBlock";
import type { JobInfo } from "../../lib/types";
import { TaskIcon } from "./SchedulePicker";
import type { ScheduledTask, TaskRun } from "../../lib/types";
import { IconCheck, IconChevron, IconClock, IconClose, IconLock, IconSnooze, IconEdit, IconHistory, IconPause, IconPlay, IconTrash } from "../../ui/icons";
import { Hint, ListGroup, Page, PageHeader, Section, Skeleton, Toggle } from "../../ui/kit";
import TaskSheet, { changesOf, draftOf } from "./TaskSheet";
import { taskModelLabel } from "./TaskModelPicker";
import { useModelCatalog } from "../../hooks/useModelCatalog";
import { confirmDialog } from "../../ui/dialog";

/** 定时任务详情（/me/tasks/:id）：任务本身（时间、去向 + 非默认的模型 / 思考档、提示词、开关、立即运行、编辑、删除）+ 最近运行记录。
 *  有运行在排队或进行时每 4 秒刷新，结束就停（useTaskRuns）。报告那次可点开对话（/chat + state.open）。
 *  v2.15：头卡里碰壁条（WallNotice：去处理 / 重试），碰壁那次运行锁图标 + “碰壁”。
 *  v2.13：“跳过下一次 / 撤销跳过”（POST / DELETE skip）、“助手记下的”（TaskMemory）、没打扰你的运行（silent_reason）。
 *  与 App task_detail.dart 同版面同文案；Home 的“任务失败”提醒卡（target=tasks）直达这里。 */
export default function TaskDetailScreen() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const tasks = useResource<ScheduledTask>("/api/tasks");
  const task = tasks.items.find((t) => t.id === id);
  const refreshTasks = tasks.reload;
  const onTick = useCallback(() => { refreshTasks(); }, [refreshTasks]);
  const { runs, error, reload, busy } = useTaskRuns(id, !!task?.run_requested, onTick);
  const [editing, setEditing] = useState(false);
  const [log, setLog] = useState<JobInfo | null>(null);
  const cat = useModelCatalog();

  if (!task) {
    return (
      <Page header={<PageHeader title="定时任务" back />}>
        {tasks.loading ? <Skeleton /> : <Hint icon={<IconClock size={26} />} title="该任务已删除" text="可能已在别的设备上删除。" />}
      </Page>
    );
  }

  const runNow = async () => { await http.post(`/api/tasks/${task.id}/run`, {}); await Promise.all([refreshTasks(), reload()]); };
  const remove = async () => {
    if (!(await confirmDialog({ title: `删除「${task.name}」？`, text: "运行记录和它在 Home 上的卡片会一起删除。" }))) return;
    await tasks.remove(task.id);
    nav("/me/tasks");
  };
  const toggleSkip = async () => {
    await (task.skipped_at ? http.del(`/api/tasks/${task.id}/skip`) : http.post(`/api/tasks/${task.id}/skip`, {}));
    await refreshTasks();
  };
  const queued = task.run_requested && !(runs ?? []).some((r) => r.status === "running");

  return (
    <Page header={<PageHeader title={task.name} back action={<>
      <button className="icon-btn" aria-label="编辑任务" onClick={() => setEditing(true)}><IconEdit /></button>
      <button className="icon-btn" aria-label="删除任务" onClick={remove}><IconTrash /></button>
    </>} />}>
      <div className="task-head">
        <div className="task-head-top">
          <span className="row-icon"><TaskIcon task={task} /></span>
          <div className="row-body">
            <div className="row-title">{scheduleLabel(task)}</div>
            <div className="row-sub">{[taskOutputLabel(task), usesModel(task) ? taskModelLabel(task, cat) : null].filter(Boolean).join(" · ")}</div>
            {nextRunLabel(task) && <div className="row-sub task-next" key={nextRunLabel(task)}>{nextRunLabel(task)}</div>}
            {skipLabel(task) && <div className="row-sub task-skip" key={skipLabel(task)}>{skipLabel(task)}</div>}
          </div>
          <Toggle on={task.active} label={`启用「${task.name}」`} onChange={(v) => tasks.update(task.id, { active: v })} />
        </div>
        {autoPauseNote(task) && (
          <div className="task-pause-note" role="status"><IconPause /><span>{autoPauseNote(task)}</span></div>
        )}
        <WallNotice task={task} onRetry={runNow} busy={busy} />
        <p className={`task-prompt ${isScript(task) ? "mono" : ""}`}>{task.prompt}</p>
        <div className="task-head-actions">
          {(canSkip(task) || task.skipped_at) && (
            <button className="btn btn-ghost btn-sm" onClick={toggleSkip}>{task.skipped_at ? "撤销跳过" : "跳过下一次"}</button>
          )}
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={runNow}><IconPlay />{busy ? "运行中…" : "立即运行"}</button>
        </div>
      </div>

      <TaskMemory task={task} onClear={async (field) => { await tasks.update(task.id, { [field]: "" }); }} />

      <Section title="运行记录">
        {error ? (
          <Hint icon={<IconHistory size={26} />} title="运行记录加载失败" text={error}
            action={<button className="btn btn-soft" onClick={reload}>重试</button>} />
        ) : runs === null ? <Skeleton /> : runs.length === 0 && !task.run_requested ? (
          <Hint icon={<IconHistory size={26} />} title="还没运行过" text="到点会自动运行，也可以点上面的“立即运行”试一次。" />
        ) : (
          <ListGroup className="task-runs">
            {queued && (
              <div className="row run-row" aria-label="排队中，马上开始">
                <span className="run-status"><span className="run-pulse muted" /></span>
                <div className="row-body"><div className="row-title">排队中</div><div className="row-sub">马上开始</div></div>
              </div>
            )}
            {runs.map((r, i) => <RunRow key={r.id} run={r} index={i} onOpen={(cid) => nav("/chat", { state: { open: cid } })}
              onLog={(jid) => http.get<JobInfo>(`/api/jobs/${jid}`).then(setLog).catch(() => {})} />)}
          </ListGroup>
        )}
      </Section>

      {log && <JobLog job={log} onClose={() => setLog(null)} />}
      {editing && <TaskSheet title={task.output === "panel" ? "编辑面板" : isScript(task) ? "编辑脚本" : "编辑任务"} panel={task.output === "panel"}
        initial={draftOf(task)} onClose={() => setEditing(false)}
        onSave={async (d) => { const c = changesOf(draftOf(task), d); if (Object.keys(c).length) await tasks.update(task.id, c); }} />}
    </Page>
  );
}

/** 一次运行：有对话的点开对话；定时脚本没开对话的（没告诉你那次）点开它的后台任务日志。 */
function RunRow({ run: r, index, onOpen, onLog }: { run: TaskRun; index: number; onOpen: (conversationId: string) => void; onLog: (jobId: string) => void }) {
  const running = r.status === "running", failed = r.status === "error";
  const label = runStateLabel(r), silent = isSilent(r), walled = isWalled(r);
  const when = formatWhen(r.started_at);
  const sub = [r.trigger === "manual" ? "手动" : "定时", silent || walled ? label : null, running ? "进行中" : r.duration_ms === null ? null : `用时 ${formatDuration(r.duration_ms)}`]
    .filter(Boolean).join(" · ");
  const body = <>
    <span className={`run-status ${r.status}${walled ? " walled" : ""}`} aria-hidden>{running ? <span className="run-pulse" /> : walled ? <IconLock size={14} /> : failed ? <IconClose size={14} /> : silent ? <IconSnooze size={14} /> : <IconCheck size={14} />}</span>
    <span className="row-body">
      <span className="row-title">{when}</span>
      <span className="row-sub">{sub}</span>
      {failed && r.error && <span className="run-error">{r.error}</span>}
      {silent && <span className="run-quiet">{r.silent_reason}</span>}
    </span>
    {(r.conversation_id || (r.job_id && !running)) && <IconChevron />}
  </>;
  const aria = `${label}，${when}，${sub}${failed && r.error ? `，原因：${r.error}` : ""}${silent ? `，${r.silent_reason}` : ""}`;
  const style = { animationDelay: `calc(var(--stagger) * ${Math.min(index, 10)})` };
  if (!r.conversation_id && r.job_id && !running)
    return <button className="row run-row" style={style} aria-label={`${aria}，看日志`} onClick={() => onLog(r.job_id!)}>{body}</button>;
  return r.conversation_id
    ? <button className="row run-row" style={style} aria-label={`${aria}，打开报告`} onClick={() => onOpen(r.conversation_id!)}>{body}</button>
    : <div className="row run-row" style={style} aria-label={aria} role="group">{body}</div>;
}

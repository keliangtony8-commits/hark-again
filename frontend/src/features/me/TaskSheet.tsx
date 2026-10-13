import { useState } from "react";
import type { ScheduledTask } from "../../lib/types";
import { Sheet } from "../../ui/kit";
import SchedulePicker from "./SchedulePicker";
import TaskModelPicker from "./TaskModelPicker";
import { NOTIFY_HINTS, NOTIFY_LABELS } from "../../lib/taskLabels";

type Notify = keyof typeof NOTIFY_LABELS;

/** 表单的值：计划两个字段都带（cron 与 run_at 二选一，另一个为空），切换模式时服务端清掉另一个。 */
/** model / reasoning：任务自己的模型和思考强度，null = 默认（TaskModelPicker）。 */
/** kind / notify：定时脚本（kind 建好不改，changesOf 自然不会带它；notify 改了才发）。 */
export type TaskDraft = Pick<ScheduledTask, "name" | "prompt" | "cron" | "active"> & { run_at: string | null; model: string | null; reasoning: string | null;
  kind: "agent" | "script" | "log"; notify: Notify };
export const EMPTY_TASK: TaskDraft = { name: "", prompt: "", cron: "0 8 * * *", run_at: null, active: true, model: null, reasoning: null,
  kind: "agent", notify: "failure" };
export const EMPTY_SCRIPT: TaskDraft = { ...EMPTY_TASK, cron: "0 3 * * *", kind: "script" };

/** 从已有任务得到草稿（只取可改的字段，不把只读字段 PATCH 回去）。 */
export const draftOf = (t: ScheduledTask): TaskDraft => ({ name: t.name, prompt: t.prompt, cron: t.cron, run_at: t.run_at ?? null, active: t.active,
  model: t.model ?? null, reasoning: t.reasoning ?? null, kind: t.kind ?? "agent", notify: t.notify ?? "failure" });

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
  const script = d.kind === "script"; // 定时脚本：命令 + 什么时候告诉我，没有模型选择（不调模型）
  const log = d.kind === "log"; // v2.55 记录面板：只能改标题（内容按记下的每一笔算）
  return (
    <Sheet title={title} onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!valid} onClick={async () => { await onSave(d); onClose(); }}>保存</button>
    </>}>
      <label className="form-field"><span>{panel ? "标题" : "名称"}</span>
        <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder="今日简报" /></label>
      {log && <p className="form-note">在聊天里说一句就记一笔（“今天跑了 5 公里”），面板自动算今天、近 7 天和连续天数。</p>}
      {!log && <>
      {script && <p className="form-note">到点直接在工作区跑这条命令，不调用模型、不花 token。</p>}
      <label className="form-field"><span>{panel ? "每次刷新查什么、怎么展示" : script ? "到点运行的命令" : "要我做什么"}</span>
        <textarea className={script ? "mono" : undefined} value={d.prompt} onChange={(e) => setD({ ...d, prompt: e.target.value })}
          placeholder={script ? "python3 scripts/fetch.py" : "帮我准备今天…"} spellCheck={!script} /></label>
      <SchedulePicker repeatOnly={panel} value={{ cron: d.cron, run_at: d.run_at }} onChange={(p) => setD({ ...d, ...p })} />
      {script ? (
        <div className="form-field"><span>什么时候告诉我</span>
          <div className="seg">
            {(Object.keys(NOTIFY_LABELS) as Notify[]).map((k) => (
              <button key={k} className={`chip ${d.notify === k ? "on" : ""}`} aria-pressed={d.notify === k}
                onClick={() => setD({ ...d, notify: k })}>{NOTIFY_LABELS[k]}</button>
            ))}
          </div>
          <small key={d.notify} className="fade-swap">{NOTIFY_HINTS[d.notify]}</small>
        </div>
      ) : <TaskModelPicker value={{ model: d.model, reasoning: d.reasoning }} onChange={(m) => setD({ ...d, ...m })} />}
      </>}
    </Sheet>
  );
}

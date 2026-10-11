// 选“什么时候跑”：重复（cron 常用项 + 手写）或一次（快捷时刻 + 自选日期时间）。新建/编辑任务表单共用。
// 与 App features/me/schedule_picker.dart 同结构同规则：cron 与 run_at 二选一（docs/protocol.md 定时任务）。
import { useMemo, useState } from "react";
import { CRON_PRESETS, describeCron } from "../../lib/cron";
import { onceShortcuts } from "../../lib/timeShortcuts";
import { formatWhen } from "../../lib/format";
import type { ScheduledTask } from "../../lib/types";
import { IconAlarm, IconClock, IconLayout } from "../../ui/icons";
import { Segmented } from "../../ui/kit";

/** 一个计划：run_at 非空 = 一次性（cron 为空串），否则按 cron 重复。发给服务端时两个字段都带。 */
export type Plan = { cron: string; run_at: string | null };

/** 行首/详情图标：面板 / 一次性（闹钟）/ 重复（时钟）。 */
export function TaskIcon({ task }: { task: ScheduledTask }) {
  return task.output === "panel" ? <IconLayout /> : task.run_at ? <IconAlarm /> : <IconClock />;
}

export { onceShortcuts };

const two = (n: number) => String(n).padStart(2, "0");
/** Date → <input type="datetime-local"> 的本地值 */
const localValue = (d: Date) => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`;

/** repeatOnly：面板只能按 cron 重复，不给“重复/一次”切换。 */
export default function SchedulePicker({ value, onChange, repeatOnly = false }: { value: Plan; onChange: (p: Plan) => void; repeatOnly?: boolean }) {
  const now = useMemo(() => new Date(), []);
  const shortcuts = useMemo(() => onceShortcuts(now), [now]);
  const once = !!value.run_at;
  const isShortcut = (iso: string | null) => !!iso && shortcuts.some((s) => s.at.getTime() === new Date(iso).getTime());
  const [custom, setCustom] = useState(once && !isShortcut(value.run_at));
  const [lastCron, setLastCron] = useState(value.cron || CRON_PRESETS[0].cron);

  const setMode = (m: "repeat" | "once") => {
    if ((m === "once") === once) return;
    if (m === "repeat") return onChange({ cron: lastCron, run_at: null });
    if (value.cron) setLastCron(value.cron);
    setCustom(false);
    onChange({ cron: "", run_at: shortcuts[0].at.toISOString() });
  };

  return (
    <div className="form-field"><span>什么时候</span>
      {!repeatOnly && <Segmented label="重复还是一次" value={once ? "once" : "repeat"} onChange={setMode}
        options={[{ value: "repeat", label: "重复" }, { value: "once", label: "一次" }]} />}
      {once ? (
        <div className="plan-body" key="once">
          <div className="seg">
            {shortcuts.map((s) => (
              <button key={s.label} className={`chip ${!custom && value.run_at === s.at.toISOString() ? "on" : ""}`}
                onClick={() => { setCustom(false); onChange({ cron: "", run_at: s.at.toISOString() }); }}>{s.label}</button>
            ))}
            <button className={`chip ${custom ? "on" : ""}`} onClick={() => setCustom(true)}>
              {custom ? formatWhen(value.run_at, now) : "选时间…"}</button>
          </div>
          {custom && (
            <input className="plan-body" type="datetime-local" aria-label="运行时间" min={localValue(now)}
              value={localValue(new Date(value.run_at!))}
              onChange={(e) => e.target.value && onChange({ cron: "", run_at: new Date(e.target.value).toISOString() })} />
          )}
        </div>
      ) : (
        <div className="plan-body" key="repeat">
          <div className="seg">
            {CRON_PRESETS.map((p) => (
              <button key={p.cron} className={`chip ${value.cron === p.cron ? "on" : ""}`} onClick={() => onChange({ cron: p.cron, run_at: null })}>{p.label}</button>
            ))}
          </div>
          <input value={value.cron} aria-label="cron 表达式" onChange={(e) => onChange({ cron: e.target.value, run_at: null })} />
          <small>cron 表达式（分 时 日 月 周）：{describeCron(value.cron)}</small>
        </div>
      )}
    </div>
  );
}

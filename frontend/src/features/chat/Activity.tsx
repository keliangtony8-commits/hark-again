// 活动时间线（v1.28，与 App features/chat/activity_view.dart 同一套）：回复上方一行“用了 4 步 · 12 秒 ›”（有没成的补“1 步没成”），
// 点开是竖向时间线：状态圆点 + 标题 + 等宽摘要 + 用时，没成的下面一行原因；步骤之间一根发丝线。规则在 lib/activity.ts。
import { useState } from "react";
import { activitySummary, stepDuration, stepFailed, stepSemantics, STEP_STATE_LABEL } from "../../lib/activity";
import type { ActivityStep } from "../../lib/types";
import { IconAlert, IconCheck, IconChevron, IconClose, IconHistory, IconStop } from "../../ui/icons";

function Mark({ s }: { s: ActivityStep }) {
  switch (s.state) {
    case "running": return <span className="step-pulse" />;
    case "done": return <IconCheck size={11} />;
    case "error": return <IconAlert size={11} />;
    case "denied": return <IconClose size={11} />;
    case "stopped": return <IconStop size={10} />;
  }
}

export default function ActivitySummary({ steps, pending }: { steps: ActivityStep[]; pending?: boolean }) {
  const [open, setOpen] = useState(false);
  const label = activitySummary(steps, pending);
  const bad = steps.filter(stepFailed).length;
  return (
    <div className="thought-sum activity">
      <button className={`thought-toggle ${open ? "open" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconHistory size={14} />{label}
        {bad > 0 && <span className="activity-bad">· {bad} 步没成</span>}
        <IconChevron size={14} />
      </button>
      {open && (
        <ol className="activity-steps">
          {steps.map((s, i) => (
            <li key={s.id} className={`step ${s.state} ${stepFailed(s) ? "bad" : ""}`} aria-label={stepSemantics(s)}
              style={{ animationDelay: `calc(${Math.min(i, 10)} * var(--stagger))` }}>
              <span className="step-dot" aria-hidden><Mark s={s} /></span>
              <div className="step-body" aria-hidden>
                <div className="step-line">
                  <span className="step-title">{s.title}</span>
                  {s.detail && <code className="step-detail" title={s.detail}>{s.detail}</code>}
                  {s.ms != null && s.state !== "running" && <span className="step-ms">{stepDuration(s.ms)}</span>}
                </div>
                {stepFailed(s) && <div className="step-note">{s.note || STEP_STATE_LABEL[s.state]}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

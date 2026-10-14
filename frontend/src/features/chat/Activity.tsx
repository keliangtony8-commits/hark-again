// 活动时间线（v1.28，与 App features/chat/activity_view.dart 同一套）：回复上方一行“做了 4 步 · 12 秒 ›”（有没成的补“1 步没成”），
// 点开是竖向时间线：状态圆点 + 标题 + 等宽摘要 + 用时，没成的下面一行原因；步骤之间一根发丝线。规则在 lib/activity.ts。
// v2.79：默认收起，只有一轮停在出错的一步时自己展开；不到 1 秒的步骤不写用时（满屏 “0.0 秒” 像坏了）。
// v1.34：改了文件的步骤行尾 “+3 −1”（绿/红），点这一行展开 diff（新增绿、删除红、段头淡）；像密钥的文件只有数字。
import { useEffect, useState } from "react";
import { activityOpensItself, activitySummary, stepChange, stepDuration, stepExpandable, stepFailed, stepFileTag, stepFiles, stepSemantics, STEP_STATE_LABEL } from "../../lib/activity";
import type { ActivityStep } from "../../lib/types";
import { Diff, DiffStat, FileDiffRow } from "../../ui/Diff";
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
  const [open, setOpen] = useState(() => activityOpensItself(steps, pending));
  const stuck = activityOpensItself(steps, pending);
  useEffect(() => { if (stuck) setOpen(true); }, [stuck]); // 刚结束、卡在出错的一步：自己展开（v2.79）
  const label = activitySummary(steps, pending);
  const bad = steps.filter(stepFailed).length;
  return (
    <div className="thought-sum activity">
      <button className={`thought-toggle ${open ? "open" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconHistory size={14} />{label}
        {bad > 0 && <span className="activity-bad">· {bad} 项失败</span>}
        <IconChevron size={14} />
      </button>
      {open && (
        <ol className="activity-steps">
          {steps.map((s, i) => <Step key={s.id} s={s} i={i} />)}
        </ol>
      )}
    </div>
  );
}

function Step({ s, i }: { s: ActivityStep; i: number }) {
  const [diff, setDiff] = useState(false);
  const [file, setFile] = useState<number | null>(null); // 几个文件时展开了哪一个
  const files = stepFiles(s);
  const c = stepChange(s);
  const canOpen = stepExpandable(s);
  const line = (
    <>
      <span className="step-title">{s.title}</span>
      {s.detail && <code className="step-detail" title={s.detail}>{s.detail}</code>}
      {c && (
        <span className="step-change">
          <DiffStat c={c} />
          {canOpen && <IconChevron size={12} />}
        </span>
      )}
      {s.ms != null && s.state !== "running" && stepDuration(s.ms) && <span className="step-ms">{stepDuration(s.ms)}</span>}
    </>
  );
  return (
    <li className={`step ${s.state} ${stepFailed(s) ? "bad" : ""}`} style={{ animationDelay: `calc(${Math.min(i, 10)} * var(--stagger))` }}>
      <span className="step-dot" aria-hidden><Mark s={s} /></span>
      <div className="step-body">
        {canOpen ? (
          <button className={`step-line step-toggle ${diff ? "open" : ""}`} aria-expanded={diff} aria-label={stepSemantics(s)} onClick={() => setDiff(!diff)}>{line}</button>
        ) : (
          <div className="step-line" aria-label={stepSemantics(s)} role="group">{line}</div>
        )}
        {stepFailed(s) && <div className="step-note" aria-hidden>{s.note || STEP_STATE_LABEL[s.state]}</div>}
        {diff && canOpen && (files.length === 1 ? <Diff c={files[0]} /> : (
          <ul className="file-diff-list">
            {files.map((f, k) => (
              <FileDiffRow key={f.path} c={f} i={k} tag={stepFileTag(f)} open={file === k} onToggle={() => setFile(file === k ? null : k)} />
            ))}
          </ul>
        ))}
      </div>
    </li>
  );
}

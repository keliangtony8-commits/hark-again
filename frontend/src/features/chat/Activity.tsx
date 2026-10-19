// 步骤胶囊（v3.5.5，照 Hark；= App features/chat/activity_view.dart StepCapsule，规则在 lib/activity.ts）：一条回复的过程只用回复下方一颗胶囊——
// 生成中只显示“当前正在做的那一步”（capsuleLabel），换步骤原地交叉淡入淡出（旧字往上淡出、新字从下淡入），前面一颗脉冲点；
// 生成完收成安静的“N 个步骤 · 12 秒”（失败补“· N 项失败”）。点开 = 竖向时间线：状态圆点 + 标题 + 等宽摘要 + 用时，没成的下面一行原因。
// 替换了 v1.28 回复上方那一行和回复卡里逐条的“正在…”小条。默认收起，只有一轮停在出错的一步时自己展开；不到 1 秒的步骤不写用时。
// v1.34：改了文件的步骤行尾 “+3 −1”（绿/红），点这一行展开 diff（新增绿、删除红、段头淡）；像密钥的文件只有数字。
import { useEffect, useState } from "react";
import { activityOpensItself, activitySummary, capsuleLabel, stepChange, stepDuration, stepExpandable, stepFailed, stepFileTag, stepFiles, stepSemantics, STEP_STATE_LABEL } from "../../lib/activity";
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

/** 换字时留住上一句一小会儿，好让它淡出（= App SwapSwitcher）。时长 = --dur。
 *  上一句在这一次渲染里就定下（React“记住上一次渲染的值”的写法）：新字第一帧就带着淡入，不会先实色闪一帧。 */
const SWAP_MS = 240;
function useSwap(key: string) {
  const [s, set] = useState<{ cur: string; prev: string | null }>({ cur: key, prev: null });
  if (s.cur !== key) set({ cur: key, prev: s.cur });
  useEffect(() => {
    if (s.prev == null) return;
    const t = window.setTimeout(() => set((x) => ({ ...x, prev: null })), SWAP_MS);
    return () => window.clearTimeout(t);
  }, [s.prev, s.cur]);
  return s.cur === key ? s.prev : null;
}

function CapText({ title, detail }: { title: string; detail: string }) {
  return <>{title}{detail && <span className="cap-detail"> · {detail}</span>}</>;
}

export default function StepCapsule({ steps, pending }: { steps: ActivityStep[]; pending?: boolean }) {
  const [open, setOpen] = useState(() => activityOpensItself(steps, pending));
  const stuck = activityOpensItself(steps, pending);
  useEffect(() => { if (stuck) setOpen(true); }, [stuck]); // 刚结束、卡在出错的一步：自己展开（v2.79）
  const [title, detail] = pending ? capsuleLabel(steps) : [activitySummary(steps), ""];
  const key = `${title}\u0000${detail}`;
  const prev = useSwap(key);
  const [pTitle, pDetail] = prev ? prev.split("\u0000") : ["", ""];
  const bad = pending ? 0 : steps.filter(stepFailed).length;
  const label = detail ? `${title} · ${detail}` : title;
  return (
    <div className={`step-cap-wrap ${pending ? "live" : ""}`}>
      <button className={`step-cap ${open ? "open" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}
        aria-label={`${label}${bad ? `，${bad} 项失败` : ""}，${open ? "收起步骤" : "展开步骤"}`}>
        {pending ? <span className="step-pulse" aria-hidden /> : <IconHistory size={13} />}
        <span className="cap-text" aria-hidden>
          {prev && <span key={prev} className="cap-line out"><CapText title={pTitle} detail={pDetail} /></span>}
          <span key={key} className={`cap-line ${prev ? "in" : ""}`}><CapText title={title} detail={detail} /></span>
        </span>
        {bad > 0 && <span className="activity-bad" aria-hidden>· {bad} 项失败</span>}
        <IconChevron size={13} />
      </button>
      {/* 生成中读屏播报当前这一步 */}
      {pending && <span className="sr-only" aria-live="polite">{label}</span>}
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

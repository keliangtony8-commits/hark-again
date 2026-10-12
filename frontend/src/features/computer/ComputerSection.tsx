import { useState } from "react";
import { Link } from "react-router-dom";
import { JobLog } from "../../blocks/JobBlock";
import { http } from "../../lib/api";
import { COMPUTER_MEMORY_TIGHT, type ComputerStatus, computerDetail, computerHint, computerMemoryRatio, computerOomNote, computerPath,
  computerRestartText, computerSemantics, computerStateLabel } from "../../lib/computer";
import { jobDuration } from "../../lib/jobs";
import type { JobInfo } from "../../lib/types";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconChevron, IconCloudOff, IconComputer } from "../../ui/icons";
import { Section } from "../../ui/kit";
import "./computer.css";
import { type ComputerCtl, useComputer } from "./useComputer";

/** “电脑”一节（v1.25，= App features/computer/computer_section.dart）：项目首屏和“我的电脑”页共用。
 *  状态行（运行/休眠/没开机/连不上 + 内存 · 文件 + 内存条）→ 正在跑的后台任务（点开完整日志、可取消）；标题右边“重启”只在运行中给。
 *  数据：给了 ctl（电脑页，几节共用一份）就用它，否则自己 useComputer(ws)（项目首屏）。加载中 / 失败 → 整节不画。
 *  v1.27：说明行带 CPU；内存打满被系统杀过 → 一行警示；to 给了（项目首屏）→ 状态行是链接，进这台电脑的详情页。 */
export default function ComputerSection({ ws, title = "电脑", enter, ctl, to }:
  { ws: string; title?: string; enter?: number; ctl?: ComputerCtl; to?: string }) {
  const own = useComputer(ws, false);
  const { s, set, load } = ctl ?? own;
  const [restarting, setRestarting] = useState(false);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [log, setLog] = useState<JobInfo | null>(null);

  if (!s) return null;
  const restart = async () => {
    if (!await confirmDialog({ title: "重启这台电脑？", text: computerRestartText(s), action: "重启" })) return;
    setRestarting(true);
    try { set(await http.post<ComputerStatus>(`${computerPath(ws)}/restart`, {})); }
    catch (e) { void noticeDialog("没能重启", e instanceof Error ? e.message : undefined); }
    setRestarting(false);
  };
  const cancel = async (j: JobInfo) => {
    setCancelling((c) => new Set(c).add(j.id));
    try { await http.post(`/api/jobs/${j.id}/cancel`, {}); await load(true); } catch { /* 下一次刷新会告诉真实状态 */ }
    setCancelling((c) => { const n = new Set(c); n.delete(j.id); return n; });
  };
  const ratio = computerMemoryRatio(s);
  const hint = computerHint(s);
  const down = s.sandbox.state === "unreachable";
  const oom = computerOomNote(s);
  const status = (
    <>
      <span className="row-icon">{down ? <IconCloudOff /> : <IconComputer />}</span>
      <div className="row-body" aria-hidden>
        <div key={s.sandbox.state} className="row-title computer-state">{computerStateLabel(s.sandbox.state)}</div>
        <div className="row-sub">{computerDetail(s)}</div>
        {ratio != null && (
          <div className={`meter computer-meter${ratio >= COMPUTER_MEMORY_TIGHT ? " meter-near" : ""}`}>
            <span style={{ transform: `scaleX(${ratio})` }} />
          </div>
        )}
        {oom && <div key={s.sandbox.oom_kills} className="computer-oom">{oom}</div>}
      </div>
      {hint && <span key={hint} className="row-hint computer-hint" aria-hidden>{hint}</span>}
      {to && <span className="row-trail" aria-hidden><IconChevron /></span>}
    </>
  );
  const label = [computerSemantics(s), oom].filter(Boolean).join("，");
  return (
    <Section title={title} enter={enter}
      action={s.sandbox.state === "running" && <button className="btn btn-ghost btn-sm" disabled={restarting} onClick={restart}>{restarting ? "正在重启" : "重启"}</button>}>
      <div className="list">
        {to
          ? <Link to={to} className={`row computer-status${down ? " is-down" : ""}`} aria-label={label}>{status}</Link>
          : <div className={`row computer-status${down ? " is-down" : ""}`} role="group" aria-label={label}>{status}</div>}
        {s.running_jobs.map((j) => (
          <div key={j.id} className="row computer-job">
            <button className="computer-job-open" onClick={() => setLog(j)} aria-label={`${j.title}，运行 ${jobDuration(j.elapsed)}，看日志`}>
              <span className="row-icon"><i className="job-dot" /></span>
              <div className="row-body"><div className="row-title">{j.title}</div>
                <div className="row-sub">运行 {jobDuration(j.elapsed)} · $ {j.command.split("\n")[0]}</div></div>
            </button>
            <button className="btn btn-ghost btn-sm" disabled={cancelling.has(j.id)} onClick={() => void cancel(j)}>
              {cancelling.has(j.id) ? "正在取消" : "取消"}</button>
          </div>
        ))}
      </div>
      {log && <JobLog job={log} onClose={() => setLog(null)} />}
    </Section>
  );
}

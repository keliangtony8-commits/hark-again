import { useState } from "react";
import { JobLog } from "../../blocks/JobBlock";
import { http } from "../../lib/api";
import { COMPUTER_MEMORY_TIGHT, type ComputerStatus, type ServiceInfo, computerDetail, computerHint, computerHintWarn, computerMemoryRatio,
  computerOomNote, computerPath, machineLine, computerRestartText, computerSemantics, computerStateLabel, serviceAction, serviceLine,
  serviceSemantics } from "../../lib/computer";
import { jobDuration, jobRowSubtitle } from "../../lib/jobs";
import type { JobInfo } from "../../lib/types";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconChevron, IconCloudOff, IconComputer, IconServer } from "../../ui/icons";
import { ListGroup, ListRow, Section } from "../../ui/kit";
import "./computer.css";
import { type ComputerCtl, useComputer } from "./useComputer";

/** “电脑”一节（v1.25，= App features/computer/computer_section.dart）：项目首屏和“我的电脑”页共用。
 *  状态行（运行/休眠/没开机/连不上 + 内存 · 文件 + 内存条）→ 正在运行的后台任务（点开完整日志、可取消）；标题右边“重启”只在运行中给。
 *  数据：给了 ctl（电脑页，几节共用一份）就用它，否则自己 useComputer(ws)（项目首屏）。加载中 / 失败 → 整节不画。
 *  v1.27：说明行带 CPU；内存打满被系统杀过 → 一行警示；to 给了（项目首屏）→ 状态行是链接，进这台电脑的详情页。
 *  v1.82：常驻服务排在任务前（服务器 app/services.py）：健康点（在跑闪点 / 等重启警示闪点 / 停了警示点）、副标题、
 *  行尾 重启 / 立即重启 / 重新启动（POST /api/jobs/{id}/restart，不用确认：不丢文件，日志接着写）；点行看完整日志。 */
export default function ComputerSection({ ws, title = "电脑", enter, ctl, to }:
  { ws: string; title?: string; enter?: number; ctl?: ComputerCtl; to?: string }) {
  const own = useComputer(ws, false);
  const { s, set, load } = ctl ?? own;
  const [restarting, setRestarting] = useState(false);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [log, setLog] = useState<JobInfo | null>(null);
  const [bouncing, setBouncing] = useState<Set<string>>(new Set());

  if (!s) return null;
  const restart = async () => {
    if (!await confirmDialog({ title: "重启这台电脑？", text: computerRestartText(s), action: "重启" })) return;
    setRestarting(true);
    try { set(await http.post<ComputerStatus>(`${computerPath(ws)}/restart`, {})); }
    catch (e) { void noticeDialog("重启失败", e instanceof Error ? e.message : undefined); }
    setRestarting(false);
  };
  const cancel = async (j: JobInfo) => {
    setCancelling((c) => new Set(c).add(j.id));
    try { await http.post(`/api/jobs/${j.id}/cancel`, {}); await load(); } catch { /* 下一次刷新会告诉真实状态 */ }
    setCancelling((c) => { const n = new Set(c); n.delete(j.id); return n; });
  };
  const bounce = async (v: ServiceInfo) => {
    setBouncing((b) => new Set(b).add(v.id));
    try { await http.post(`/api/jobs/${v.id}/restart`, {}); await load(); }
    catch (e) { void noticeDialog("重启失败", e instanceof Error ? e.message : undefined); }
    setBouncing((b) => { const n = new Set(b); n.delete(v.id); return n; });
  };
  const ratio = computerMemoryRatio(s);
  const hint = computerHint(s);
  const down = s.sandbox.state === "unreachable";
  const oom = computerOomNote(s);
  const label = [computerSemantics(s), oom].filter(Boolean).join("，");
  const hintEl = hint && <span key={hint} className={`row-hint computer-hint${computerHintWarn(s) ? " is-warn" : ""}`} aria-hidden>{hint}</span>;
  const machine = s.machine ? machineLine(s.machine) : null;
  return (
    <Section title={title} enter={enter}
      action={s.sandbox.state === "running" && <button className="btn btn-ghost btn-sm" disabled={restarting} onClick={restart}>{restarting ? "正在重启" : "重启"}</button>}>
      <ListGroup>
        <ListRow className={`computer-status${down ? " is-down" : ""}`} to={to ?? undefined} role={to ? undefined : "group"} label={label}
          icon={down ? <IconCloudOff /> : <IconComputer />}
          title={<span key={s.sandbox.state} className="computer-state">{computerStateLabel(s.sandbox.state)}</span>} sub={computerDetail(s)}
          extra={<>
            {ratio != null && (
              <div className={`meter computer-meter${ratio >= COMPUTER_MEMORY_TIGHT ? " meter-near" : ""}`}>
                <span style={{ transform: `scaleX(${ratio})` }} />
              </div>
            )}
            {oom && <div key={s.sandbox.oom_kills} className="computer-oom">{oom}</div>}
          </>}
          trail={to ? <>{hintEl}<IconChevron /></> : hintEl || null} />
        {machine && ( // v2.85 整台服务器（只有个人工作区给）
          <ListRow icon={<IconServer />} title="整台服务器" sub={machine} />
        )}
        {(s.services ?? []).map((v) => (
          <ListRow key={v.id} className={`computer-svc is-${v.health}`} onClick={() => setLog(v)} label={`${serviceSemantics(v)}，看日志`} trail={null}
            icon={<i key={v.health} className={`job-dot svc-dot is-${v.health}`} />} title={v.title}
            sub={<>{v.health === "gave_up" && <span className="svc-problem">已停止 · </span>}{serviceLine(v)}</>}
            control={<button className="btn btn-ghost btn-sm" disabled={bouncing.has(v.id)} onClick={() => void bounce(v)}>
              {bouncing.has(v.id) ? "正在重启" : serviceAction(v.health)}</button>} />
        ))}
        {s.running_jobs.map((j) => (
          <ListRow key={j.id} onClick={() => setLog(j)} label={`${j.title}，运行 ${jobDuration(j.elapsed)}，看日志`} trail={null}
            icon={<i className="job-dot" />} title={j.title} sub={jobRowSubtitle(j)}
            control={<button className="btn btn-ghost btn-sm" disabled={cancelling.has(j.id)} onClick={() => void cancel(j)}>
              {cancelling.has(j.id) ? "正在取消" : "取消"}</button>} />
        ))}
      </ListGroup>
      {log && <JobLog job={log} onClose={() => setLog(null)} />}
    </Section>
  );
}

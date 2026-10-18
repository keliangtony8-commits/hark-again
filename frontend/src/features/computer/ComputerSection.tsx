import { memo, useCallback, useState } from "react";
import { JobLog } from "../../blocks/JobBlock";
import { http } from "../../lib/api";
import { COMPUTER_MEMORY_TIGHT, type ComputerStatus, computerDetail, computerHint, computerHintWarn, computerMemoryRatio,
  computerOomNote, computerPath, machineLine, computerRestartText, computerSemantics, computerStateLabel, serviceAction, serviceLine,
  serviceSemantics } from "../../lib/computer";
import { jobDuration, jobRowSubtitle } from "../../lib/jobs";
import type { JobInfo } from "../../lib/types";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconCloudOff, IconComputer, IconRefresh, IconServer } from "../../ui/icons";
import { ListGroup, ListRow } from "../../ui/kit";
import "./computer.css";
import { peekComputer, setComputer, useComputerLoad, useComputerSelect, useLate } from "./useComputer";

/** 我的电脑的状态部件（v1.25 起；v3.5.1 拆开 = App features/computer/computer_section.dart，供一屏概览和子页组合，见 ComputerScreen.tsx）：
 *  ComputerStatusGroup  一个分组：状态行（运行中 / 行尾小字 / CPU · 内存 · 文件 / 内存条 / 打满警示）→“整台服务器”→ 常驻服务 + 后台任务行；
 *                       limit 给了只露前几行，多了一行“全部 N 个 ›”（allTo）进子页 tasks；status=false = 后台任务子页（只有服务 + 任务，不限行）。
 *  服务行（v1.82）：健康点、副标题、行尾 重启 / 立即重启 / 重新启动（POST /api/jobs/{id}/restart，不用确认）；任务行尾“取消”；点行看完整日志。
 *  ComputerRestartButton 标题行右侧圆玻璃钮“重启”（只在运行中给）：确认后停掉后台任务、删容器，文件和装过的包都在。
 *  每一行 memo + useComputerSelect 只取自己的字段：轮询回来只有变了的行重渲染。 */

type StatusView = {
  state: ComputerStatus["sandbox"]["state"]; detail: string; hint: string | null; hintWarn: boolean; ratio: number | null;
  oom: string | null; oomKills: number; label: string;
} | null;

const statusView = (s: ComputerStatus | undefined): StatusView => s ? {
  state: s.sandbox.state, detail: computerDetail(s), hint: computerHint(s), hintWarn: computerHintWarn(s), ratio: computerMemoryRatio(s),
  oom: computerOomNote(s), oomKills: s.sandbox.oom_kills ?? 0, label: [computerSemantics(s), computerOomNote(s)].filter(Boolean).join("，"),
} : null;

const StatusRow = memo(function StatusRow({ ws, late }: { ws: string; late: boolean }) {
  const v = useComputerSelect(ws, statusView);
  if (!v) return null;
  const down = v.state === "unreachable";
  return (
    <ListRow className={`computer-status${down ? " is-down" : ""}`} role="group" label={v.label}
      icon={down ? <IconCloudOff /> : <IconComputer />}
      title={<span key={v.state} className="computer-state">{computerStateLabel(v.state)}</span>} sub={v.detail}
      extra={<>
        {v.ratio != null && (
          <div className={`meter computer-meter${v.ratio >= COMPUTER_MEMORY_TIGHT ? " meter-near" : ""}${late ? " is-static" : ""}`}>
            <span style={{ transform: `scaleX(${v.ratio})` }} />
          </div>
        )}
        {v.oom && <div key={v.oomKills} className="computer-oom">{v.oom}</div>}
      </>}
      trail={v.hint ? <span key={v.hint} className={`row-hint computer-hint${v.hintWarn ? " is-warn" : ""}`} aria-hidden>{v.hint}</span> : null} />
  );
});

const MachineRow = memo(function MachineRow({ ws }: { ws: string }) {
  const line = useComputerSelect(ws, (s) => (s?.machine ? machineLine(s.machine) : null));
  // v2.85 整台服务器（只有个人工作区给）
  return line ? <ListRow icon={<IconServer />} title="整台服务器" sub={line} /> : null;
});

const ServiceRow = memo(function ServiceRow({ ws, id, busy, onRestart, onLog }:
  { ws: string; id: string; busy: boolean; onRestart: (id: string, title: string) => void; onLog: (id: string) => void }) {
  const v = useComputerSelect(ws, (s) => {
    const x = (s?.services ?? []).find((j) => j.id === id);
    return x ? { title: x.title, health: x.health, line: serviceLine(x), label: serviceSemantics(x) } : null;
  });
  if (!v) return null;
  return (
    <ListRow className={`computer-svc is-${v.health}`} onClick={() => onLog(id)} label={`${v.label}，看日志`} trail={null}
      icon={<i key={v.health} className={`job-dot svc-dot is-${v.health}`} />} title={v.title}
      sub={<>{v.health === "gave_up" && <span className="svc-problem">已停止 · </span>}{v.line}</>}
      control={<button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onRestart(id, v.title)}>
        {busy ? "正在重启" : serviceAction(v.health)}</button>} />
  );
});

const JobRow = memo(function JobRow({ ws, id, busy, onCancel, onLog }:
  { ws: string; id: string; busy: boolean; onCancel: (id: string) => void; onLog: (id: string) => void }) {
  const v = useComputerSelect(ws, (s) => {
    const j = s?.running_jobs.find((x) => x.id === id);
    return j ? { title: j.title, sub: jobRowSubtitle(j), label: `${j.title}，运行 ${jobDuration(j.elapsed)}，看日志` } : null;
  });
  if (!v) return null;
  return (
    <ListRow onClick={() => onLog(id)} label={v.label} trail={null} icon={<i className="job-dot" />} title={v.title} sub={v.sub}
      control={<button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onCancel(id)}>{busy ? "正在取消" : "取消"}</button>} />
  );
});

/** 有哪几行（只听 id 串；行里的数字变了由各行自己重渲染）。 */
const rowIds = (s: ComputerStatus | undefined) =>
  s ? [...(s.services ?? []).map((v) => `s:${v.id}`), ...s.running_jobs.map((j) => `j:${j.id}`)] : null;

export function ComputerStatusGroup({ ws, status = true, limit, allTo, enter }:
  { ws: string; status?: boolean; limit?: number; allTo?: string; enter?: number }) {
  const ids = useComputerSelect(ws, rowIds);
  const late = useLate();
  const load = useComputerLoad();
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [bouncing, setBouncing] = useState<Set<string>>(new Set());
  const [log, setLog] = useState<JobInfo | null>(null);

  const onLog = useCallback((id: string) => {
    const s = peekComputer(ws);
    const j = s?.running_jobs.find((x) => x.id === id) ?? (s?.services ?? []).find((x) => x.id === id);
    if (j) setLog(j);
  }, [ws]);
  const onCancel = useCallback(async (id: string) => {
    setCancelling((c) => new Set(c).add(id));
    try { await http.post(`/api/jobs/${id}/cancel`, {}); await load(); } catch { /* 下一次刷新会告诉真实状态 */ }
    setCancelling((c) => { const n = new Set(c); n.delete(id); return n; });
  }, [load]);
  const onRestart = useCallback(async (id: string) => {
    setBouncing((b) => new Set(b).add(id));
    try { await http.post(`/api/jobs/${id}/restart`, {}); await load(); }
    catch (e) { void noticeDialog("重启失败", e instanceof Error ? e.message : undefined); }
    setBouncing((b) => { const n = new Set(b); n.delete(id); return n; });
  }, [load]);

  if (!ids || (!status && !ids.length)) return null;
  const shown = limit == null ? ids : ids.slice(0, limit);
  const more = limit != null && ids.length > limit;
  return (
    <>
      <ListGroup className="computer-group" enter={late ? undefined : enter}>
        {status && <StatusRow ws={ws} late={late} />}
        {status && <MachineRow ws={ws} />}
        {shown.map((k) => {
          const id = k.slice(2);
          return k.startsWith("s:")
            ? <ServiceRow key={k} ws={ws} id={id} busy={bouncing.has(id)} onRestart={onRestart} onLog={onLog} />
            : <JobRow key={k} ws={ws} id={id} busy={cancelling.has(id)} onCancel={onCancel} onLog={onLog} />;
        })}
        {more && allTo && (
          <ListRow className="computer-all" to={allTo} title={`全部 ${ids.length} 个 ›`} trail={null} label={`全部 ${ids.length} 个服务和后台任务`} />
        )}
      </ListGroup>
      {log && <JobLog job={log} onClose={() => setLog(null)} />}
    </>
  );
}

/** 标题行右侧的“重启”圆玻璃钮（只在运行中给；确认逻辑同 v1.25）。 */
export const ComputerRestartButton = memo(function ComputerRestartButton({ ws }: { ws: string }) {
  const running = useComputerSelect(ws, (s) => s?.sandbox.state === "running");
  const [restarting, setRestarting] = useState(false);
  if (!running) return null;
  const restart = async () => {
    const s = peekComputer(ws);
    if (!s) return;
    if (!await confirmDialog({ title: "重启这台电脑？", text: computerRestartText(s), action: "重启" })) return;
    setRestarting(true);
    try { setComputer(ws, await http.post<ComputerStatus>(`${computerPath(ws)}/restart`, {})); }
    catch (e) { void noticeDialog("重启失败", e instanceof Error ? e.message : undefined); }
    setRestarting(false);
  };
  return (
    <button className="glass-btn glass computer-restart" disabled={restarting} onClick={() => void restart()}
      aria-label={restarting ? "正在重启" : "重启"} title={restarting ? "正在重启" : "重启"}><IconRefresh size={20} /></button>
  );
});

import { memo, useState } from "react";
import { http } from "../../lib/api";
import { CLEANUP_TEXT, type CleanupResult, type ComputerStatus, EMPTY_STORAGE, type InstalledTool, type StorageKey, cleanupDone, cleanupLabel,
  computerDiskLine, computerDiskNote, computerDiskRatio, computerPath, diskTight, processLine, processTitle, storageRows, toolsSummary,
  MEMORY_OTHER_TITLE, type MemoryRow, memoryOtherLine, memoryOtherShare, memoryRatio, memoryRowKey, memoryRowLine, memoryRowTitle,
  memoryTight, memoryTightNote, memoryViewLine, memoryViewOf,
  DISK_JOBS_TITLE, diskJobLine, diskJobRows, diskJobShare, diskJobSize, diskJobsNote } from "../../lib/computer";
import { JobLog } from "../../blocks/JobBlock";
import type { JobInfo } from "../../lib/types";
import { formatSize } from "../../lib/files";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconGlobe, IconExternal, IconCopy, IconDoc, IconDownload, IconFolder, IconReceipt, IconRefresh, IconSettings, IconBolt, IconDisk, IconChip, IconServer, IconTerminal, IconMore, IconTrash } from "../../ui/icons";
import { ListGroup, ListRow, Section, Sheet } from "../../ui/kit";
import { setComputer, useComputerSelect, useLate } from "./useComputer";
import { type PreviewLink, portLine, portTitle } from "../../lib/preview";
import { copyLink } from "../../lib/pages";

/** 电脑页的各节（v1.27，= App features/computer/computer_details.dart）。v3.5.1：每节是 /…/computer/:part 子页的正文，
 *  titled=false 不画节标题（页标题就是节名）；只 useComputerSelect 自己显示的值，轮询回来没变就不重渲染；滚过之后才出来的不放入场动画。 */
export const ProcessSection = memo(function ProcessSection({ ws, enter, titled = true }: { ws: string; enter?: number; titled?: boolean }) {
  const list = useComputerSelect(ws, (s) => (s && s.sandbox.state === "running" ? s.sandbox.processes ?? [] : []));
  const late = useLate();
  if (!list.length) return null;
  return (
    <Section title={titled ? "正在运行的程序" : undefined} enter={late ? undefined : enter} action={<span className="section-note">{list.length}</span>}>
      <ListGroup>
        {list.map((p) => (
          <ListRow key={p.pid} icon={<IconBolt />} title={<span className="computer-proc">{processTitle(p)}</span>} sub={processLine(p)} />
        ))}
      </ListGroup>
    </Section>
  );
});

/** 内存去哪了（v1.94，= App MemorySection）：整台已用 + 按大小排的占用者，每行一条占比细条；后台任务 / 服务点了看日志。 */
export const MemorySection = memo(function MemorySection({ ws, enter, titled = true }: { ws: string; enter?: number; titled?: boolean }) {
  const [log, setLog] = useState<JobInfo | null>(null);
  // 行 + 能看日志的那几个任务 / 服务（点行要打开它的日志）
  const pick = useComputerSelect(ws, (s) => {
    const v = s ? memoryViewOf(s) : null;
    if (!s || !v) return null;
    const ids = new Set(v.rows.map((r) => r.id).filter(Boolean));
    return { v, jobs: [...s.running_jobs, ...(s.services ?? [])].filter((j) => ids.has(j.id)) as JobInfo[] };
  });
  const late = useLate();
  if (!pick) return null;
  const { v, jobs } = pick;
  const tight = memoryTight(v);
  const note = memoryTightNote(v);
  const ratio = memoryRatio(v);
  const jobOf = (r: MemoryRow): JobInfo | null =>
    r.id ? (jobs.find((j) => j.id === r.id) ?? null) : null;
  const icon = (r: MemoryRow) => (r.kind === "job" ? <IconChip /> : r.kind === "service" ? <IconServer /> : <IconTerminal />);
  const bar = (share: number, warn: boolean) => (
    <div className={`meter computer-meter${warn ? " meter-near" : ""}${late ? " is-static" : ""}`}><span style={{ transform: `scaleX(${share})` }} /></div>
  );
  return (
    <Section title={titled ? "内存" : undefined} enter={late ? undefined : enter}>
      <ListGroup>
        <ListRow className={`computer-quota${tight ? " is-tight" : ""}`} role="group" label={[memoryViewLine(v), note].filter(Boolean).join("，")}
          icon={<IconChip />} title={<span key={memoryViewLine(v)} className="computer-state">{memoryViewLine(v)}</span>}
          extra={<>
            {ratio != null && <div className={`meter computer-meter${tight ? " meter-near" : ""}${late ? " is-static" : ""}`}><span style={{ transform: `scaleX(${ratio})` }} /></div>}
            {note && <div className="computer-oom">{note}</div>}
          </>} />
        {v.rows.map((r, i) => {
          const job = jobOf(r);
          const warn = i === 0 && tight;
          const body = (<>
            <span className={`row-icon${warn ? " computer-warn" : ""}`}>{icon(r)}</span>
            <div className="row-body">
              <div className="computer-mem-head"><span className={`row-title${r.kind === "process" ? " computer-proc" : ""}`}>{memoryRowTitle(r)}</span>
                <span key={r.memory} className="row-hint computer-hint">{formatSize(r.memory)}</span></div>
              <div className="row-sub">{memoryRowLine(r)}</div>
              {bar(r.share, warn)}
            </div>
          </>);
          return job
            ? <button key={memoryRowKey(r)} className="row computer-mem" onClick={() => setLog(job)} aria-label={`${memoryRowTitle(r)}，${formatSize(r.memory)}，${memoryRowLine(r)}，看日志`}>{body}</button>
            : <div key={memoryRowKey(r)} className="row computer-mem">{body}</div>;
        })}
        {v.other > 0 && (
          <div className="row computer-mem">
            <span className="row-icon"><IconMore /></span>
            <div className="row-body">
              <div className="computer-mem-head"><span className="row-title">{MEMORY_OTHER_TITLE}</span>
                <span key={v.other} className="row-hint computer-hint">{formatSize(v.other)}</span></div>
              <div className="row-sub">{memoryOtherLine(v)}</div>
              {bar(memoryOtherShare(v), false)}
            </div>
          </div>
        )}
      </ListGroup>
      {log && <JobLog job={log} onClose={() => setLog(null)} />}
    </Section>
  );
});

/** 最近 7 天谁写得最多（v1.98，= App DiskJobsSection）：按任务结算时的磁盘账从大到小，和内存一节同一种行；点了看完整日志。 */
export const DiskJobsSection = memo(function DiskJobsSection({ ws, enter }: { ws: string; enter?: number }) {
  const [log, setLog] = useState<JobInfo | null>(null);
  const pick = useComputerSelect(ws, (s) => {
    const rows = s ? diskJobRows(s) : [];
    return s && rows.length ? { note: diskJobsNote(s), rows: rows.map((r) => ({ ...r, share: diskJobShare(s, r) })) } : null;
  });
  const late = useLate();
  if (!pick) return null;
  const { note, rows } = pick;
  return (
    <Section title={DISK_JOBS_TITLE} enter={late ? undefined : enter}>
      <ListGroup>
        <div key={note} className="row-sub computer-diskjobs-note">{note}</div>
        {rows.map((r) => (
          <button key={r.job.id} className="row computer-mem" onClick={() => setLog(r.job)}
            aria-label={`${r.job.title}，${diskJobSize(r)}，${diskJobLine(r)}，看日志`}>
            <span className="row-icon">{r.disk.top[0]?.path === ".home/" ? <IconSettings /> : <IconDisk />}</span>
            <div className="row-body">
              <div className="computer-mem-head"><span className="row-title">{r.job.title}</span>
                <span key={r.total} className="row-hint computer-hint">{diskJobSize(r)}</span></div>
              <div className="row-sub">{diskJobLine(r)}</div>
              <div className={`meter computer-meter${late ? " is-static" : ""}`}><span style={{ transform: `scaleX(${r.share})` }} /></div>
            </div>
          </button>
        ))}
      </ListGroup>
      {log && <JobLog job={log} onClose={() => setLog(null)} />}
    </Section>
  );
});

/** 正在监听的端口（v1.30）：打开 = 签一条预览链接、新标签页开；复制 = 签好复制。只听本机的写明“打不开”、不给按钮。 */
export const PortsSection = memo(function PortsSection({ ws, enter, titled = true }: { ws: string; enter?: number; titled?: boolean }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const list = useComputerSelect(ws, (s) => (s && s.sandbox.state === "running" ? s.ports ?? [] : []));
  const late = useLate();
  if (!list.length) return null;
  const go = async (port: number, copy: boolean) => {
    // 先开空白标签页再填地址：等接口回来再 window.open 会被浏览器当成弹窗拦掉
    const tab = copy ? null : window.open("", "_blank");
    setBusy(port);
    try {
      const r = await http.post<PreviewLink>(`${computerPath(ws)}/preview`, { port });
      if (copy) { if (await copyLink(r.url)) setCopied(port); }
      else if (tab) { tab.opener = null; tab.location.href = r.url; }
    } catch (e) {
      tab?.close();
      void noticeDialog("打开预览失败", e instanceof Error ? e.message : undefined);
    }
    setBusy(null);
  };
  return (
    <Section title={titled ? "正在监听的端口" : undefined} enter={late ? undefined : enter} action={<span className="section-note">{list.length}</span>}>
      <ListGroup>
        {list.map((p) => (
          <ListRow key={p.port} icon={<IconGlobe size={16} />} title={portTitle(p.port)} problem={p.loopback ? "打不开" : undefined} sub={portLine(p)}
            control={!p.loopback && (
              <span className="row-trail computer-port-actions">
                <button className="icon-btn" aria-label={`复制端口 ${p.port} 的预览链接`} disabled={busy !== null} onClick={() => go(p.port, true)}>
                  {copied === p.port ? "✓" : <IconCopy />}</button>
                <button className="btn btn-sm btn-ghost" disabled={busy !== null} onClick={() => go(p.port, false)}>
                  <IconExternal /> {busy === p.port ? "正在打开" : "预览"}</button>
              </span>
            )} />
        ))}
      </ListGroup>
    </Section>
  );
});

const ICONS: Record<StorageKey, () => JSX.Element> = {
  files: () => <IconFolder />, installed: () => <IconDownload />, logs: () => <IconReceipt />, spill: () => <IconDoc />, cache: () => <IconRefresh />,
};

/** 磁盘配额：已用 / 上限 + 细条；快满、满了条变警示色并说清后果（与状态块的内存条同一画法）。 */
function QuotaRow({ s, late }: { s: ComputerStatus; late: boolean }) {
  const note = computerDiskNote(s);
  const line = computerDiskLine(s);
  return (
    <ListRow className={`computer-quota${diskTight(s) ? " is-tight" : ""}`} role="group" label={[line, note].filter(Boolean).join("，")}
      icon={<IconDisk />} title={<span key={line} className="computer-state">{line}</span>}
      extra={<>
        <div className={`meter computer-meter${diskTight(s) ? " meter-near" : ""}${late ? " is-static" : ""}`}>
          <span style={{ transform: `scaleX(${computerDiskRatio(s) ?? 0})` }} />
        </div>
        {note && <div key={s.disk_level} className="computer-oom">{note}</div>}
      </>} />
  );
}

/** 磁盘：配额 + 按用途拆开 + 装过的工具 + 一键清理。titled=false（磁盘子页）：不画节标题，“清理”挪到列表最后一行（= App v3.5.1）。 */
export const StorageSection = memo(function StorageSection({ ws, enter, onFiles, titled = true }:
  { ws: string; enter?: number; onFiles?: () => void; titled?: boolean }) {
  const [cleaning, setCleaning] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [tools, setTools] = useState<InstalledTool[] | null>(null);
  // 只取磁盘这几项（CPU、任务进度变了不重渲染）
  const s = useComputerSelect(ws, (c) => c && ({ disk_used: c.disk_used, disk_partial: c.disk_partial, disk_limit: c.disk_limit,
    disk_level: c.disk_level, storage: c.storage, tools: c.tools }) as ComputerStatus);
  const late = useLate();
  if (!s) return null;
  const st = s.storage ?? EMPTY_STORAGE;
  const label = cleanupLabel(st);
  const clean = async () => {
    if (!await confirmDialog({ title: "清理这台电脑？", text: CLEANUP_TEXT, action: "清理" })) return;
    setCleaning(true);
    try {
      const r = await http.post<CleanupResult>(`${computerPath(ws)}/cleanup`, {});
      setComputer(ws, r.status); setDone(cleanupDone(r.freed));
    } catch (e) { void noticeDialog("清理失败", e instanceof Error ? e.message : undefined); }
    setCleaning(false);
  };
  const all = s.tools ?? [];
  return (
    <Section title={titled ? "磁盘" : undefined} enter={late ? undefined : enter} action={titled && (label
      ? <button className="btn btn-ghost btn-sm" disabled={cleaning} onClick={clean}>{cleaning ? "正在清理" : label}</button>
      : done && <span key={done} className="section-note computer-done">{done}</span>)}>
      <ListGroup>
        {s.disk_limit != null && <QuotaRow s={s} late={late} />}
        {storageRows(st).map(([k, name, line, bytes]) => (
          <ListRow key={k} onClick={k === "files" && onFiles ? onFiles : undefined} icon={ICONS[k]()} title={name} sub={line}
            trail={<span key={bytes} className="row-hint computer-hint">{formatSize(bytes)}</span>} />
        ))}
        <ListRow onClick={all.length ? () => setTools(all) : undefined} icon={<IconSettings />} title="装过的工具" sub={toolsSummary(all)} />
        {!titled && label && (
          <ListRow key="clean" onClick={() => void clean()} disabled={cleaning} icon={<IconTrash size={20} />} title={cleaning ? "正在清理" : label} trail={null} />
        )}
        {!titled && !label && done && (
          <ListRow key="cleaned" icon={<IconTrash size={20} />} title={<span key={done} className="computer-done">{done}</span>} />
        )}
      </ListGroup>
      {tools && (
        <Sheet title="装过的工具" onClose={() => setTools(null)}>
          <p className="pick-note">装在工作区 ~/.local 里，以后的对话和后台任务都能直接用；不含系统预装的。</p>
          <ListGroup>
            {tools.map((t, i) => (
              <ListRow key={`${t.kind}-${t.name}`} enter={Math.min(i, 8)} title={t.name} sub={t.kind}
                control={t.version && <span className="row-hint">{t.version}</span>} />
            ))}
          </ListGroup>
        </Sheet>
      )}
    </Section>
  );
});

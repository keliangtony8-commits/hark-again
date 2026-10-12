import { useState } from "react";
import { http } from "../../lib/api";
import { CLEANUP_TEXT, type CleanupResult, type ComputerStatus, EMPTY_STORAGE, type InstalledTool, type StorageKey, cleanupDone, cleanupLabel,
  computerDiskLine, computerDiskNote, computerDiskRatio, computerPath, diskTight, processLine, processTitle, storageRows, toolsSummary } from "../../lib/computer";
import { formatSize } from "../../lib/files";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconGlobe, IconExternal, IconCopy, IconChevron, IconDoc, IconDownload, IconFolder, IconReceipt, IconRefresh, IconSettings, IconBolt, IconDisk } from "../../ui/icons";
import { Section, Sheet } from "../../ui/kit";
import type { ComputerCtl } from "./useComputer";
import { type PreviewLink, portLine, portTitle } from "../../lib/preview";
import { copyLink } from "../../lib/pages";

/** 电脑页的“正在运行的程序”和“磁盘”（v1.27，= App features/computer/computer_details.dart），与状态一节共用 ctl。 */
export function ProcessSection({ ctl, enter }: { ctl: ComputerCtl; enter?: number }) {
  const s = ctl.s;
  const list = s && s.sandbox.state === "running" ? s.sandbox.processes ?? [] : [];
  if (!list.length) return null;
  return (
    <Section title="正在运行的程序" enter={enter} action={<span className="section-note">{list.length}</span>}>
      <div className="list">
        {list.map((p) => (
          <div key={p.pid} className="row">
            <span className="row-icon"><IconBolt /></span>
            <div className="row-body"><div className="row-title computer-proc">{processTitle(p)}</div>
              <div className="row-sub">{processLine(p)}</div></div>
          </div>
        ))}
      </div>
    </Section>
  );
}

/** 正在监听的端口（v1.30）：打开 = 签一条预览链接、新标签页开；复制 = 签好复制。只听本机的写明“打不开”、不给按钮。 */
export function PortsSection({ ws, ctl, enter }: { ws: string; ctl: ComputerCtl; enter?: number }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const s = ctl.s;
  const list = s && s.sandbox.state === "running" ? s.ports ?? [] : [];
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
      void noticeDialog("没能打开预览", e instanceof Error ? e.message : undefined);
    }
    setBusy(null);
  };
  return (
    <Section title="正在监听的端口" enter={enter} action={<span className="section-note">{list.length}</span>}>
      <div className="list">
        {list.map((p) => (
          <div key={p.port} className="row">
            <span className="row-icon"><IconGlobe size={16} /></span>
            <div className="row-body"><div className="row-title">{portTitle(p.port)}</div>
              <div className="row-sub">{p.loopback && <><span className="row-problem">打不开</span> · </>}{portLine(p)}</div></div>
            {!p.loopback && (
              <span className="row-trail computer-port-actions">
                <button className="icon-btn" aria-label={`复制端口 ${p.port} 的预览链接`} disabled={busy !== null} onClick={() => go(p.port, true)}>
                  {copied === p.port ? "✓" : <IconCopy />}</button>
                <button className="btn btn-sm btn-ghost" disabled={busy !== null} onClick={() => go(p.port, false)}>
                  <IconExternal /> {busy === p.port ? "正在打开" : "预览"}</button>
              </span>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

const ICONS: Record<StorageKey, () => JSX.Element> = {
  files: () => <IconFolder />, installed: () => <IconDownload />, logs: () => <IconReceipt />, spill: () => <IconDoc />, cache: () => <IconRefresh />,
};

/** 磁盘配额：已用 / 上限 + 细条；快满、满了条变警示色并说清后果（与状态块的内存条同一画法）。 */
function QuotaRow({ s }: { s: ComputerStatus }) {
  const note = computerDiskNote(s);
  const line = computerDiskLine(s);
  return (
    <div className={`row computer-quota${diskTight(s) ? " is-tight" : ""}`} role="group" aria-label={[line, note].filter(Boolean).join("，")}>
      <span className="row-icon"><IconDisk /></span>
      <div className="row-body" aria-hidden>
        <div key={line} className="row-title computer-state">{line}</div>
        <div className={`meter computer-meter${diskTight(s) ? " meter-near" : ""}`}>
          <span style={{ transform: `scaleX(${computerDiskRatio(s) ?? 0})` }} />
        </div>
        {note && <div key={s.disk_level} className="computer-oom">{note}</div>}
      </div>
    </div>
  );
}

export function StorageSection({ ws, ctl, enter, onFiles }: { ws: string; ctl: ComputerCtl; enter?: number; onFiles?: () => void }) {
  const [cleaning, setCleaning] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [tools, setTools] = useState<InstalledTool[] | null>(null);
  const s = ctl.s;
  if (!s) return null;
  const st = s.storage ?? EMPTY_STORAGE;
  const label = cleanupLabel(st);
  const clean = async () => {
    if (!await confirmDialog({ title: "清理这台电脑？", text: CLEANUP_TEXT, action: "清理" })) return;
    setCleaning(true);
    try {
      const r = await http.post<CleanupResult>(`${computerPath(ws)}/cleanup`, {});
      ctl.set(r.status); setDone(cleanupDone(r.freed));
    } catch (e) { void noticeDialog("没能清理", e instanceof Error ? e.message : undefined); }
    setCleaning(false);
  };
  const all = s.tools ?? [];
  return (
    <Section title="磁盘" enter={enter} action={label
      ? <button className="btn btn-ghost btn-sm" disabled={cleaning} onClick={clean}>{cleaning ? "正在清理" : label}</button>
      : done && <span key={done} className="section-note computer-done">{done}</span>}>
      <div className="list">
        {s.disk_limit != null && <QuotaRow s={s} />}
        {storageRows(st).map(([k, name, line, bytes]) => {
          const body = (<>
            <span className="row-icon">{ICONS[k]()}</span>
            <div className="row-body"><div className="row-title">{name}</div><div className="row-sub">{line}</div></div>
            <span key={bytes} className="row-hint computer-hint">{formatSize(bytes)}</span>
          </>);
          return k === "files" && onFiles
            ? <button key={k} className="row" onClick={onFiles}>{body}</button>
            : <div key={k} className="row">{body}</div>;
        })}
        {all.length ? (
          <button className="row" onClick={() => setTools(all)}>
            <span className="row-icon"><IconSettings /></span>
            <div className="row-body"><div className="row-title">装过的工具</div><div className="row-sub">{toolsSummary(all)}</div></div>
            <span className="row-trail"><IconChevron /></span>
          </button>
        ) : (
          <div className="row"><span className="row-icon"><IconSettings /></span>
            <div className="row-body"><div className="row-title">装过的工具</div><div className="row-sub">{toolsSummary(all)}</div></div></div>
        )}
      </div>
      {tools && (
        <Sheet title="装过的工具" onClose={() => setTools(null)}>
          <p className="pick-note">装在工作区 ~/.local 里，以后的对话和后台任务都能直接用；不含系统预装的。</p>
          <div className="list">
            {tools.map((t, i) => (
              <div key={`${t.kind}-${t.name}`} className="row enter" style={{ animationDelay: `calc(var(--stagger) * ${Math.min(i, 8)})` }}>
                <div className="row-body"><div className="row-title">{t.name}</div><div className="row-sub">{t.kind}</div></div>
                {t.version && <span className="row-hint">{t.version}</span>}
              </div>
            ))}
          </div>
        </Sheet>
      )}
    </Section>
  );
}

import { useState } from "react";
import { http } from "../../lib/api";
import { CLEANUP_TEXT, type CleanupResult, EMPTY_STORAGE, type InstalledTool, type StorageKey, cleanupDone, cleanupLabel, computerPath,
  processLine, processTitle, storageRows, toolsSummary } from "../../lib/computer";
import { formatSize } from "../../lib/files";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconChevron, IconDoc, IconDownload, IconFolder, IconReceipt, IconRefresh, IconSettings, IconBolt } from "../../ui/icons";
import { Section, Sheet } from "../../ui/kit";
import type { ComputerCtl } from "./useComputer";

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

const ICONS: Record<StorageKey, () => JSX.Element> = {
  files: () => <IconFolder />, installed: () => <IconDownload />, logs: () => <IconReceipt />, spill: () => <IconDoc />, cache: () => <IconRefresh />,
};

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

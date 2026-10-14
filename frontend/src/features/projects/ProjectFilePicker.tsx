import { useEffect, useState } from "react";
import { workspaceFilesTitle, workspacePickEmptyText } from "../../lib/workspace";
import { http } from "../../lib/api";
import { extOf, MAX_MESSAGE_FILES, projectFileBlock } from "../../lib/files";
import { formatWhen } from "../../lib/format";
import type { FileBlock, ProjectFile } from "../../lib/types";
import { projectFileLine } from "./projectHomeRules";
import { IconCheck, IconFile } from "../../ui/icons";
import { Hint, Sheet, Skeleton, stagger } from "../../ui/kit";

/** 引用项目文件（v1.13，与 App pickProjectFiles 同款）：多选；已在这条消息里的（taken）显示但不能再选；
 *  room = 还能加几个。确认 → onPick(新选的，按列表顺序)。只带引用，内容由服务器每轮从项目里读。 */
export default function ProjectFilePicker({ projectId, taken, room, onPick, onClose }: {
  projectId: string; taken: Set<string>; room: number; onPick: (files: FileBlock[]) => void; onClose: () => void;
}) {
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [full, setFull] = useState(false);
  useEffect(() => {
    http.get<ProjectFile[]>(`/api/projects/${projectId}/files`).then(setFiles).catch((e) => setErr(String(e.message ?? e)));
  }, [projectId]);

  const toggle = (p: string) => {
    if (taken.has(p)) return;
    const next = new Set(chosen);
    if (next.has(p)) next.delete(p);
    else if (next.size >= room) { setFull(true); return; }
    else next.add(p);
    setFull(false);
    setChosen(next);
  };
  const confirm = () => onPick((files ?? []).filter((f) => chosen.has(f.path)).map((f) => projectFileBlock(projectId, f)));

  return (
    <Sheet title={`引用${workspaceFilesTitle(projectId)}`} onClose={onClose} actions={
      <button className="btn btn-primary" disabled={chosen.size === 0} onClick={confirm}>
        {chosen.size === 0 ? "选几个文件" : `引用 ${chosen.size} 个文件`}
      </button>
    }>
      <p className={`pick-note ${full ? "is-warn" : ""}`} aria-live="polite">
        {full ? `一条消息最多带 ${MAX_MESSAGE_FILES} 个文件` : "我读的是文件当前的内容，之后改了也会读到新的。"}
      </p>
      {err ? <Hint icon={<IconFile size={26} />} title="加载失败" text={err} />
        : files === null ? <Skeleton />
        : files.length === 0 ? <Hint icon={<IconFile size={26} />} title="文件夹是空的" text={workspacePickEmptyText(projectId)} />
        : (
          <div className="list" role="group" aria-label={workspaceFilesTitle(projectId)}>
            {files.map((f, i) => {
              const isTaken = taken.has(f.path);
              const on = isTaken || chosen.has(f.path);
              return (
                <button key={f.path} className={`row pick-row enter ${isTaken ? "row-off" : ""}`} style={stagger(i)}
                  role="checkbox" aria-checked={on} aria-disabled={isTaken} onClick={() => toggle(f.path)}>
                  <span className="row-icon file-ext">{extOf(f.name)}</span>
                  <span className="row-body">
                    <span className="row-title">{f.name}</span>
                    <span className="row-sub">{isTaken ? "已在这条消息里" : [projectFileLine(f), f.modified ? formatWhen(new Date(f.modified * 1000).toISOString()) : ""].filter(Boolean).join(" · ")}</span>
                  </span>
                  <span className={`pick-check ${on ? "on" : ""}`} aria-hidden>{on && <IconCheck size={14} />}</span>
                </button>
              );
            })}
          </div>
        )}
    </Sheet>
  );
}

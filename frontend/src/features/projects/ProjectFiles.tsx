import { useCallback, useEffect, useRef, useState } from "react";
import { fileUrl, http } from "../../lib/api";
import { extOf, formatSize } from "../../lib/files";
import type { ProjectFile } from "../../lib/types";
import { IconDownload, IconFile, IconTrash, IconUpload } from "../../ui/icons";
import { Hint, Sheet, Skeleton } from "../../ui/kit";

/** 项目工作区文件：你上传的资料，以及我在沙盒里生成的文件。 */
export default function ProjectFiles({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [files, setFiles] = useState<ProjectFile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const base = `/api/projects/${projectId}/files`;
  const enc = (p: string) => p.split("/").map(encodeURIComponent).join("/");

  const load = useCallback(() => http.get<ProjectFile[]>(base).then(setFiles), [base]);
  useEffect(() => { load(); }, [load]);

  const upload = async (list: FileList | null) => {
    setBusy(true);
    try { for (const f of Array.from(list ?? [])) await http.upload(base, f); await load(); }
    finally { setBusy(false); if (picker.current) picker.current.value = ""; }
  };
  const remove = async (p: string) => { await http.del(`${base}/${enc(p)}`); load(); };

  return (
    <Sheet title="项目文件" onClose={onClose} actions={<>
      <input ref={picker} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
      <button className="btn btn-primary" disabled={busy} onClick={() => picker.current?.click()}><IconUpload size={18} />{busy ? "上传中…" : "上传文件"}</button>
    </>}>
      {files === null ? <Skeleton /> : files.length === 0 ? (
        <Hint icon={<IconFile size={26} />} title="还没有文件" text="上传资料让我参考，或者让我在这个项目里写代码、跑命令，生成的文件都会出现在这里。" />
      ) : (
        <div className="list">
          {files.map((f) => (
            <div key={f.path} className="row">
              <span className="row-icon file-ext">{extOf(f.name)}</span>
              <div className="row-body"><div className="row-title">{f.path}</div><div className="row-sub">{formatSize(f.size)}</div></div>
              <a className="icon-btn" href={fileUrl(`${base}/${enc(f.path)}`)} download={f.name} aria-label="下载"><IconDownload /></a>
              <button className="icon-btn" onClick={() => remove(f.path)} aria-label="删除"><IconTrash /></button>
            </div>
          ))}
        </div>
      )}
    </Sheet>
  );
}

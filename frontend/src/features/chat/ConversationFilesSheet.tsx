import { useCallback, useEffect, useState } from "react";
import { fileUrl, http } from "../../lib/api";
import { extOf } from "../../lib/files";
import {
  canZip, conversationFileLine, conversationFilePath, conversationFilesPath, conversationZipPath, fileOriginCounts,
  fileOriginLabel, zipNote, type ConversationFiles,
} from "../../lib/conversationFiles";
import { IconDownload, IconFolder } from "../../ui/icons";
import { Hint, ListGroup, ListRow, Sheet, Skeleton } from "../../ui/kit";

/** 本对话全部文件（v1.33，App features/chat/conversation_files.dart 同义）：交给你的、你发的、网页下载/上传的、助手写的，
 *  最新在前，按来源筛选，一键打包下载。入口：本对话用量弹层、历史每行菜单。 */
export default function ConversationFilesSheet({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const [data, setData] = useState<ConversationFiles | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [origin, setOrigin] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    http.get<ConversationFiles>(conversationFilesPath(conversationId)).then(setData, (e) => setError(String(e?.message ?? e)));
  }, [conversationId]);
  useEffect(() => { load(); }, [load]);

  const counts = data ? fileOriginCounts(data) : [];
  const shown = data ? data.files.filter((f) => !origin || f.origin === origin) : [];
  const zippable = !!data && canZip(data);
  return (
    <Sheet title="本对话全部文件" onClose={onClose} actions={<>
      {data && data.files.length > 0 && (zippable
        ? <a className="btn btn-primary" href={fileUrl(conversationZipPath(conversationId))} download><IconDownload size={18} />打包下载</a>
        : <button className="btn btn-primary" disabled><IconDownload size={18} />打包下载</button>)}
      <button className="btn btn-ghost" onClick={onClose}>关闭</button></>}>
      {error ? (
        <Hint icon={<IconFolder size={26} />} title="加载失败" text={error} action={<button className="btn btn-ghost" onClick={load}>重试</button>} />
      ) : data === null ? <Skeleton /> : data.files.length === 0 ? (
        <Hint icon={<IconFolder size={26} />} title="这个对话还没有文件" text="你发的附件、我交给你的成果、浏览器下载的文件和我写出来的文件，都会收在这里。" />
      ) : (
        <>
          <p className="desc">{zipNote(data)}</p>
          {counts.length > 1 && (
            <div className="seg" role="group" aria-label="按来源筛选">
              <button className={`chip ${!origin ? "on" : ""}`} aria-pressed={!origin} onClick={() => setOrigin(null)}>全部 {data.files.length}</button>
              {counts.map(([o, n]) => (
                <button key={o} className={`chip ${origin === o ? "on" : ""}`} aria-pressed={origin === o}
                  onClick={() => setOrigin(origin === o ? null : o)}>{fileOriginLabel(o)} {n}</button>
              ))}
            </div>
          )}
          <ListGroup key={origin ?? "all"}>
            {shown.map((f, i) => (
              <ListRow key={f.key} enter={Math.min(i, 8)} icon={extOf(f.name)} iconClass="file-ext" title={f.name}
                problem={f.gone ? "已不在" : undefined} sub={conversationFileLine(f)} off={f.gone}
                href={f.gone ? undefined : fileUrl(conversationFilePath(f))} label={f.gone ? `${f.name}，已不在，打不开` : undefined} />
            ))}
          </ListGroup>
        </>
      )}
    </Sheet>
  );
}

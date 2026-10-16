import { useState } from "react";
import { useSwr } from "../../hooks/useSwr";
import { http } from "../../lib/api";
import { copyLink, shareLink } from "../../lib/pages";
import type { ConversationShare } from "../../lib/types";
import { IconCopy, IconGlobe, IconRefresh } from "../../ui/icons";
import { Sheet, Skeleton } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

/**
 * 分享对话 = 只读网页快照（服务端渲染，同时出现在 我的 → Pages）。与 App conversation_share.dart 同结构：
 * 没分享 → “生成分享链接”；分享中 → 链接 + 复制/分享 +（stale 时）更新快照 + 停止分享；停止过 → “恢复分享”（原链接）。
 * 状态只来自服务器响应，组件不自己推断。
 */
export default function ShareSheet({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const path = `/api/conversations/${conversationId}/share`;
  const { data: state, error, reload, mutate: setState } = useSwr<ConversationShare>(path);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const run = async (call: () => Promise<unknown>, done: string) => {
    if (busy) return;
    setBusy(true); setNote(null);
    try { setState(await call() as ConversationShare); setNote(done); }
    catch (e) { setNote((e as Error).message); }
    finally { setBusy(false); }
  };
  const share = (done: string) => run(() => http.post(path, {}), done);
  const stop = async () => {
    if (await confirmDialog({ title: "停止分享？", text: "链接会打不开，快照还留着；之后再分享，原链接恢复。", action: "停止分享" })) {
      await run(() => http.del(path), "已停止分享");
    }
  };
  const copy = async (url: string) => setNote((await copyLink(url)) ? "链接已复制" : "浏览器不允许复制，请手动选中链接");

  const live = state?.shared && state.url;
  return (
    <Sheet title="分享对话" onClose={onClose} actions={<button className="btn btn-ghost" onClick={onClose}>关闭</button>}>
      <p className="share-hint">生成一张只读网页快照，拿到链接的人都能看。审批卡和浏览器画面不会出现，附件只显示文件名。</p>
      {error ? (
        <div className="share-body"><p className="share-hint">{error.message}</p><button className="btn btn-ghost" onClick={() => void reload()}>重试</button></div>
      ) : !state ? <Skeleton rows={2} /> : live ? (
        <div className="share-body" key="on">
          <button className="share-link" onClick={() => copy(state.url!)} aria-label="复制链接">
            <IconGlobe size={18} /><span>{state.url}</span>
          </button>
          <div className="share-meta">快照更新于 {new Date((state.updated ?? 0) * 1000).toLocaleString("zh-CN", { hour12: false })}</div>
          <div className="share-actions">
            <button className="btn btn-ghost" onClick={() => copy(state.url!)}><IconCopy size={16} />复制链接</button>
            <button className="btn btn-primary" onClick={async () => { if (!(await shareLink(state.url!, state.title ?? ""))) copy(state.url!); }}>分享</button>
          </div>
          {state.stale && (
            <button className="btn btn-soft btn-block share-stale" disabled={busy} onClick={() => share("快照已更新，链接不变")}>
              <IconRefresh size={16} />对话有新内容 · 更新快照
            </button>
          )}
          <button className="btn btn-danger share-stop" disabled={busy} onClick={stop}>停止分享</button>
        </div>
      ) : (
        <div className="share-body" key="off">
          {state.slug && <p className="share-hint">之前停止过分享，恢复后还是原来的链接。</p>}
          <button className="btn btn-primary btn-block" disabled={busy}
            onClick={() => share(state.slug ? "已恢复，原链接可以打开了" : "已生成链接")}>
            <IconGlobe size={16} />{state.slug ? "恢复分享" : "生成分享链接"}
          </button>
        </div>
      )}
      {note && <div className="share-note" role="status" key={note}>{note}</div>}
    </Sheet>
  );
}

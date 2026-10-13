import { useEffect, useState } from "react";
import { useResource } from "../hooks/useResource";
import { connectCardState, startConnect } from "../lib/connect";
import type { ConnectBlock as T, Connector } from "../lib/types";
import { IconCheck, IconPlug } from "../ui/icons";

/** 连接卡（v2.36，= App blocks/connect_block.dart）：助手请你连一个账户。名字 + 状态行（可以连 / 已连接 · 账户 / 授权失效）
 *  + 助手写的理由；按钮去服务商授权页，本人完成。窗口重新获得焦点时重拉连接器列表，卡片原地换成“已连接”。 */
export default function ConnectBlock({ block }: { block: T }) {
  const list = useResource<Connector>("/api/connectors");
  const [err, setErr] = useState<string | null>(null);
  const { reload } = list;
  useEffect(() => {
    const onFocus = () => { void reload().catch(() => {}); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);
  const live = list.loading ? null : list.items.find((c) => c.id === block.provider) ?? null;
  const s = connectCardState(block, live);
  const go = async () => {
    setErr(null);
    try { await startConnect(block.provider); } catch (e) { setErr(e instanceof Error ? e.message : "无法开始连接"); }
  };
  return (
    <div className={`card blk-connect is-${s.tone}`}>
      <div className="blk-page-bar">
        <span className="blk-connect-icon"><IconPlug size={18} /></span>
        <div className="blk-link-body">
          <div className="blk-link-title">{block.name}</div>
          <div key={s.line} className="blk-connect-line fade-in">{s.tone === "done" && <IconCheck size={14} />}{s.line}</div>
          {block.reason && <div className="blk-link-host">{block.reason}</div>}
        </div>
      </div>
      {(s.button || err) && (
        <div className="blk-preview-actions">
          {err && <span className="blk-connect-err">{err}</span>}
          {s.button && <button className={`btn btn-sm ${s.tone === "done" ? "btn-ghost" : "btn-primary"}`} onClick={() => void go()}>{s.button}</button>}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import BlockRenderer from "../../blocks/BlockRenderer";
import { copyText } from "../../lib/copy";
import { speechSupported, stopIfSpeaking, toggleSpeech, useSpeechPhase } from "../../lib/speech";
import type { Message } from "../../lib/types";
import { ThinkingCard, ThoughtSummary } from "./Thought";
import CopyButton from "../../ui/CopyButton";
import { IconCheck, IconClose, IconCopy, IconEdit, IconRefresh, IconSpeaker, IconStop } from "../../ui/icons";

export type OutboxActions = { onResend: (id: string) => void; onDiscard: (id: string) => void };

/** 回复下方的操作条：复制、朗读；最后一条另有“重新生成”（由 ChatView 决定给不给）。回复生成完才出现，避免流式时跳动。 */
function MessageActions({ message, onRegenerate }: { message: Message; onRegenerate?: () => void }) {
  const phase = useSpeechPhase(message.id);
  useEffect(() => () => stopIfSpeaking(message.id), [message.id]);
  const md = copyText(message.blocks);
  const spoken = message.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim();
  return (
    <div className="msg-actions">
      {md && <CopyButton text={md} />}
      {speechSupported && spoken && (
        <button className={`icon-btn sm speak-btn ${phase}`} aria-label={phase === "idle" ? "朗读" : "停止朗读"}
          title={phase === "idle" ? "朗读" : "停止朗读"} onClick={() => toggleSpeech(message.id, spoken)}>
          {/* 准备中（向服务器要语音）= 闪烁的小点；在读 = 停止方块 */}
          <span key={phase} className="icon-pop">{phase === "loading" ? <span className="speak-dot" /> : phase === "playing" ? <IconStop /> : <IconSpeaker />}</span>
        </button>
      )}
      {onRegenerate && (
        <button className="icon-btn sm msg-regen" aria-label="重新生成" title="重新生成" onClick={onRegenerate}><IconRefresh /></button>
      )}
      {/* 半截回复：提醒内容不完整（重新生成就能补全） */}
      {message.status === "stopped" && <span className="msg-stopped"><IconStop size={12} />已停止</span>}
    </div>
  );
}

/** 没发出去的消息气泡下方的状态行：待发送 = 淡色提示；发送失败 = 点按重发 + 删除。 */
function OutboxStatus({ message, onResend, onDiscard }: { message: Message } & OutboxActions) {
  if (message.outbox === "queued") return <div className="msg-status">待发送</div>;
  return (
    <div className="msg-status err">
      <button className="msg-status-btn" onClick={() => onResend(message.id)}>发送失败 · 点按重发</button>
      <button className="icon-btn sm" aria-label="删除这条" onClick={() => onDiscard(message.id)}><IconClose size={14} /></button>
    </div>
  );
}

type Props = OutboxActions & {
  message: Message; onRegenerate?: () => void;
  /** 最后一条：回复的操作条常驻；更早的只在悬停/键盘聚焦时出现（同 App：只有最后一条常驻复制/重答）。 */
  last?: boolean;
  /** 只有最后一条可编辑的用户消息才给（由 ChatView 按 editableId 决定）；editing = 正在编辑它（气泡高亮）。 */
  onEdit?: () => void; editing?: boolean;
};

/** 根节点带 data-msg-id：ChatView 按它定位搜索命中的消息。 */
export default function MessageView({ message, last, onResend, onDiscard, onRegenerate, onEdit, editing }: Props) {
  if (message.role === "user") {
    const text = message.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim();
    const files = message.blocks.filter((b) => b.type === "file");
    return (
      <div className={`msg user ${message.outbox ?? ""} ${editing ? "editing" : ""}`} data-msg-id={message.id}>
        {files.length > 0 && <div className="msg-files"><BlockRenderer blocks={files} /></div>}
        {/* 气泡左边悬停才出现的操作：复制；最后一条另有“编辑”（键盘：输入框为空时按 ↑） */}
        {(text || onEdit) && (
          <div className="bubble-row">
            {!message.outbox && !editing && (
              <div className="msg-actions user-actions">
                {text && <CopyButton text={text} />}
                {onEdit && <button className="icon-btn sm" aria-label="编辑" title="编辑（↑）" onClick={onEdit}><IconEdit /></button>}
              </div>
            )}
            {text && <div className="bubble">{text}</div>}
          </div>
        )}
        {message.outbox && <OutboxStatus message={message} onResend={onResend} onDiscard={onDiscard} />}
      </div>
    );
  }
  const running = message.tools?.filter((t) => t.state === "running") ?? [];
  const empty = message.pending && message.blocks.length === 0 && running.length === 0;
  // AI 回复 = 左侧一张玻璃卡（块都在卡里）；还没出字时只是一颗“思考中”小胶囊
  return (
    <div className={`msg assistant ${last ? "last" : ""}`} data-msg-id={message.id}>
      {!empty && message.thought?.trim() && <ThoughtSummary message={message} />}
      {empty ? (message.thought?.trim()
        ? <ThinkingCard message={message} />
        : <div className="thinking glass-chip"><span /><span /><span /></div>) : (
        <div className="ai-card">
          <BlockRenderer blocks={message.blocks} />
          {message.pending && running.map((t) => (
            <div key={t.id} className="tool-run"><span className="tool-spin" />{t.label}…</div>
          ))}
        </div>
      )}
      {!message.pending && <MessageActions message={message} onRegenerate={onRegenerate} />}
    </div>
  );
}

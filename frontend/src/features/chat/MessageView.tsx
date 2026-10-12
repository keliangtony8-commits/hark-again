import { useEffect, useState } from "react";
import BlockRenderer from "../../blocks/BlockRenderer";
import { replySegments } from "../../blocks/registry";
import { copyText } from "../../lib/copy";
import { speechSupported, stopIfSpeaking, toggleSpeech, useSpeechPhase } from "../../lib/speech";
import type { Message } from "../../lib/types";
import { ThinkingCard, ThoughtSummary } from "./Thought";
import ActivitySummary from "./Activity";
import RetryLine from "./RetryLine";
import CopyButton from "../../ui/CopyButton";
import SaveReplyButton from "../projects/SaveReplyButton";
import { IconCheck, IconClose, IconCloudOff, IconCopy, IconEdit, IconRefresh, IconSpeaker, IconStop } from "../../ui/icons";
import { cutLabel } from "../../lib/messageStatus";

export type OutboxActions = { onResend: (id: string) => void; onDiscard: (id: string) => void };

/** 回复下方的操作条：复制、朗读、存到项目文件；最后一条另有“重新生成”（由 ChatView 决定给不给）。回复生成完才出现，避免流式时跳动。 */
function MessageActions({ message, onRegenerate, projectId }: { message: Message; onRegenerate?: () => void; projectId?: string }) {
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
      {/* 存到项目文件（v1.15）：有内容才给；项目对话直接存本项目，主聊天先选项目 */}
      {md && <SaveReplyButton messageId={message.id} projectId={projectId} />}
      {/* 半截回复：提醒内容不完整（重新生成就能补全） */}
      {cutLabel(message) && (
        <span className={`msg-stopped${message.status === "interrupted" ? " is-interrupted" : ""}`}>
          {message.status === "interrupted" ? <IconCloudOff size={12} /> : <IconStop size={12} />}{cutLabel(message)}
        </span>
      )}
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
  /** 所在项目（主聊天不给）：“存到项目文件”直接存进它。 */
  projectId?: string;
  /** 最后一条：回复的操作条常驻；更早的只在悬停/键盘聚焦时出现（同 App：只有最后一条常驻复制/重答）。 */
  last?: boolean;
  /** 只有最后一条可编辑的用户消息才给（由 ChatView 按 editableId 决定）；editing = 正在编辑它（气泡高亮）。 */
  onEdit?: () => void; editing?: boolean;
};

/** 根节点带 data-msg-id：ChatView 按它定位搜索命中的消息。 */
export default function MessageView({ message, last, onResend, onDiscard, onRegenerate, onEdit, editing, projectId }: Props) {
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
  const steps = message.steps ?? [];
  const running = steps.filter((t) => t.state === "running");
  const empty = message.pending && message.blocks.length === 0 && running.length === 0;
  // AI 回复 = 若干段（blocks/registry replySegments）：正文段是左侧玻璃回复卡，卡片块单独成卡、占满聊天区；
  // 运行中的工具条跟在最后一段正文里，最后一段是卡片时另起一张小回复卡。还没出字时只是一颗“思考中”小胶囊
  const segments = replySegments(message.blocks);
  const tools = message.pending ? running : [];
  if (tools.length && (!segments.length || segments[segments.length - 1].card)) segments.push({ card: false, blocks: [] });
  return (
    <div className={`msg assistant ${last ? "last" : ""}`} data-msg-id={message.id}>
      {!empty && message.thought?.trim() && <ThoughtSummary message={message} />}
      {/* 活动时间线（v1.28）：用过工具就多一行“用了 N 步”，生成中有完成的步骤就出现 */}
      {steps.length > 0 && (!message.pending || steps.some((t) => t.state !== "running")) && <ActivitySummary steps={steps} pending={message.pending} />}
      {/* 模型调用失败在自动重试 / 换了备用模型（v1.50）：只在生成中出现 */}
      {message.pending && message.retry && <RetryLine notice={message.retry} />}
      {empty ? (message.thought?.trim()
        ? <ThinkingCard message={message} />
        : <div className="thinking glass-chip"><span /><span /><span /></div>) : segments.map((s, i) => s.card ? (
          <div key={i} className="ai-block"><BlockRenderer blocks={s.blocks} /></div>
        ) : (
          <div key={i} className="ai-card">
            <BlockRenderer blocks={s.blocks} />
            {i === segments.length - 1 && tools.map((t) => (
              <div key={t.id} className="tool-run"><span className="tool-spin" />正在{t.title}{t.detail ? <span className="tool-run-detail"> · {t.detail}</span> : "…"}</div>
            ))}
          </div>
        ))}
      {!message.pending && <MessageActions message={message} onRegenerate={onRegenerate} projectId={projectId} />}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import BlockRenderer from "../../blocks/BlockRenderer";
import { replySegments } from "../../blocks/registry";
import { copyText } from "../../lib/copy";
import { speechSupported, stopIfSpeaking, stopSpeaking, toggleSpeech, useSpeechPhase } from "../../lib/speech";
import { writeClipboard } from "../../lib/clipboard";
import { formatClock } from "../../lib/format";
import { SAVE_REPLY_LABEL } from "../../lib/saveReply";
import type { Message, MessageQuote } from "../../lib/types";
import { ThinkingCard, ThoughtSummary } from "./Thought";
import StepCapsule from "./Activity";
import RetryLine from "./RetryLine";
import { useSaveReply } from "../projects/useSaveReply";
import { useReplyRating } from "./useReplyRating";
import type { MenuItem } from "../../ui/kit";
import { useFocusMenu } from "../../ui/FocusMenu";
import { quoteLine } from "../../lib/quote";
import { IconAlert, IconClock, IconClose, IconCloudOff, IconCopy, IconEdit, IconMore, IconPlay, IconQuoteArrow, IconRefresh, IconReply, IconSaveTo, IconSpeaker, IconStop } from "../../ui/icons";
import { CONTINUE_TEXT, continueHint, endLabel, endWarns } from "../../lib/messageStatus";

export type OutboxActions = { onResend: (id: string) => void; onDiscard: (id: string) => void };

/** §I/§J（= App 长按聚焦菜单）：气泡下没有常驻按钮。悬停（或键盘聚焦）一颗“⋯”、或在气泡上右键，打开这条消息的原地聚焦菜单（ui/FocusMenu）；
 *  回复：复制 · 回复 · 朗读 · 重新生成（只最后一条）· 存成文件 · 有用 · 不好——和 App 同序同名（电脑上原地选字，不需要“选择文字”）。
 *  动作的结果（已复制 / 已存进… / 谢谢，记下了 / 原因）写在回复下同一行状态里。 */
function useReplyMenu(message: Message, onRegenerate: (() => void) | undefined, projectId: string | undefined, onQuote: (() => void) | undefined) {
  const phase = useSpeechPhase(message.id);
  useEffect(() => () => stopIfSpeaking(message.id), [message.id]);
  const [copied, setCopied] = useState(0);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(0), 2500); return () => clearTimeout(t); }, [copied]);
  const md = copyText(message.blocks);
  const spoken = message.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim();
  const saved = useSaveReply(message.id, projectId);
  const rating = useReplyRating(message.id, message.feedback);
  const items: MenuItem[] = [
    ...(md ? [{ label: "复制", icon: <IconCopy />, onSelect: () => void writeClipboard(md).then(() => setCopied(Date.now())) }] : []),
    ...(onQuote ? [{ label: "回复", icon: <IconReply />, onSelect: onQuote }] : []),
    ...(speechSupported && spoken ? [{ label: phase === "idle" ? "朗读" : "停止朗读", icon: phase === "idle" ? <IconSpeaker /> : <IconStop />, onSelect: () => void toggleSpeech(message.id, spoken) }] : []),
    ...(onRegenerate ? [{ label: "重新生成", icon: <IconRefresh />, onSelect: onRegenerate }] : []),
    ...(md ? [{ label: SAVE_REPLY_LABEL, icon: <IconSaveTo />, onSelect: saved.start }] : []),
    ...(message.id !== "pending" ? rating.items : []),
  ];
  const note = copied ? <span key={copied} className="msg-saved fade-in" role="status">已复制</span> : saved.note ?? rating.note;
  return { items, phase, note, portals: <>{saved.picker}{rating.sheet}</> };
}

function EndIcon({ status }: Pick<Message, "status">) {
  switch (status) {
    case "interrupted": return <IconCloudOff size={12} />;
    case "wrapped": return <IconClock size={12} />;
    case "looped": return <IconAlert size={12} />;
    default: return <IconStop size={12} />;
  }
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
  /** “继续”：最后一条没正常说完的回复、且能发消息时才给（ChatView 决定）；点了等于发一句“继续”。 */
  onContinue?: () => void;
  /** 所在项目（主聊天不给）：“存到项目文件”直接存进它。 */
  projectId?: string;
  /** 这条的时间开着（ChatView timesShown 唯一状态，点这条切换）：在气泡同侧画一行时间（formatClock）。 */
  showTime?: boolean;
  /** 只有最后一条可编辑的用户消息才给（由 ChatView 按 editableId 决定）；editing = 正在编辑它（气泡高亮）。 */
  onEdit?: () => void; editing?: boolean;
  /** 菜单里的“回复”（§J 引用回复）：只给已落库、生成完的消息。onJumpQuote = 点气泡顶上的引用行，回到原消息。 */
  onQuote?: () => void; onJumpQuote?: (id: string) => void;
  /** 顶上画不画引用行（ChatView 按 lib/quote showsQuote 算：助手回复紧挨着原话时不画）。 */
  showQuote?: boolean;
};

/** 气泡顶上的引用行（= App QuoteLine）：折线连接符 + 一行原文；点一下回到原消息并闪一下；原消息已删 = 灰字斜体、点不了。 */
function QuoteLine({ quote, onJump }: { quote: MessageQuote; onJump?: (id: string) => void }) {
  const body = <><IconQuoteArrow /><span>{quoteLine(quote)}</span></>;
  return quote.missing || !onJump
    ? <div className={`msg-quote ${quote.missing ? "missing" : ""}`}>{body}</div>
    : <button className="msg-quote" onClick={(e) => { e.stopPropagation(); onJump(quote.id); }} title="回到被引用的消息">{body}</button>;
}

/** 根节点带 data-msg-id：ChatView 按它定位搜索命中的消息。 */
/** 点一下露出的时间行（§I）：灰色小字，靠气泡那侧；没落库（无时间）不画。 */
function TimeLine({ message, show }: { message: Message; show?: boolean }) {
  const t = show ? formatClock(message.created_at) : "";
  return t ? <div className="msg-time">{t}</div> : null;
}

export default function MessageView(props: Props) {
  return props.message.role === "user" ? <UserView {...props} /> : <AssistantView {...props} />;
}

/** 发出后多久内首次挂上才弹（= App Motion.sendFresh） */
const SEND_FRESH_MS = 1000;

function UserView({ message, showTime, onResend, onDiscard, onEdit, editing, onQuote, onJumpQuote, showQuote }: Props) {
  const text = message.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim();
  const files = message.blocks.filter((b) => b.type === "file");
  const skills = ["origin", "agent", "skill"].flatMap((t) => message.blocks.filter((b) => b.type === t)); // 来自 X、@子助手、$技能 依次
  const bubble = useRef<HTMLDivElement>(null);
  const menu = useFocusMenu(() => [
    ...(text ? [{ label: "复制", icon: <IconCopy />, onSelect: () => void writeClipboard(text) }] : []),
    ...(onQuote ? [{ label: "回复", icon: <IconReply />, onSelect: onQuote }] : []),
    ...(onEdit ? [{ label: "编辑", icon: <IconEdit />, onSelect: onEdit }] : []),
  ], { alignEnd: true, label: "这条消息的操作" });
  const canMenu = !message.outbox && !editing;
  // §O 本机刚发出的那条（local id、1 秒内挂上）往上弹一下；只在挂载时判定一次，历史/同步/别的设备发来的不弹
  const [fresh] = useState(() => message.id.startsWith("local-") && !!message.created_at && Date.now() - Date.parse(message.created_at) < SEND_FRESH_MS);
  return (
    <div className={`msg user ${message.outbox ?? ""} ${editing ? "editing" : ""} ${fresh ? "send-rise" : ""}`} data-msg-id={message.id} data-server-id={message.serverId}>
      {showQuote !== false && message.quote && <QuoteLine quote={message.quote} onJump={onJumpQuote} />}
      {skills.length > 0 && <div className="msg-skills"><BlockRenderer blocks={skills} /></div>}
      {files.length > 0 && <div className="msg-files"><BlockRenderer blocks={files} /></div>}
      {/* 气泡左边悬停才出现的“⋯”、或右键气泡（= App 长按）：复制 · 回复；最后一条另有“编辑”（键盘：输入框为空时按 ↑） */}
      {(text || onEdit) && (
        <div className="bubble-row">
          {canMenu && (
            <div className="msg-more">
              <button className="icon-btn sm" aria-label="这条消息的操作" aria-haspopup="menu" onClick={(e) => { e.stopPropagation(); menu.open(bubble.current); }}><IconMore /></button>
            </div>
          )}
          {text && <div className="bubble" ref={bubble} onContextMenu={canMenu ? (e) => { e.preventDefault(); menu.open(bubble.current); } : undefined}>{text}</div>}
        </div>
      )}
      {menu.node}
      {message.outbox && <OutboxStatus message={message} onResend={onResend} onDiscard={onDiscard} />}
      <TimeLine message={message} show={showTime} />
    </div>
  );
}

function AssistantView({ message, showTime, onRegenerate, onContinue, projectId, onQuote, onJumpQuote, showQuote = true }: Props) {
  const menu = useReplyMenu(message, onRegenerate, projectId, onQuote);
  const body = useRef<HTMLDivElement>(null);
  const focus = useFocusMenu(() => menu.items, { label: "这条回复的操作" });
  const note = message.pending ? null : menu.note;
  const steps = message.steps ?? [];
  const running = !!message.pending && steps.some((t) => t.state === "running");
  const hasThought = !!message.thought?.trim();
  // 还没出字：没有步骤时是“思考中”小胶囊 / 思考卡；在跑工具（或两步之间没有思考内容）时回复处什么都不画，只有下面的步骤胶囊（v3.5.5，= App）
  const waiting = !!message.pending && message.blocks.length === 0;
  const empty = waiting && !running && (hasThought || steps.length === 0);
  // AI 回复 = 若干段（blocks/registry replySegments）：正文段是左侧玻璃回复卡，卡片块单独成卡、占满聊天区；过程不进回复卡
  const segments = replySegments(message.blocks);
  return (
    <div className="msg assistant" data-msg-id={message.id}>
      {/* §C 回复不紧挨着它回应的那句时：顶上一行连接线 + 原话（和用户引用同一个 QuoteLine） */}
      {showQuote && message.quote && <QuoteLine quote={message.quote} onJump={onJumpQuote} />}
      {!empty && hasThought && <ThoughtSummary message={message} />}
      {/* 模型调用失败在自动重试 / 换了备用模型（v1.50）：只在生成中出现 */}
      {message.pending && message.retry && <RetryLine notice={message.retry} />}
      <div className="ai-body" ref={body} onContextMenu={message.pending ? undefined : (e) => {
        if (window.getSelection()?.toString()) return; // 选了字时右键照旧给浏览器的“复制”
        e.preventDefault(); focus.open(body.current);
      }}>
      {empty ? (message.thought?.trim()
        ? <ThinkingCard message={message} />
        : <div className="thinking glass-chip"><span /><span /><span /></div>) : segments.map((s, i) => s.card ? (
          <div key={i} className="ai-block"><BlockRenderer blocks={s.blocks} /></div>
        ) : (
          <div key={i} className="ai-card">
            <BlockRenderer blocks={s.blocks} />
          </div>
        ))}
      </div>
      {/* 步骤胶囊（v3.5.5）：用过工具就在回复下方一颗——生成中显示当前那一步，生成完收成“N 个步骤 · 12 秒”，点开看全部步骤 */}
      {steps.length > 0 && <StepCapsule steps={steps} pending={message.pending} />}
      {!message.pending && (
        <div className="msg-more">
          <button className="icon-btn sm" aria-label="这条回复的操作" aria-haspopup="menu" onClick={(e) => { e.stopPropagation(); focus.open(body.current); }}><IconMore /></button>
        </div>
      )}
      {focus.node}
      {/* 正在朗读：一行“点按停止”（原来是操作条里的停止键） */}
      {menu.phase !== "idle" && (
        <button className="msg-stopped msg-speaking" onClick={stopSpeaking}>
          {menu.phase === "loading" ? <span className="speak-dot" /> : <IconStop size={12} />}{menu.phase === "loading" ? "准备朗读…" : "正在朗读 · 点按停止"}
        </button>
      )}
      {menu.portals}
      {/* 照常显示的状态：没正常说完（停止 / 被打断 / 步数用完 / 原地打转）+ 菜单动作的结果 */}
      {!message.pending && (endLabel(message) || note) && (
        <div className="msg-lines">
          {endLabel(message) && (
            <span className={`msg-stopped${endWarns(message) ? " is-interrupted" : ""}`}><EndIcon status={message.status} />{endLabel(message)}</span>
          )}
          {note}
        </div>
      )}
      {!message.pending && onContinue && (
        <button className="btn btn-ghost btn-sm msg-continue" title={continueHint(message)} aria-description={continueHint(message)} onClick={onContinue}>
          <IconPlay size={14} />{CONTINUE_TEXT}
        </button>
      )}
      {!message.pending && <TimeLine message={message} show={showTime} />}
    </div>
  );
}

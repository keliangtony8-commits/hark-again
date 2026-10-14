import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from "react";
import { workspaceOf } from "../../lib/workspace";
import type { LinkStatus } from "../../lib/socket";
import { formatDay, startsNewDay } from "../../lib/format";
import type { Message, MessageQuote, OutgoingFile } from "../../lib/types";
import { quotable, quoteOf, showsQuote } from "../../lib/quote";
import { FloatingFooter } from "../../ui/kit";
import { IconArrowDown } from "../../ui/icons";
import { useStickToBottom } from "./useStickToBottom";
import Composer, { type EditDraft } from "./Composer";
import type { SlashCall } from "../../lib/slash";
import EmptyState from "./EmptyState";
import MessageView, { type OutboxActions } from "./MessageView";
import { CONTINUE_TEXT, continuable } from "../../lib/messageStatus";

type Props = OutboxActions & {
  messages: Message[]; busy: boolean; error: string | null; link: LinkStatus;
  canRegenerate: boolean; onRegenerate: () => void;
  /** 可编辑的最后一条用户消息；onEdit 改写它并重答。 */
  editableId: string | null; onEdit: (text: string) => void;
  /** 生成中；onStop 为空 = 已请求停止，停止键置灰。 */
  streaming: boolean; onStop?: () => void;
  /** 生成中能补一句给这一轮（useChat.canSteer）。 */
  canSteer?: boolean;
  /** 待定位的消息（搜索命中）；处理完调 onFocused 取走。 */
  focus: string | null; onFocused: () => void;
  /** 输入框主按钮左边的插槽（模型钮）。 */
  accessory?: ReactNode;
  onSend: (t: string, files?: OutgoingFile[], quote?: MessageQuote) => void; projectId?: string; onReconnect: () => void; greeting?: string;
  /** 本机斜杠命令（/new /compact /plan /copy /status，features/chat/slashActions.ts）；返回输入框下方的一句提示。 */
  onSlash?: (c: SlashCall, files: OutgoingFile[]) => Promise<string | undefined>;
  /** 没有消息时画什么（项目首屏）；空 = 通用问候 EmptyState。 */
  empty?: ReactNode;
};

/** 长连接断开时的提示条（输入胶囊上方的一颗玻璃胶囊）：待发送的消息会在连上后自动发出，“重试”跳过退避立刻重连。
 *  断线时还在生成 = 服务器支持续传，回答在那边接着写（useChat 续传）。 */
function LinkBar({ onRetry, streaming }: { onRetry: () => void; streaming: boolean }) {
  return (
    <div className="link-bar glass" role="status">
      <span className="link-dot" aria-hidden />
      <span className="link-text">{streaming ? "连接已断开 · 回答还在服务器上继续写" : "连接已断开 · 正在重连"}</span>
      <button className="btn btn-ghost btn-sm" onClick={onRetry}>重试</button>
    </div>
  );
}

/** 点一条消息 = 这条的时间开关（§I）；每条消息悬停一颗“⋯” = 它的动作菜单（MessageView）。
 *  编辑最后一条用户消息：点气泡下的“编辑”（或空输入框按 ↑）→ 输入框进入编辑态，发送走 onEdit。
 *  编辑态只是界面状态，放在这里；那条消息不再可编辑（开始生成、换了对话）就自动退出。 */
export default function ChatView({ messages, busy, error, link, canRegenerate, onRegenerate, editableId, onEdit, streaming, onStop, canSteer, focus, onFocused, accessory, onSend, onSlash, onReconnect, onResend, onDiscard, greeting, empty: emptyView, projectId }: Props) {
  const last = messages[messages.length - 1];
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const editing = draft && draft.id === editableId ? draft : null;
  // 引用回复（§J，= App ChatView._quoting）：菜单“回复”设上，发出 / ✕ / 换对话 / 进入编辑时清掉；编辑态优先
  const [quoting, setQuoting] = useState<MessageQuote | null>(null);
  const startEdit = () => {
    const m = messages.find((x) => x.id === editableId);
    if (!m) return;
    setQuoting(null);
    setDraft({
      id: m.id, text: m.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim(),
      hasFiles: m.blocks.some((b) => b.type === "file"),
    });
  };
  // 贴底跟随（useStickToBottom 唯一规则）：流式变高只靠 ResizeObserver 贴一次；往上翻就停，出“回到最新”
  const [footerH, setFooterH] = useState(0); // 输入胶囊浮在底部（FloatingFooter 量它的实际高度），消息从它下面滚过去
  const empty = messages.length === 0;
  const stick = useStickToBottom(!empty, [footerH]);
  const thread = stick.ref;
  // 换对话（第一条变了）或自己刚发了一条（最后一条是新的用户消息）= 回到底部；别的变化（每个 token）不动滚动位置
  const seen = useRef<{ first?: string; last?: string }>({});
  // 滚到某条中间闪一下（.flash 动画，结束自己摘掉，重复定位能再闪），不再被贴底拉走：搜索定位、点引用行都走这里
  const reveal = (id: string) => {
    const el = thread.current?.querySelector<HTMLElement>(`[data-msg-id="${CSS.escape(id)}"], [data-server-id="${CSS.escape(id)}"]`);
    if (!el) return false;
    stick.release();
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    el.classList.remove("flash");
    void el.offsetWidth;   // 重新触发动画
    el.classList.add("flash");
    el.addEventListener("animationend", () => el.classList.remove("flash"), { once: true });
    return true;
  };
  useEffect(() => {
    if (focus && reveal(focus)) { onFocused(); return; }
    const first = messages[0]?.id, lastId = last?.id, prev = seen.current;
    if (first !== prev.first || (lastId !== prev.last && last?.role === "user")) stick.pin();
    seen.current = { first, last: lastId };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, focus, onFocused]);

  // §I（用户 17:45 定稿，= App ChatView._timesShown）：点哪条显示哪条的时间，各自开关、可同时开几条；换对话清空。
  // 选了文字、点在按钮 / 链接 / 输入框 / 菜单上不算（电脑上点一下常常是在选字或操作卡片）。
  const [timesShown, setTimesShown] = useState<ReadonlySet<string>>(new Set());
  const firstId = messages[0]?.id;
  useEffect(() => { setTimesShown(new Set()); setQuoting(null); }, [firstId]);
  const toggleTime = (id: string) => (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (!t.closest(".bubble, .ai-card, .ai-block, .msg-files")) return; // 点气泡 / 回复本身才算，不算两旁空白
    if (t.closest("button, a, input, textarea, select, label, summary, [role=button], [role=menu], [contenteditable=true], .menu")) return;
    if (window.getSelection()?.toString()) return;
    setTimesShown((s) => { const n = new Set(s); if (!n.delete(id)) n.add(id); return n; });
  };

  const pad = { ["--footer-h" as string]: `${footerH}px` } as CSSProperties;
  return (
    <>
      <div className="thread" ref={thread} style={pad} onScroll={stick.onScroll} onWheel={stick.onWheel}>
        {messages.length === 0 ? (
          emptyView ?? <EmptyState onPick={(t) => onSend(t)} subtitle={greeting} />
        ) : (
          <div className="thread-inner">
            {messages.map((m, i) => (
              <div key={m.id} className="msg-slot" onClick={m.pending ? undefined : toggleTime(m.id)}>
                {startsNewDay(messages, i) && <div className="day-sep">{formatDay(m.created_at!)}</div>}
                <MessageView message={m} showTime={timesShown.has(m.id)} onResend={onResend} onDiscard={onDiscard}
                  onRegenerate={m === last && m.role === "assistant" && canRegenerate ? onRegenerate : undefined}
                  onContinue={m === last && m.role === "assistant" && canRegenerate && continuable(m) ? () => onSend(CONTINUE_TEXT) : undefined}
                  onEdit={m.id === editableId ? startEdit : undefined} editing={m.id === editing?.id} projectId={projectId}
                  onQuote={quotable(m) ? () => { setDraft(null); setQuoting(quoteOf(m)); } : undefined} onJumpQuote={reveal} showQuote={showsQuote(messages, i)} />
              </div>
            ))}
            {error && (
              <div className="error-banner">
                <span>{error}</span>
                {/* 上一轮失败、最后一条是没等到回复的用户消息：就地重试 */}
                {canRegenerate && last?.role === "user" && <button className="btn btn-ghost btn-sm" onClick={onRegenerate}>重试</button>}
              </div>
            )}
          </div>
        )}
      </div>
      <FloatingFooter onHeight={setFooterH}>
        {stick.away && !empty && (
          <button className="jump-latest glass raised" onClick={stick.jump}><IconArrowDown size={14} />回到最新</button>
        )}
        {link === "down" && <LinkBar onRetry={onReconnect} streaming={!!streaming} />}
        <Composer disabled={busy} streaming={streaming} canSteer={canSteer} onStop={onStop} accessory={accessory} workspace={workspaceOf(projectId)}
          onSlash={onSlash} editing={editing} onCancelEdit={() => setDraft(null)} onEditLast={editableId ? startEdit : undefined}
          quoting={editing ? null : quoting} onCancelQuote={() => setQuoting(null)}
          onSend={(t, files) => { if (editing) { onEdit(t); setDraft(null); } else { onSend(t, files, quoting ?? undefined); setQuoting(null); } }} />
      </FloatingFooter>
    </>
  );
}

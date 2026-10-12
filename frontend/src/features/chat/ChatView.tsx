import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from "react";
import { workspaceOf } from "../../lib/workspace";
import type { LinkStatus } from "../../lib/socket";
import { formatDay, startsNewDay } from "../../lib/format";
import type { Message, OutgoingFile } from "../../lib/types";
import { FloatingFooter } from "../../ui/kit";
import Composer, { type EditDraft } from "./Composer";
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
  /** 待定位的消息（搜索命中）；处理完调 onFocused 取走。 */
  focus: string | null; onFocused: () => void;
  /** 输入框主按钮左边的插槽（模型钮）。 */
  accessory?: ReactNode;
  onSend: (t: string, files?: OutgoingFile[]) => void; projectId?: string; onReconnect: () => void; greeting?: string;
  /** 没有消息时画什么（项目首屏）；空 = 通用问候 EmptyState。 */
  empty?: ReactNode;
};

/** 长连接断开时的提示条（输入胶囊上方的一颗玻璃胶囊）：待发送的消息会在连上后自动发出，“重试”跳过退避立刻重连。 */
function LinkBar({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="link-bar glass" role="status">
      <span className="link-dot" aria-hidden />
      <span className="link-text">连接已断开 · 正在重连</span>
      <button className="btn btn-ghost btn-sm" onClick={onRetry}>重试</button>
    </div>
  );
}

/** 离底部多少像素以内算“在底部”（贴底跟随）。 */
const PIN_SLACK = 32;

/** 编辑最后一条用户消息：点气泡下的“编辑”（或空输入框按 ↑）→ 输入框进入编辑态，发送走 onEdit。
 *  编辑态只是界面状态，放在这里；那条消息不再可编辑（开始生成、换了对话）就自动退出。 */
export default function ChatView({ messages, busy, error, link, canRegenerate, onRegenerate, editableId, onEdit, streaming, onStop, focus, onFocused, accessory, onSend, onReconnect, onResend, onDiscard, greeting, empty: emptyView, projectId }: Props) {
  const last = messages[messages.length - 1];
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const editing = draft && draft.id === editableId ? draft : null;
  const startEdit = () => {
    const m = messages.find((x) => x.id === editableId);
    if (!m) return;
    setDraft({
      id: m.id, text: m.blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim(),
      hasFiles: m.blocks.some((b) => b.type === "file"),
    });
  };
  const end = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  // 平时贴底；有定位请求时滚到那条消息的中间并闪一下（.flash 动画，结束自己摘掉，重复定位能再闪）
  useEffect(() => {
    const el = focus ? thread.current?.querySelector<HTMLElement>(`[data-msg-id="${CSS.escape(focus)}"]`) : null;
    if (!el) { pinned.current = true; end.current?.scrollIntoView({ block: "end" }); return; }
    pinned.current = false; // 定位到某条消息：别再被贴底拉走
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    el.classList.remove("flash");
    void el.offsetWidth;   // 重新触发动画
    el.classList.add("flash");
    el.addEventListener("animationend", () => el.classList.remove("flash"), { once: true });
    onFocused();
  }, [messages, focus, onFocused]);

  // 输入胶囊浮在底部（FloatingFooter 量它的实际高度），消息从它下面滚过去
  const [footerH, setFooterH] = useState(0);
  // 贴底：用户在底部（差 PIN_SLACK 以内）时，内容或底部让位后来才变高（胶囊量出高度、图片加载、卡片展开）
  // 也跟着贴回底部；往上翻了就不打扰。不然刚打开的对话，最后一张卡的按钮会压在输入胶囊下面。
  // 只有“往上翻”才取消贴底：.thread 是平滑滚动，程序滚到底的半路也会触发 scroll，那时 scrollTop 只增不减。
  const pinned = useRef(true);
  const lastTop = useRef(0);
  const onScroll = () => {
    const el = thread.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < PIN_SLACK) pinned.current = true;
    else if (el.scrollTop < lastTop.current - 1) pinned.current = false;
    lastTop.current = el.scrollTop;
  };
  const empty = messages.length === 0;
  useEffect(() => {
    const el = thread.current;
    const inner = el?.firstElementChild;
    if (!el || !inner || empty) return;
    const stick = () => { if (pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: "instant" }); };
    stick();
    const ro = new ResizeObserver(stick);
    ro.observe(inner);
    return () => ro.disconnect();
  }, [empty, footerH]);
  const pad = { ["--footer-h" as string]: `${footerH}px` } as CSSProperties;
  return (
    <>
      <div className="thread" ref={thread} style={pad} onScroll={onScroll}>
        {messages.length === 0 ? (
          emptyView ?? <EmptyState onPick={(t) => onSend(t)} subtitle={greeting} />
        ) : (
          <div className="thread-inner">
            {messages.map((m, i) => (
              <div key={m.id} className="msg-slot">
                {startsNewDay(messages, i) && <div className="day-sep">{formatDay(m.created_at!)}</div>}
                <MessageView message={m} last={m === last} onResend={onResend} onDiscard={onDiscard}
                  onRegenerate={m === last && m.role === "assistant" && canRegenerate ? onRegenerate : undefined}
                  onContinue={m === last && m.role === "assistant" && canRegenerate && continuable(m) ? () => onSend(CONTINUE_TEXT) : undefined}
                  onEdit={m.id === editableId ? startEdit : undefined} editing={m.id === editing?.id} projectId={projectId} />
              </div>
            ))}
            {error && (
              <div className="error-banner">
                <span>{error}</span>
                {/* 上一轮失败、最后一条是没等到回复的用户消息：就地重试 */}
                {canRegenerate && last?.role === "user" && <button className="btn btn-ghost btn-sm" onClick={onRegenerate}>重试</button>}
              </div>
            )}
            <div ref={end} />
          </div>
        )}
      </div>
      <FloatingFooter onHeight={setFooterH}>
        {link === "down" && <LinkBar onRetry={onReconnect} />}
        <Composer disabled={busy} streaming={streaming} onStop={onStop} accessory={accessory} workspace={workspaceOf(projectId)}
          editing={editing} onCancelEdit={() => setDraft(null)} onEditLast={editableId ? startEdit : undefined}
          onSend={(t, files) => { if (editing) { onEdit(t); setDraft(null); } else onSend(t, files); }} />
      </FloatingFooter>
    </>
  );
}

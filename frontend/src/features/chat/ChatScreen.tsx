import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BlockActionsContext } from "../../blocks/actions";
import { useChat } from "../../hooks/useChat";
import { IconHistory } from "../../ui/icons";
import { ShellLead } from "../../shell/ShellLead";
import ChatTitle from "./ChatTitle";
import ChatView from "./ChatView";
import ConversationList from "./ConversationList";
import ModelChip from "./ModelChip";
import type { Upload } from "../../lib/types";
import "./chat.css";

type Props = {
  projectId?: string;       // 有值 = 项目内聊天
  listTitle?: string;
  leading?: ReactNode;      // 有值 = 页面自带浮动标题栏（项目页：返回/文件/设置）；没有 = 主聊天，标题是外壳顶栏下的一行小字
  trailing?: ReactNode;     // 浮动标题栏右侧（项目页：文件/设置），左右对称让标题居中
  headerTitle?: string;
  emptyGreeting?: string;
};

/** 聊天屏：主聊天和项目内对话共用（设计 v2）。
 *  主聊天：外壳的浮动顶栏在上，标题是它下面居中的一行小字，窄屏的“历史”按钮传进顶栏左槽；
 *  项目对话：没有外壳顶栏，同一位置换成本页的玻璃标题栏。新对话在历史面板顶部。 */
export default function ChatScreen({ projectId, listTitle = "对话", leading, trailing, headerTitle, emptyGreeting }: Props) {
  const chat = useChat(projectId);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const nav = useNavigate();
  const consumed = useRef(false);

  // 从 Home 跳过来：带一句话就直接发出；带对话 id 就打开那段对话。用完清掉路由状态防止重复
  useEffect(() => {
    const st = location.state as { draft?: string; files?: Upload[]; open?: string } | null;
    if (!st || consumed.current) return;
    consumed.current = true;
    if (st.open) chat.open(st.open);
    else if (st.draft || st.files?.length) chat.send(st.draft ?? "", st.files);
    nav(location.pathname, { replace: true, state: null });
  }, [location, chat, nav]);

  // 搜索时列表被过滤，活动对话可能不在其中：记住它最后一次出现时的标题
  const lastTitle = useRef<{ id: string | null; title: string }>({ id: null, title: "新对话" });
  const found = chat.list.items.find((c) => c.id === chat.activeId);
  if (found) lastTitle.current = { id: found.id, title: found.title };
  const title = headerTitle ?? (lastTitle.current.id === chat.activeId && chat.activeId ? lastTitle.current.title : "新对话");
  const open = (id: string | null, focus?: string) => { chat.open(id, focus); setDrawer(false); };

  return (
    <BlockActionsContext.Provider value={{ replyApproval: chat.replyApproval }}>
      <div className={`chat ${leading ? "with-bar" : "floating"} ${drawer ? "drawer-open" : ""}`}>
        <ConversationList title={listTitle} list={chat.list} activeId={chat.activeId}
          onOpen={open} onDelete={chat.remove} onClose={() => setDrawer(false)} />
        <div className="scrim" onClick={() => setDrawer(false)} />
        <section className="chat-main">
          {leading ? (
            <header className="chat-top chat-bar glass">
              <div className="chat-bar-side">
                {leading}
                <button className="icon-btn mobile-only" onClick={() => setDrawer(true)} aria-label="历史"><IconHistory /></button>
              </div>
              <ChatTitle title={title} conversationId={chat.activeId} streaming={chat.streaming} />
              <div className="chat-bar-side end">{trailing}</div>
            </header>
          ) : (
            <>
              <ShellLead>
                <button className="glass-btn glass mobile-only" onClick={() => setDrawer(true)} aria-label="历史"><IconHistory /></button>
              </ShellLead>
              <header className="chat-top chat-caption"><ChatTitle title={title} conversationId={chat.activeId} streaming={chat.streaming} /></header>
            </>
          )}
          <ChatView messages={chat.messages} busy={chat.busy} error={chat.error} link={chat.link} greeting={emptyGreeting}
            canRegenerate={chat.canRegenerate} onRegenerate={chat.regenerate}
            editableId={chat.editableId} onEdit={chat.edit}
            streaming={chat.streaming} onStop={chat.canStop ? chat.stop : undefined}
            focus={chat.focus} onFocused={chat.takeFocus}
            accessory={<ModelChip model={chat.model} onChange={chat.setModel} />}
            onSend={chat.send} onReconnect={chat.reconnect} onResend={chat.resend} onDiscard={chat.discard} />
        </section>
      </div>
    </BlockActionsContext.Provider>
  );
}

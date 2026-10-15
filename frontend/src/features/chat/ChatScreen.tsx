import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BlockActionsContext } from "../../blocks/actions";
import { useChat } from "../../hooks/useChat";
import { useModelCatalog } from "../../hooks/useModelCatalog";
import { IconHistory } from "../../ui/icons";
import MenuPlus from "./MenuPlus";
import { ShellLead } from "../../shell/ShellLead";
import ChatTitle from "./ChatTitle";
import ChatView from "./ChatView";
import ConversationList from "./ConversationList";
import EffortChip from "./EffortChip";
import PlanModeChip from "./PlanModeChip";
import { runSlash } from "./slashActions";
import ModelChip from "./ModelChip";
import type { ConversationSummary, OutgoingFile } from "../../lib/types";
import { greetOnce, useProfile } from "../../lib/profile";
import "./chat.css";

type Props = {
  projectId?: string;       // 有值 = 项目内聊天
  listTitle?: string;
  back?: ReactNode;         // 标题行最左（项目页：返回项目列表）；和 trailing 对称，标题居中
  trailing?: ReactNode;     // 标题行最右（项目页：项目菜单 ⋯）
  headerTitle?: string;
  emptyGreeting?: string;
  /** 没有消息时的首屏（项目首屏 ProjectHome）：拿到打开对话和对话列表。 */
  empty?: (c: EmptyContext) => ReactNode;
};

export type EmptyContext = { open: (id: string) => void; conversations: ConversationSummary[] };

/** 聊天屏：主聊天和项目内对话共用（设计 v2；v2.93 §Q 起两者都在一级外壳下）。
 *  外壳的浮动顶栏在上，标题是它下面的一行小字（标题行，= App ChatScaffold header）；窄屏左上钮传进顶栏左槽：
 *  主聊天 = 历史（抽屉盖全屏）；项目 = ≡（本项目对话列表，从标题行下面滑出，开着时同一颗钮转成 + = 新对话）。
 *  项目的标题行左 ‹ 返回项目列表、右 ⋯ 项目菜单。新对话在历史面板顶部（项目抽屉里由那颗 + 承担）。 */
export default function ChatScreen({ projectId, listTitle = "对话", back, trailing, headerTitle, emptyGreeting, empty }: Props) {
  const chat = useChat(projectId);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const nav = useNavigate();
  const consumed = useRef<string | null>(null); // 用过的那次跳转（location.key）：同一页里再跳一次（转交卡打开同项目的另一段）也认

  // 从 Home 跳过来：带一句话就直接发出（新对话）；带对话 id 就打开那段，同时带话 = 打开后再发（建议卡“开始做”）。
  // 用完清掉路由状态防止重复
  useEffect(() => {
    const st = location.state as { draft?: string; files?: OutgoingFile[]; open?: string } | null;
    if (!st || consumed.current === location.key) return;
    consumed.current = location.key;
    if (st.open) chat.open(st.open).then(() => { if (st.draft?.trim()) chat.send(st.draft); });
    else if (st.draft || st.files?.length) chat.send(st.draft ?? "", st.files);
    nav(location.pathname, { replace: true, state: null });
  }, [location, chat, nav]);

  // v2.92 §P 首次问候：主聊天空白、服务器说还没问候过 → 请服务器建「初次见面」对话并打开它（= App chat_screen.dart）。
  // 助手的开场白就是那段对话的第一条消息：在聊天里问称呼，不做表单引导页。
  const profile = useProfile();
  const greetNow = !projectId && !!profile?.greet && !chat.activeId && chat.messages.length === 0;
  useEffect(() => {
    if (!greetNow) return;
    void greetOnce().then((id) => { if (id) { chat.list.refresh(); chat.open(id); } });
  }, [greetNow, chat]);

  // 搜索时列表被过滤，活动对话可能不在其中：记住它最后一次出现时的标题
  const lastTitle = useRef<{ id: string | null; title: string }>({ id: null, title: "新对话" });
  const found = chat.list.items.find((c) => c.id === chat.activeId);
  if (found) lastTitle.current = { id: found.id, title: found.title };
  const title = headerTitle ?? (lastTitle.current.id === chat.activeId && chat.activeId ? lastTitle.current.title : "新对话");
  const open = (id: string | null, focus?: string) => { chat.open(id, focus); setDrawer(false); };
  // 打开对话列表：项目里顺便刷新一次（状态胶囊以服务器为准；挂起的卡片出现在一轮中途）
  const showList = () => { setDrawer(true); if (projectId) chat.list.refresh(); };
  // v2.91 §N 项目对话的标题药丸：当前对话在列表里的标题（搜索过滤掉时沿用最后一次看到的）
  const convTitle = chat.activeId && lastTitle.current.id === chat.activeId ? lastTitle.current.title : "";
  // v2.23 转交卡 / “来自 X”：同一个范围（主聊天或同一项目）直接打开，否则跳到那边的聊天再打开（路由状态 open）
  const openElsewhere = (id: string, pid: string | null) => {
    if ((pid ?? undefined) === projectId) open(id);
    else nav(pid ? `/projects/${pid}` : "/chat", { state: { open: id } });
  };
  // /status 打开标题的本对话用量面板：每次 +1，ChatTitle 看到变化就打开
  const [statusAsk, setStatusAsk] = useState(0);
  const catalog = useModelCatalog();
  const onSlash = (c: Parameters<typeof runSlash>[0], files: OutgoingFile[]) => runSlash(c, files, {
    activeId: chat.activeId, messages: chat.messages, planMode: chat.planMode,
    open: (id) => open(id), setPlanMode: chat.setPlanMode, send: chat.send, showStatus: () => setStatusAsk((n) => n + 1),
    catalog: catalog ?? null, model: chat.model, setModel: chat.setModel, seek: chat.seek,
  });

  return (
    <BlockActionsContext.Provider value={{ replyApproval: chat.replyApproval, replyForm: chat.replyForm, onJobSettled: chat.refreshActive, undoChanges: chat.undoChanges, followUp: chat.followUp, openConversation: (id, pid) => openElsewhere(id, pid) }}>
      <div className={`chat floating ${projectId ? "project" : ""} ${drawer ? "drawer-open" : ""}`}>
        <ConversationList title={listTitle} list={chat.list} activeId={chat.activeId}
          onOpen={open} onDelete={chat.remove} onClose={() => setDrawer(false)} />
        <div className="scrim" onClick={() => setDrawer(false)} />
        <section className="chat-main">
          <ShellLead>
            {projectId
              ? <MenuPlus mobileOnly plus={drawer} label={drawer ? "新对话" : "项目对话"} onClick={() => (drawer ? open(null) : showList())} />
              : <button className="glass-btn glass mobile-only" onClick={() => setDrawer(true)} aria-label="历史"><IconHistory /></button>}
          </ShellLead>
          <header className={`chat-top chat-caption ${back || trailing ? "with-sides" : ""}`}>
            {(back || trailing) && <div className="chat-caption-side">{back}</div>}
            <ChatTitle title={title} conversationId={chat.activeId} streaming={chat.streaming} statusAsk={statusAsk} />
            {(back || trailing) && <div className="chat-caption-side end">{trailing}</div>}
          </header>
          <ChatView empty={empty?.({ open: (id) => open(id), conversations: chat.list.items })}
            pill={projectId ? { id: chat.activeId, title: convTitle } : undefined}
            projectId={projectId} messages={chat.messages} busy={chat.busy} error={chat.error} link={chat.link} greeting={emptyGreeting}
            canRegenerate={chat.canRegenerate} onRegenerate={chat.regenerate}
            editableId={chat.editableId} onEdit={chat.edit}
            streaming={chat.streaming} canSteer={chat.canSteer} onStop={chat.canStop ? chat.stop : undefined}
            focus={chat.focus} onFocused={chat.takeFocus}
            accessory={<>
              <ModelChip model={chat.model} routed={chat.routed} onChange={chat.setModel} />
              <EffortChip model={chat.model} effort={chat.effort} onChange={chat.setEffort} />
              <PlanModeChip on={chat.planMode} onChange={chat.setPlanMode} />
            </>}
            onSend={chat.send} onSlash={onSlash} onReconnect={chat.reconnect} onResend={chat.resend} onDiscard={chat.discard} />
        </section>
      </div>
    </BlockActionsContext.Provider>
  );
}

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BlockActionsContext } from "../../blocks/actions";
import { useChat } from "../../hooks/useChat";
import { useModelCatalog } from "../../hooks/useModelCatalog";
import MenuPlus from "./MenuPlus";
import { ShellLead } from "../../shell/ShellLead";
import ChatTitle from "./ChatTitle";
import ChatView from "./ChatView";
import ConversationList from "./ConversationList";
import EffortChip from "./EffortChip";
import PlanModeChip from "./PlanModeChip";
import { runSlash } from "./slashActions";
import ModelChip from "./ModelChip";
import type { OutgoingFile } from "../../lib/types";
import { greetOnce, useProfile } from "../../lib/profile";
import "./chat.css";

type Props = {
  projectId?: string;       // 有值 = 项目聊天（v2.95 项目 = 一段对话）
  emptyGreeting?: string;
  /** 项目：顶栏下那一行写的东西（纯文字项目名 ProjectTitle，点开项目菜单）代替对话标题。 */
  caption?: ReactNode;
  /** 项目：左上 ☰ = 回项目目录（v3.5.2，ProjectScreen 决定是退一页还是去 /projects）。 */
  onBack?: () => void;
};

/** 主聊天的对话目录路由（v3.5.2 照 Hark，= App /chat/history）：聊天标签里的一页，不是弹层。 */
export const CHAT_DIRECTORY = "/chat/history";

/** 聊天屏：主聊天和项目聊天共用（设计 v2；都在一级外壳下）。
 *  外壳的浮动顶栏在上，顶栏下一行（chat-caption，= App ChatScaffold header）是全站唯一的标题位：
 *    主聊天 = 对话总结标题 + 本对话用量；项目 = 纯文字项目名（caption，点开项目菜单），下面直接是那一段对话。
 *  v3.5.2 照 Hark：左上 ☰ 不开抽屉 / 弹层，而是回到本标签的“目录”（路由内导航，浏览器返回同样回来）：
 *    主聊天（窄屏）：☰ → /chat/history 对话目录（同一个 ChatScreen 实例，对话和连接不断），目录里左上同一颗钮转成 + = 新对话；
 *      点一段对话 / 新对话 / 返回 = 回聊天。宽屏历史栏照旧常驻左侧，没有这颗钮。
 *    项目：☰ → 项目目录（onBack），各宽度都有；项目没有侧栏。 */
export default function ChatScreen({ projectId, emptyGreeting, caption, onBack }: Props) {
  const chat = useChat(projectId);
  const location = useLocation();
  const nav = useNavigate();
  // 对话目录开着 = 地址在 /chat/history（App.tsx 两条路由挂同一个 ChatScreen，React 复用这一个实例）
  const dirOpen = !projectId && location.pathname === CHAT_DIRECTORY;
  const pushedDir = useRef(false); // 目录是这一页用 ☰ 推进来的：回聊天 = 退一页（= 浏览器返回）；否则（直接打开 / 刷新）换掉地址
  const showDir = () => { pushedDir.current = true; nav(CHAT_DIRECTORY); };
  const closeDir = () => {
    if (!dirOpen) return;
    if (pushedDir.current) nav(-1); else nav("/chat", { replace: true });
    pushedDir.current = false;
  };
  // 宽屏历史栏常驻，没有目录页：直接打开 /chat/history（或窗口拉宽）就回聊天
  useEffect(() => {
    if (!dirOpen) return;
    const wide = matchMedia("(min-width: 861px)");
    const check = () => { if (wide.matches) { pushedDir.current = false; nav("/chat", { replace: true }); } };
    check();
    wide.addEventListener("change", check);
    return () => wide.removeEventListener("change", check);
  }, [dirOpen, nav]);
  const consumed = useRef<string | null>(null); // 用过的那次跳转（location.key）：同一页里再跳一次（反馈 / 建议卡又指回本项目）也认

  // 从 Home 跳过来：带一句话就直接发出（新对话）；带对话 id 就打开那段，同时带话 = 打开后再发（建议卡“开始做”）。
  // 项目里不认带来的对话 id（老消息里的 id 可能是迁移时合并掉的那段）：打开的永远是项目那一段，带话就在那段里发。
  // 用完清掉路由状态防止重复
  useEffect(() => {
    const st = location.state as { draft?: string; files?: OutgoingFile[]; open?: string; focus?: string } | null;
    // 只认这几样；别的路由状态（如项目目录进来的标记）不归这里管，也不清
    if (!st || !(st.draft || st.files?.length || st.open || st.focus) || consumed.current === location.key) return;
    consumed.current = location.key;
    if (projectId) chat.openProjectChat(st.focus).then(() => { if (st.draft?.trim() || st.files?.length) chat.send(st.draft ?? "", st.files); });
    else if (st.open) chat.open(st.open, st.focus).then(() => { if (st.draft?.trim()) chat.send(st.draft); });
    else if (st.draft || st.files?.length) chat.send(st.draft ?? "", st.files);
    nav(location.pathname, { replace: true, state: null });
  }, [location, chat, nav, projectId]);

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
  const title = lastTitle.current.id === chat.activeId && chat.activeId ? lastTitle.current.title : "新对话";
  const open = (id: string | null, focus?: string) => { chat.open(id, focus); closeDir(); };
  // v2.23 转交卡 / “来自 X”：主聊天里的对话直接打开；指向项目的统一进那个项目的那一段（同一项目 = 已经在看它，只确保打开）
  // v3.2.1 历史搜索命中项目那段对话也走这里（带 focus = 命中的那条消息）
  const openElsewhere = (id: string, pid: string | null, focus?: string) => {
    if (!pid && !projectId) open(id, focus);
    else if (pid && pid === projectId) void chat.openProjectChat(focus);
    else nav(pid ? `/projects/${pid}` : "/chat", { state: { open: id, focus } });
  };
  // /status 打开标题的本对话用量面板：每次 +1，ChatTitle 看到变化就打开
  const [statusAsk, setStatusAsk] = useState(0);
  const catalog = useModelCatalog();
  const onSlash = (c: Parameters<typeof runSlash>[0], files: OutgoingFile[]) => runSlash(c, files, {
    activeId: chat.activeId, messages: chat.messages, planMode: chat.planMode, inProject: !!projectId,
    open: (id) => open(id), setPlanMode: chat.setPlanMode, send: chat.send, showStatus: () => setStatusAsk((n) => n + 1),
    catalog: catalog ?? null, model: chat.model, setModel: chat.setModel, seek: chat.seek,
  });

  return (
    <BlockActionsContext.Provider value={{ replyApproval: chat.replyApproval, replyForm: chat.replyForm, onJobSettled: chat.refreshActive, undoChanges: chat.undoChanges, followUp: chat.followUp, openConversation: (id, pid) => openElsewhere(id, pid) }}>
      <div className={`chat floating ${projectId ? "project" : ""} ${dirOpen ? "dir-open" : ""}`}>
        {!projectId && <ConversationList title="对话" list={chat.list} activeId={chat.activeId} onOpen={(id, focus, pid) => (pid ? openElsewhere(id ?? "", pid, focus) : open(id, focus))} onDelete={chat.remove} />}
        <section className="chat-main" {...(dirOpen ? { inert: "", "aria-hidden": true } : {})}>
          <ShellLead>
            {projectId
              ? <MenuPlus plus={false} label="项目" onClick={() => onBack?.()} />
              : <MenuPlus mobileOnly plus={dirOpen} label={dirOpen ? "新对话" : "历史"} onClick={() => (dirOpen ? open(null) : showDir())} />}
          </ShellLead>
          <header className="chat-top chat-caption">
            <ChatTitle title={title} head={caption} conversationId={chat.activeId} streaming={chat.streaming} statusAsk={statusAsk} />
          </header>
          <ChatView projectId={projectId} messages={chat.messages} busy={chat.busy} error={chat.error} link={chat.link} greeting={emptyGreeting}
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

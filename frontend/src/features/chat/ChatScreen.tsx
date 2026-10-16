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
import type { OutgoingFile } from "../../lib/types";
import { greetOnce, useProfile } from "../../lib/profile";
import "./chat.css";

type Props = {
  projectId?: string;       // 有值 = 项目聊天（v2.95 项目 = 一段对话）
  emptyGreeting?: string;
  /** 项目：顶栏下那一行写的东西（项目名药丸 ProjectPill）代替对话标题。 */
  caption?: ReactNode;
  /** 项目：左上 ≡ 打开的项目切换栏。render 拿到 close（选了项目就收起）；onOpen = 打开时刷新一次（状态胶囊以服务器为准）；
   *  onNew = 抽屉开着时同一颗钮转成的 + = 新建项目。 */
  switcher?: { render: (close: () => void) => ReactNode; onOpen?: () => void; onNew: () => void };
};

/** 聊天屏：主聊天和项目聊天共用（设计 v2；都在一级外壳下）。
 *  外壳的浮动顶栏在上，顶栏下一行（chat-caption，= App ChatScaffold header）是全站唯一的标题位：
 *    主聊天 = 对话总结标题 + 本对话用量；项目 = 项目名药丸（caption，点开项目菜单），下面直接是那一段对话。
 *  窄屏左上钮传进顶栏左槽：主聊天 = 历史（抽屉盖全屏，新对话在历史面板顶部）；
 *    项目 = ≡ 打开项目切换栏（从标题行下面滑出），开着时同一颗钮转成 + = 新建项目。宽屏切换栏常驻左侧。 */
export default function ChatScreen({ projectId, emptyGreeting, caption, switcher }: Props) {
  const chat = useChat(projectId);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const nav = useNavigate();
  const consumed = useRef<string | null>(null); // 用过的那次跳转（location.key）：同一页里再跳一次（反馈 / 建议卡又指回本项目）也认

  // 从 Home 跳过来：带一句话就直接发出（新对话）；带对话 id 就打开那段，同时带话 = 打开后再发（建议卡“开始做”）。
  // 项目里不认带来的对话 id（老消息里的 id 可能是迁移时合并掉的那段）：打开的永远是项目那一段，带话就在那段里发。
  // 用完清掉路由状态防止重复
  useEffect(() => {
    const st = location.state as { draft?: string; files?: OutgoingFile[]; open?: string; focus?: string } | null;
    if (!st || consumed.current === location.key) return;
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
  const open = (id: string | null, focus?: string) => { chat.open(id, focus); setDrawer(false); };
  // 项目切换栏：打开时刷新一次项目列表（状态胶囊以服务器为准；挂起的卡片出现在一轮中途）
  const showList = () => { setDrawer(true); switcher?.onOpen?.(); };
  // v2.23 转交卡 / “来自 X”：主聊天里的对话直接打开；指向项目的统一进那个项目的那一段（同一项目 = 已经在看它，只确保打开）
  // v3.2.1 历史搜索命中项目那段对话也走这里（带 focus = 命中的那条消息）
  const openElsewhere = (id: string, pid: string | null, focus?: string) => {
    if (!pid && !projectId) open(id, focus);
    else if (pid && pid === projectId) { void chat.openProjectChat(focus); setDrawer(false); }
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
      <div className={`chat floating ${projectId ? "project" : ""} ${drawer ? "drawer-open" : ""}`}>
        {switcher
          ? switcher.render(() => setDrawer(false))
          : <ConversationList title="对话" list={chat.list} activeId={chat.activeId} onOpen={(id, focus, pid) => (pid ? openElsewhere(id ?? "", pid, focus) : open(id, focus))} onDelete={chat.remove} />}
        <section className="chat-main">
          <ShellLead>
            {projectId
              ? <MenuPlus mobileOnly plus={drawer} label={drawer ? "新建项目" : "切换项目"}
                  onClick={() => { if (!drawer) showList(); else { setDrawer(false); switcher?.onNew(); } }} />
              : <button className="glass-btn glass mobile-only" onClick={() => setDrawer((d) => !d)} aria-label={drawer ? "收起历史" : "历史"} aria-expanded={drawer}><IconHistory /></button>}
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

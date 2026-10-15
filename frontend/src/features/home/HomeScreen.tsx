import { Fragment, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import BlockRenderer from "../../blocks/BlockRenderer";
import { useInbox } from "../../hooks/useInbox";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { HomeCard, ScheduledTask } from "../../lib/types";
import { cardEyebrow, cardRoute, cardTarget, splitTarget, type CardTarget } from "../../lib/cardTargets";
import LaunchComposer, { useAskInNewChat } from "../../shell/LaunchComposer";
import { ShellLead } from "../../shell/ShellLead";
import { WidePill } from "../../ui/glass";
import { IconChat, IconEdit, IconHistory, IconMore, IconPlug, IconPlus, IconRefresh, IconSpark, IconTrash } from "../../ui/icons";
import { Menu, Page, Skeleton, stagger } from "../../ui/kit";
import TaskSheet, { changesOf, draftOf, EMPTY_TASK } from "../me/TaskSheet";
import WallNotice from "../me/WallNotice";
import NewPanelSheet from "./NewPanelSheet";
import StackCard from "./StackCard";
import { SnoozedRow, SnoozeMenu, type Snooze } from "./Snooze";
import { removedPanels, removePanel as removeCard, revivePanel } from "./RemovedPanels";
import { InboxRow } from "./InboxRow";
import { OfferImage, OfferSource } from "./OfferMedia";
import { agendaDetail, agendaHint, agendaNowAt, clockOf, agendaProblem, agendaSummary, briefTaskOf, MORNING_BRIEF, PREP_DAY_PROMPT, todayAgenda } from "./todayAgenda";
import "./home.css";

/** 错峰入场第 i 拍（.enter 读 --i；超过 10 拍不再加，= App Motion.stagger）。 */
const nth = stagger;
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

/** 主页输入框聚焦时的建议，= App home_screen.dart homePrompts：第一个是“帮我准备今天”。 */
const HOME_PROMPTS = [PREP_DAY_PROMPT, "查一下今天的新闻", "帮我规划这周的学习", "把这段话翻译成英文"];

/** Home（v2.78 重做，docs/home-redesign.md，= App home_screen.dart）：居中一列同款卡，没有小节标题、问候、空状态。
 *  顺序：要你处理的建议卡（全无时一张连接引导卡）→ 今天（仅有任务时）→ 面板们 → 收件箱 → 一行稍后 → 创建一个新面板。
 *  起点 / 早间简报 / 找回移除的面板都在新面板弹层里。输入在底部浮动胶囊，顶栏左侧 + = 新面板。 */
export default function HomeScreen() {
  const nav = useNavigate();
  const cards = useResource<HomeCard>("/api/cards");
  const tasks = useResource<ScheduledTask>("/api/tasks");
  const [newPanel, setNewPanel] = useState(false);
  const inbox = useInbox();
  const askNew = useAskInNewChat();

  // 收件箱摘要一变（新报告、别的端读过），卡片跟着重拉
  useEffect(() => { if (inbox.version > 0) cards.reload(); }, [inbox.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const openReport = (r: HomeCard) => {
    if (!r.conversation_id) return;
    if (r.unread) inbox.markRead([r.id]);
    nav("/chat", { state: { open: r.conversation_id } });
  };

  // 主动建议卡：去处按钮读掉未读再跳；忽略后未读数跟着刷新
  const openTarget = (c: HomeCard, t: CardTarget) => {
    if (c.unread) inbox.markRead([c.id]);
    nav(cardRoute(t, c));
  };
  // 主按钮。系统提醒：发指令进新对话（恢复后服务端自己收起）。助手提议的卡：服务端开对话并记在卡上，
  // started 才把指令带过去发（重复点只回到那段）；卡留在主页变成“已交给助手”。和 App startOffer 同义。
  const doIt = async (c: HomeCard) => {
    if (c.origin !== "agent") return ask(c.action_prompt!);
    try {
      const r = await http.post<{ conversation_id: string; prompt: string; started: boolean }>(`/api/cards/${c.id}/start`, {});
      // v2.95 卡指向项目（project:<id>）：服务器把指令发进那个项目的那段对话，切到那个项目里打开（项目里只认那一段）
      const [kind, pid] = splitTarget(c.target ?? "");
      nav(kind === "project" && pid ? `/projects/${pid}` : "/chat", { state: { open: r.conversation_id, draft: r.started ? r.prompt : undefined } });
    } finally {
      cards.reload();
      inbox.refresh();
    }
  };
  const dismiss = async (c: HomeCard) => { await cards.update(c.id, { dismissed: true }); inbox.refresh(); };
  // 稍后提醒：推迟会清未读（服务端），所以同样刷新角标
  const snooze: Snooze = async (c, at) => { await cards.update(c.id, { snoozed_until: at ? at.toISOString() : null }); inbox.refresh(); };

  const ask = (text: string) => text.trim() && askNew(text.trim());
  const live = cards.items.filter((c) => !c.dismissed && !c.snoozed_until);
  // 稍后提醒（建议卡）与稍后再看（报告）合成栈末一行
  const snoozed = cards.items.filter((c) => (c.kind === "action" || c.kind === "report") && !c.dismissed && !!c.snoozed_until);
  const actions = live.filter((c) => c.kind === "action");
  const panels = live.filter((c) => c.kind === "panel");
  const reports = live.filter((c) => c.kind === "report").slice(0, 5);
  const refreshing = new Set(tasks.items.filter((t) => t.run_requested).map((t) => t.id));

  // 有面板在刷新时每 5 秒拉一次，刷完自动停
  useEffect(() => {
    if (refreshing.size === 0) return;
    const id = setInterval(() => { cards.reload(); tasks.reload(); }, 5000);
    return () => clearInterval(id);
  }, [refreshing.size]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshPanel = async (taskId: string) => { await http.post(`/api/tasks/${taskId}/run`, {}); tasks.reload(); };
  // v2.17 移除 = 停止刷新、进“最近移除”，30 天内可放回（RemovedPanels.tsx），所以不再弹危险确认
  const removePanel = async (c: HomeCard) => { await removeCard(c); cards.reload(); tasks.reload(); };
  const revive = async (c: HomeCard) => { await revivePanel(c); cards.reload(); tasks.reload(); };
  const removed = removedPanels(cards.items);
  // 编辑面板 = 编辑它的任务（同一张 TaskSheet）；改名由服务端同步到卡片，存完重拉卡片
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [schedulingBrief, setSchedulingBrief] = useState(false);
  const taskOf = (c: HomeCard) => tasks.items.find((t) => t.id === c.task_id) ?? null;

  const today = todayAgenda(tasks.items);
  const todaySummary = agendaSummary(today);
  const nowAt = agendaNowAt(today);

  // 卡片栈（= App home_screen.dart 同一顺序）：每张卡错峰浮上来；加载中整栈一块骨架
  let n = 0;
  return (
    <Page footer={<LaunchComposer suggestions={HOME_PROMPTS} />}>
      <ShellLead>
        <button className="glass-btn glass" onClick={() => setNewPanel(true)} aria-label="新面板" title="新面板"><IconPlus /></button>
      </ShellLead>

      {cards.loading ? <Skeleton rows={3} /> : <div className="home-stack">
        {actions.length === 0 && (
          <StackCard style={nth(n++)} className="onboarding">
            <h3 className="glass-title">我还能做更多</h3>
            <p className="glass-sub">连接邮箱和日历后，我会在这里主动提醒你要处理的事。</p>
            <div className="pills"><Link className="pill" to="/me/connectors"><IconPlug size={18} />去连接</Link></div>
          </StackCard>
        )}
        {actions.map((c) => {
          const target = cardTarget(c.target);
          const started = c.origin === "agent" && !!c.conversation_id;
          const eyebrow = cardEyebrow(c, target);
          const Icon = target?.Icon ?? (started ? IconChat : IconSpark);
          return (
            <div key={c.id} className="glass-card action-card enter" style={nth(n++)}>
              <OfferImage card={c} />
              <div className="action-card-head">
                <span className="row-icon icon-pop" key={String(started)}><Icon /></span>
                <div className="action-card-title">
                  {eyebrow && <span className="action-card-eyebrow fade-in" key={eyebrow}>{eyebrow}</span>}
                  {c.title}
                </div>
                <SnoozeMenu card={c} onSnooze={snooze} />
              </div>
              {c.blocks.length > 0 && <BlockRenderer blocks={c.blocks} />}
              <OfferSource card={c} />
              {/* 等宽胶囊，最后一颗是主操作（实心） */}
              <div className="pills">
                <button className="pill" onClick={() => dismiss(c)}>{started ? "收起" : "忽略"}</button>
                {target && <button className={`pill ${c.action_prompt ? "" : "primary"}`} onClick={() => openTarget(c, target)}><target.Icon size={16} />{target.label}</button>}
                {c.action_prompt && (
                  <button className="pill primary" onClick={() => doIt(c)}>
                    {started ? <><IconChat size={16} />查看对话</> : c.action_label?.trim() || "去做"}
                  </button>
                )}
              </div>
            </div>
          );
        })}

        {/* 今天：只在今天真有任务时出现（todayAgenda.ts 定规则）；下一个加重、过去的变淡、失败/暂停只染那两个字；点行进任务详情 */}
        {!tasks.loading && today.length > 0 && (
          <StackCard title="今天" rows style={nth(n++)} trailing={<span key={todaySummary} className="stack-note fade-in">{todaySummary}</span>}>
            {today.map((it, i) => {
              const problem = agendaProblem(it);
              const hint = agendaHint(it);
              return (
                <Fragment key={it.task.id}>
                {i === nowAt && <div className="today-now enter" style={nth(i + 1)} role="separator" aria-label={`现在 ${clockOf(new Date())}`}><span>现在</span><i /></div>}
                <Link to={`/me/tasks/${it.task.id}`} className={`row today-row enter ${it.faded ? "row-off" : ""} ${it.state === "next" ? "today-next" : ""}`} style={nth(i + 1)}>
                  <span className="today-time">{it.time}</span>
                  <div className="row-body"><div className="row-title">{it.task.name}</div>
                    <div className="row-sub">{problem && <><span className="row-problem">{problem}</span> · </>}{agendaDetail(it)}</div></div>
                  {hint && <span key={hint} className="row-hint fade-in">{hint}</span>}
                </Link>
                </Fragment>
              );
            })}
          </StackCard>
        )}

        {panels.map((p) => {
          const busy = !!p.task_id && refreshing.has(p.task_id);
          const time = busy ? "刷新中…" : timeOf(p.updated_at);
          return (
            <StackCard key={p.id} title={p.title} className={`panel ${busy ? "busy" : ""}`} style={nth(n++)} trailing={<span className="panel-tools">
              {/* 换字时 key 变 → 新字浮上来（刷完那一下看得见“更新了”）；内容里的关键数字由 CountUp 从旧值滚到新值 */}
              <span key={time} className="stack-note enter">{time}</span>
              {p.task_id && <button className="icon-btn sm" onClick={() => refreshPanel(p.task_id!)} disabled={busy} aria-label="刷新"><IconRefresh /></button>}
              <Menu trigger={<IconMore />} items={[
                ...(taskOf(p) ? [
                  { label: "编辑面板", icon: <IconEdit />, onSelect: () => setEditing(taskOf(p)) },
                  { label: "刷新记录", icon: <IconHistory />, onSelect: () => nav(`/me/tasks/${p.task_id}`) },
                ] : []),
                { label: "移除", icon: <IconTrash />, danger: true, onSelect: () => removePanel(p) },
              ]} />
            </span>}>
              {/* v2.15 碰壁：内容还是上一次的，上面一条说清卡在哪、要不要你处理 */}
              {taskOf(p) && <WallNotice task={taskOf(p)!} onRetry={() => refreshPanel(p.task_id!)} busy={busy} />}
              <div className="panel-body"><BlockRenderer blocks={p.blocks} /></div>
            </StackCard>
          );
        })}

        {reports.length > 0 && (
          <StackCard title="收件箱" rows style={nth(n++)}
            trailing={inbox.summary.unread > 0 ? <button className="btn btn-ghost btn-sm" onClick={() => inbox.markRead()}>全部已读</button> : undefined}>
            {reports.map((r) => (
              <InboxRow key={r.id} card={r} time={timeOf(r.updated_at)} onOpen={openReport}
                snooze={snooze} read={(c) => inbox.markRead([c.id])} dismiss={dismiss} />
            ))}
          </StackCard>
        )}

        <SnoozedRow cards={snoozed} onSnooze={snooze} />
        <div className="enter" style={nth(n++)}><WidePill label="创建一个新面板" onClick={() => setNewPanel(true)} /></div>
      </div>}

      {newPanel && <NewPanelSheet onClose={() => setNewPanel(false)} briefMissing={!briefTaskOf(tasks.items)} removed={removed}
        onBrief={() => setSchedulingBrief(true)} onRevive={revive} />}
      {schedulingBrief && <TaskSheet title="早间简报" initial={{ ...EMPTY_TASK, ...MORNING_BRIEF }} onClose={() => setSchedulingBrief(false)}
        onSave={async (d) => { await tasks.create(d); }} />}
      {editing && <TaskSheet title="编辑面板" panel initial={draftOf(editing)} onClose={() => setEditing(null)}
        onSave={async (d) => {
          const c = changesOf(draftOf(editing), d);
          if (Object.keys(c).length) { await tasks.update(editing.id, c); cards.reload(); }
        }} />}
    </Page>
  );
}

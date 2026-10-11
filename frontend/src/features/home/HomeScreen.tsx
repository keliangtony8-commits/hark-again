import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import BlockRenderer from "../../blocks/BlockRenderer";
import { useInbox } from "../../hooks/useInbox";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { HomeCard, ScheduledTask } from "../../lib/types";
import { cardRoute, cardTarget, type CardTarget } from "../../lib/cardTargets";
import { scheduleLabel, todayAt } from "../../lib/taskLabels";
import { formatDate } from "../../lib/format";
import LaunchComposer, { useAskInNewChat } from "../../shell/LaunchComposer";
import { ShellLead } from "../../shell/ShellLead";
import { WidePill } from "../../ui/glass";
import { IconChevron, IconClock, IconEdit, IconHistory, IconInbox, IconMore, IconPlug, IconPlus, IconRefresh, IconSpark, IconTrash } from "../../ui/icons";
import { Menu, Page, Section, Skeleton, stagger } from "../../ui/kit";
import TaskSheet, { changesOf, draftOf } from "../me/TaskSheet";
import NewPanelSheet, { newPanelPrompt, panelIdeas } from "./NewPanelSheet";
import { SnoozedRow, SnoozeMenu, type Snooze } from "./Snooze";
import "./home.css";
import { confirmDialog } from "../../ui/dialog";

/** 错峰入场第 i 拍（.enter 读 --i；超过 10 拍不再加，= App Motion.stagger）。 */
const nth = stagger;
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
/** 收件箱一行预览：取结果里第一段文字，去掉 Markdown 符号。 */
const preview = (c: HomeCard) => {
  const t = c.blocks.find((b) => b.type === "text");
  return t && t.type === "text" ? t.text.replace(/[#*_`>|-]/g, "").replace(/\s+/g, " ").trim().slice(0, 80) : "点开查看结果";
};

/** Home：今天要紧的事一屏看完（设计 v2）。从上到下按“要我处理 → 一眼看 → 结果 → 安排”排：
 *  问候、为你准备（主动建议 + 稍后提醒一行 / 都没有时是连接引导卡）、面板（+ 创建一个新面板）、收件箱、今天。
 *  输入在底部的浮动胶囊（LaunchComposer），顶栏左侧的 + = 新面板。 */
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
  const dismiss = async (c: HomeCard) => { await cards.update(c.id, { dismissed: true }); inbox.refresh(); };
  // 稍后提醒：推迟会清未读（服务端），所以同样刷新角标
  const snooze: Snooze = async (c, at) => { await cards.update(c.id, { snoozed_until: at ? at.toISOString() : null }); inbox.refresh(); };

  const now = new Date();
  const hour = now.getHours();
  const greet = hour < 6 ? "夜深了" : hour < 12 ? "早上好" : hour < 18 ? "下午好" : "晚上好";
  const date = formatDate(now);

  const ask = (text: string) => text.trim() && askNew(text.trim());
  const live = cards.items.filter((c) => !c.dismissed && !c.snoozed_until);
  const snoozed = cards.items.filter((c) => c.kind === "action" && !c.dismissed && !!c.snoozed_until);
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
  const removePanel = async (c: HomeCard) => {
    if (!(await confirmDialog({ title: `移除面板「${c.title}」？`, text: "它不会再刷新。", action: "移除" }))) return;
    if (c.task_id) await tasks.remove(c.task_id); // 删任务时后端会连卡一起删
    cards.reload();
  };
  // 编辑面板 = 编辑它的任务（同一张 TaskSheet）；改名由服务端同步到卡片，存完重拉卡片
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const taskOf = (c: HomeCard) => tasks.items.find((t) => t.id === c.task_id) ?? null;

  const today = tasks.items
    .filter((t) => t.active && t.output === "report")
    .map((t) => ({ t, at: todayAt(t) }))
    .filter((x): x is { t: ScheduledTask; at: string } => !!x.at)
    .sort((a, b) => a.at.localeCompare(b.at));

  return (
    <Page footer={<LaunchComposer />}>
      <ShellLead>
        <button className="glass-btn glass" onClick={() => setNewPanel(true)} aria-label="新面板" title="新面板"><IconPlus /></button>
      </ShellLead>
      <div className="home-hero">
        <div className="home-date">{date}</div>
        <h1>{greet}</h1>
      </div>

      <Section title="为你准备">
        {cards.loading ? <Skeleton rows={2} /> : actions.length === 0 && snoozed.length === 0 ? (
          <div className="glass-card onboarding enter">
            <h3 className="glass-title">连接邮箱和日历，我会主动提醒你</h3>
            <p className="glass-sub">要回的邮件、快到的截止日期、明天的课，都会出现在这里。</p>
            <div className="pills"><Link className="pill primary" to="/me/connectors"><IconPlug size={18} />去连接</Link></div>
          </div>
        ) : actions.map((c, i) => {
          const target = cardTarget(c.target);
          const Icon = target?.Icon ?? IconSpark;
          return (
            <div key={c.id} className="glass-card action-card enter" style={nth(i)}>
              <div className="action-card-head">
                <span className="row-icon"><Icon /></span>
                <div className="action-card-title">{c.title}</div>
                <SnoozeMenu card={c} onSnooze={snooze} />
              </div>
              {c.blocks.length > 0 && <BlockRenderer blocks={c.blocks} />}
              {/* 等宽胶囊，最后一颗是主操作（实心） */}
              <div className="pills">
                <button className="pill" onClick={() => dismiss(c)}>忽略</button>
                {target && <button className={`pill ${c.action_prompt ? "" : "primary"}`} onClick={() => openTarget(c, target)}><target.Icon size={16} />{target.label}</button>}
                {c.action_prompt && <button className="pill primary" onClick={() => ask(c.action_prompt!)}>去做</button>}
              </div>
            </div>
          );
        })}
        {!cards.loading && <SnoozedRow cards={snoozed} onSnooze={snooze} />}
      </Section>

      <Section title="面板">
        {cards.loading ? <Skeleton rows={1} /> : panels.length === 0 ? (
          // 还没有面板：一句话 + 几个起点胶囊（点了开新对话去搭），下面仍是“创建一个新面板”
          <div className="panel-ideas enter">
            <p>面板会按时替你盯着一件事，打开主页一眼就看到。</p>
            <div className="panel-idea-list">
              {panelIdeas.map((idea, i) => <button key={idea} className="panel-idea enter" style={nth(i + 1)} onClick={() => ask(newPanelPrompt(idea))}>{idea}</button>)}
            </div>
          </div>
        ) : panels.map((p, i) => {
          const busy = !!p.task_id && refreshing.has(p.task_id);
          const time = busy ? "刷新中…" : timeOf(p.updated_at);
          return (
            <div key={p.id} className={`glass-card panel enter ${busy ? "busy" : ""}`} style={nth(i)}>
              <div className="panel-head">
                <span className="panel-title">{p.title}</span>
                {/* 换字时 key 变 → 新字浮上来（刷完那一下看得见“更新了”）；内容里的关键数字由 CountUp 从旧值滚到新值 */}
                <span key={time} className="panel-time enter">{time}</span>
                {p.task_id && <button className="icon-btn sm" onClick={() => refreshPanel(p.task_id!)} disabled={busy} aria-label="刷新"><IconRefresh /></button>}
                <Menu trigger={<IconMore />} items={[
                  ...(taskOf(p) ? [
                    { label: "编辑面板", icon: <IconEdit />, onSelect: () => setEditing(taskOf(p)) },
                    { label: "刷新记录", icon: <IconHistory />, onSelect: () => nav(`/me/tasks/${p.task_id}`) },
                  ] : []),
                  { label: "移除", icon: <IconTrash />, danger: true, onSelect: () => removePanel(p) },
                ]} />
              </div>
              <div className="panel-body"><BlockRenderer blocks={p.blocks} /></div>
            </div>
          );
        })}
        <div className="enter" style={nth(panels.length)}><WidePill label="创建一个新面板" onClick={() => setNewPanel(true)} /></div>
      </Section>

      {reports.length > 0 && (
        <Section title="收件箱" action={inbox.summary.unread > 0 ? <button className="btn btn-ghost btn-sm" onClick={() => inbox.markRead()}>全部已读</button> : undefined}>
          <div className="list enter" style={nth(1)}>
            {reports.map((r) => (
              <button key={r.id} className={`row report-row ${r.unread ? "unread" : ""}`} onClick={() => openReport(r)}>
                <span className="row-icon"><IconInbox /></span>
                <div className="row-body">
                  <div className="row-title">{r.title}</div>
                  <div className="row-sub">{preview(r)}</div>
                </div>
                <span className="row-trail">{timeOf(r.updated_at)}<IconChevron /></span>
              </button>
            ))}
          </div>
        </Section>
      )}

      <Section title="今天">
        <div className="list">
          {today.length === 0 ? (
            <div className="row"><span className="row-icon"><IconClock /></span>
              <div className="row-body"><div className="row-title">今天没有排定的任务</div>
                <div className="row-sub">在“我的 → 定时任务”里添加</div></div></div>
          ) : today.map(({ t, at }) => (
            <div key={t.id} className="row today-row">
              <span className="today-time">{at}</span>
              <div className="row-body"><div className="row-title">{t.name}</div><div className="row-sub">{scheduleLabel(t)}</div></div>
            </div>
          ))}
        </div>
      </Section>

      {newPanel && <NewPanelSheet onClose={() => setNewPanel(false)} />}
      {editing && <TaskSheet title="编辑面板" panel initial={draftOf(editing)} onClose={() => setEditing(null)}
        onSave={async (d) => {
          const c = changesOf(draftOf(editing), d);
          if (Object.keys(c).length) { await tasks.update(editing.id, c); cards.reload(); }
        }} />}
    </Page>
  );
}

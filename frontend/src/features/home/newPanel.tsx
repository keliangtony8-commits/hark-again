// 新建面板：主页上“往主页加东西”的唯一入口（顶栏左侧 + 和栈底“创建一个新面板”胶囊都进它），= App features/home/new_panel.dart。
// v3.5.1 照 Hark：不再是白底弹层，而是主页底部输入胶囊的一种发起态模式（shell/LaunchComposer.tsx LaunchMode）——
// 整页磨砂、输入框聚焦，输入框上方一行“创建一个新面板”，占位词（前带图标）在面板示例之间轮播，发出 = newPanelPrompt 交给新对话。
// 面板由助手按描述去搭（选数据源、定刷新节奏），所以输入只问“想看什么”。原来建议问题那一格换成：
//   · 最近移除的面板（RemovedPanels.tsx 的规则，30 天内）：有才出，点一个放回主页；
//   · 示例胶囊（panelIdeas）：点一个直接交给聊天去搭；
//   · “每天早上的简报”：还没排早间简报时出现，点了打开预填好的定时任务表单。
import type { MouseEvent, ReactNode } from "react";
import { formatWhen } from "../../lib/format";
import type { HomeCard } from "../../lib/types";
import type { LaunchActions, LaunchMode } from "../../shell/LaunchComposer";
import { IconAlarm, IconBag, IconDoc, IconHistory, IconSun, IconSwap } from "../../ui/icons";
import { stagger } from "../../ui/kit";

/** 新面板的提示词，和 App new_panel.dart 同一句。 */
export const newPanelPrompt = (what: string) => `帮我在主页做一个面板：${what}`;
/** 起点（点一下交给聊天去搭；也是占位词轮播的那几句），= App panelIdeas。 */
export const panelIdeas = ["明天的天气", "美元兑人民币汇率", "我的快递到哪了", "今天的课表和作业"];
/** 示例前的图标，和 panelIdeas 一一对应（= App _ideaIcons）。 */
const IDEA_ICONS = [IconSun, IconSwap, IconBag, IconDoc];
/** 排早间简报那颗胶囊，= App briefIdeaLabel。 */
export const BRIEF_IDEA_LABEL = "每天早上的简报";
/** 输入框上方的小字，= App newPanelCaption。 */
export const NEW_PANEL_CAPTION = "创建一个新面板";

/** 输入框上方的胶囊们：最近移除（有才出，在上）→ 示例 + 早间简报（贴着小字）。点了都先收起输入框。 */
export function NewPanelExtras({ go, briefMissing, removed, onBrief, onRevive }: {
  go: LaunchActions; briefMissing: boolean; removed: HomeCard[]; onBrief: () => void; onRevive: (c: HomeCard) => void;
}) {
  const keep = (e: MouseEvent) => e.preventDefault();   // 点胶囊不让输入框先失焦（失焦 = 收起）
  return <>
    {removed.length > 0 && <>
      <div className="launch-label">最近移除 · 30 天内可放回</div>
      <div className="launch-chips">
        {removed.map((c, i) => {
          const when = c.removed_at ? formatWhen(c.removed_at) : null;
          return (
            <button key={c.id} className="glass" style={stagger(i)} onMouseDown={keep} onClick={() => go.then(() => onRevive(c))}
              aria-label={`放回「${c.title}」${when ? `，移除于 ${when}` : ""}`}>
              <IconHistory size={16} /><span className="launch-chip-text">{c.title}</span>{when && <small>{when}</small>}
            </button>
          );
        })}
      </div>
    </>}
    <div className="launch-chips">
      {panelIdeas.map((idea, i) => {
        const Icon = IDEA_ICONS[i];
        return <button key={idea} className="glass" style={stagger(removed.length + i)} onMouseDown={keep} onClick={() => go.ask(idea)}>
          <Icon size={16} /><span className="launch-chip-text">{idea}</span></button>;
      })}
      {briefMissing && <button className="glass" style={stagger(removed.length + panelIdeas.length)} onMouseDown={keep} onClick={() => go.then(onBrief)}>
        <IconAlarm size={16} /><span className="launch-chip-text">{BRIEF_IDEA_LABEL}</span></button>}
    </div>
  </>;
}

/** 主页的新建面板模式（= App newPanelMode）：+ / “创建一个新面板”把 LaunchComposer 的 mode 设成它。 */
export function newPanelMode(p: { briefMissing: boolean; removed: HomeCard[]; onBrief: () => void; onRevive: (c: HomeCard) => void }): LaunchMode {
  return {
    caption: NEW_PANEL_CAPTION,
    hints: panelIdeas,
    hintIcons: IDEA_ICONS.map((Icon, i) => <Icon key={i} size={20} />) as ReactNode[],
    wrap: newPanelPrompt,
    extras: (go) => <NewPanelExtras go={go} {...p} />,
  };
}

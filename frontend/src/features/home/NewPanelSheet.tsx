// 新面板弹层：主页上“往主页加东西”的唯一入口（顶栏左侧 + 和栈底“创建一个新面板”胶囊都开它），= App new_panel.dart。
// 面板由助手按描述去搭（选数据源、定刷新节奏），所以输入框只问“想看什么”，然后交给聊天。
// v2.78 Home 重做：起点胶囊、“每天早上的简报”（还没排时）、最近移除的面板（30 天内）都收进这里，主页只剩卡片。
import { useState } from "react";
import { formatWhen } from "../../lib/format";
import type { HomeCard } from "../../lib/types";
import { useAskInNewChat } from "../../shell/LaunchComposer";
import { IconHistory } from "../../ui/icons";
import { Sheet, stagger } from "../../ui/kit";

/** 新面板的提示词，和 App features/home/new_panel.dart 同一句。 */
export const newPanelPrompt = (what: string) => `帮我在主页做一个面板：${what}`;
/** 起点，= App new_panel.dart panelIdeas。 */
export const panelIdeas = ["明天的天气", "美元兑人民币汇率", "我的快递到哪了", "今天的课表和作业"];
/** 排早间简报那颗胶囊，= App briefIdeaLabel。 */
export const BRIEF_IDEA_LABEL = "每天早上的简报";

export default function NewPanelSheet({ onClose, briefMissing, removed, onBrief, onRevive }: {
  onClose: () => void; briefMissing: boolean; removed: HomeCard[]; onBrief: () => void; onRevive: (c: HomeCard) => void;
}) {
  const ask = useAskInNewChat();
  const [what, setWhat] = useState("");
  const go = (text: string) => { if (text.trim()) ask(newPanelPrompt(text.trim())); };
  const then = (f: () => void) => { onClose(); f(); };
  return (
    <Sheet title="新面板" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!what.trim()} onClick={() => go(what)}>开始做</button>
    </>}>
      <p className="desc">说说想在主页一眼看到什么，我来找数据、定刷新频率。</p>
      <label className="form-field">
        <span>想看什么</span>
        <textarea autoFocus rows={2} value={what} onChange={(e) => setWhat(e.target.value)} placeholder="比如：每天早上的天气和课表"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); go(what); } }} />
      </label>
      <div className="panel-idea-list">
        {panelIdeas.map((idea, i) => <button key={idea} className="panel-idea enter" style={stagger(i + 1)} onClick={() => go(idea)}>{idea}</button>)}
        {briefMissing && <button className="panel-idea enter" style={stagger(panelIdeas.length + 1)} onClick={() => then(onBrief)}>{BRIEF_IDEA_LABEL}</button>}
      </div>
      {removed.length > 0 && (
        <div className="removed-list">
          <span className="removed-label">最近移除 · 30 天内可放回</span>
          {removed.map((c) => (
            <button key={c.id} className="removed-item" onClick={() => then(() => onRevive(c))} aria-label={`放回「${c.title}」`}>
              <IconHistory size={16} /><span className="removed-title">{c.title}</span>
              <span className="removed-time">移除于 {formatWhen(c.removed_at!)}</span>
            </button>
          ))}
        </div>
      )}
    </Sheet>
  );
}

import { useState } from "react";
import { useAskInNewChat } from "../../shell/LaunchComposer";
import { Sheet } from "../../ui/kit";

/** 新面板的提示词，和 App features/home/new_panel.dart 同一句。 */
export const newPanelPrompt = (what: string) => `帮我在主页做一个面板：${what}`;
/** 还没有面板时给的几个起点，= App new_panel.dart panelIdeas。 */
export const panelIdeas = ["明天的天气", "美元兑人民币汇率", "我的快递到哪了", "今天的课表和作业"];

/** 新建面板：面板由助手按描述去搭（选数据源、定刷新节奏），所以这里只问“想看什么”，然后交给聊天。
 *  入口：主页顶栏左侧的 +、面板列表底部的“创建一个新面板”。 */
export default function NewPanelSheet({ onClose }: { onClose: () => void }) {
  const ask = useAskInNewChat();
  const [what, setWhat] = useState("");
  const go = () => { if (what.trim()) ask(newPanelPrompt(what.trim())); };
  return (
    <Sheet title="新面板" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!what.trim()} onClick={go}>开始做</button>
    </>}>
      <p className="desc">说说想在主页一眼看到什么，我来找数据、定刷新频率。</p>
      <label className="form-field">
        <span>想看什么</span>
        <textarea autoFocus rows={2} value={what} onChange={(e) => setWhat(e.target.value)} placeholder="比如：每天早上的天气和课表"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); go(); } }} />
      </label>
    </Sheet>
  );
}

// 项目首屏（v2.93 §Q 按 Hark 重做，= App ProjectHome）：项目里还没打开对话时显示，也就是“在本项目开新对话”的空白态。
// 只列本项目全部对话（置顶在前，再按更新时间），行尾状态胶囊（v2.91，没有状态写时间），点开续聊；
// 底下的输入框 = 在本项目开新对话。项目名在顶栏下的标题行，文件 / 电脑 / 规则与档案在标题行 ⋯ 里，这里都不重复。
// 宽屏时对话列表已常驻左侧，只留一行提示（CSS 切换）。
import { formatWhen } from "../../lib/format";
import type { ConversationSummary } from "../../lib/types";
import { IconChat, IconPin } from "../../ui/icons";
import StatusCapsule from "../chat/StatusCapsule";
import { projectConversations } from "./projectHomeRules";

export default function ProjectHome({ conversations, onOpen }: { conversations: ConversationSummary[]; onOpen: (id: string) => void }) {
  const all = projectConversations(conversations);
  return (
    <div className="project-home">
      <div className="section-title enter"><span>{all.length ? `对话 · ${all.length}` : "对话"}</span></div>
      {all.length === 0 ? (
        <p className="project-home-hint enter">这个项目还没有对话。在下方输入，开始第一段。</p>
      ) : (
        <>
          <p className="project-home-hint wide-only enter">从左侧选择一段对话继续，或在下方开始新的对话。</p>
          <div className="list project-home-list enter">
            {all.map((c) => (
              <button key={c.id} className="row" onClick={() => onOpen(c.id)}>
                <span className="row-icon">{c.pinned ? <IconPin /> : <IconChat />}</span>
                <div className="row-body"><div className="row-title">{c.title}</div></div>
                {c.status ? <StatusCapsule status={c.status} /> : c.updated_at && <span className="row-hint">{formatWhen(c.updated_at)}</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

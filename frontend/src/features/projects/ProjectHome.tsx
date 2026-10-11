// 项目首屏（v1.10，= App ProjectHome）：项目聊天还没打开对话时，代替通用问候。
// 字标 + 衬线名字 → 规则一行（点开规则与档案）→ 最近的对话（窄屏才有；宽屏历史栏常驻左侧，CSS 藏掉）→ 起步建议。
import { formatWhen } from "../../lib/format";
import type { ConversationSummary, Project } from "../../lib/types";
import { IconChat, IconChevron, IconPin } from "../../ui/icons";
import { stagger } from "../../ui/kit";
import { projectLine, projectRecent } from "./projectHome";

type Props = {
  project: Project; conversations: ConversationSummary[]; suggestions: string[];
  onSend: (t: string) => void; onOpen: (id: string) => void; onShowAll: () => void; onBrief: () => void;
};

export default function ProjectHome({ project: p, conversations, suggestions, onSend, onOpen, onShowAll, onBrief }: Props) {
  const recent = projectRecent(conversations);
  const n = p.conversation_count ?? 0;
  const when = formatWhen(p.last_active_at ?? p.updated_at);
  const meta = ["项目", n > 0 ? `${n} 个对话` : "", when ? `更新于 ${when}` : ""].filter(Boolean).join(" · ");
  let i = 0;
  const nth = () => stagger(i++);
  return (
    <div className="project-home">
      <div className="project-home-head enter" style={nth()}>
        <span className="project-home-mark" aria-hidden>{p.emoji}</span>
        <div className="project-home-titles">
          <span className="page-hero-label">{meta}</span>
          <h1>{p.name}</h1>
        </div>
      </div>
      <button className="project-home-line enter" style={nth()} onClick={onBrief} aria-label={`规则与档案：${projectLine(p)}`}>
        <span>{projectLine(p)}</span><IconChevron />
      </button>
      {recent.length > 0 && (
        <section className="section enter project-home-recent" style={nth()}>
          <div className="section-title"><span>最近的对话</span>
            {conversations.length > recent.length && <button className="btn btn-ghost btn-sm" onClick={onShowAll}>全部 {conversations.length} 个</button>}
          </div>
          <div className="list">
            {recent.map((c) => (
              <button key={c.id} className="row" onClick={() => onOpen(c.id)}>
                <span className="row-icon">{c.pinned ? <IconPin /> : <IconChat />}</span>
                <div className="row-body"><div className="row-title">{c.title}</div></div>
                {c.updated_at && <span className="row-hint">{formatWhen(c.updated_at)}</span>}
              </button>
            ))}
          </div>
        </section>
      )}
      {suggestions.length > 0 && (
        <section className="section enter" style={nth()}>
          <div className="section-title"><span>{recent.length ? "或者新开一段" : "从这里开始"}</span></div>
          <div className="project-home-starters">
            {suggestions.map((s) => <button key={s} className="project-starter" onClick={() => onSend(s)}>{s}</button>)}
          </div>
        </section>
      )}
    </div>
  );
}

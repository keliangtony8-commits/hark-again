// 项目首屏（v1.10，= App ProjectHome）：项目聊天还没打开对话时，代替通用问候。
// 字标 + 衬线名字 → 规则一行（点开规则与档案）→ 最近的对话（窄屏才有；宽屏历史栏常驻左侧，CSS 藏掉）
// → 文件（v1.11：最近改过的 3 个，点开就看；全部/管理 → 文件面板；空文件夹一行上传入口）
// → 电脑（v1.25：features/computer/ComputerSection）→ 起步建议。
import { fileUrl } from "../../lib/api";
import { extOf } from "../../lib/files";
import { formatWhen } from "../../lib/format";
import type { ConversationSummary, Project, ProjectFile } from "../../lib/types";
import { IconChat, IconChevron, IconPin, IconUpload } from "../../ui/icons";
import { stagger } from "../../ui/kit";
import ComputerSection from "../computer/ComputerSection";
import { PROJECT_FILES_MAX, projectFileLine, projectFilePath, projectLine, projectRecent, projectRecentFiles } from "./projectHome";

type Props = {
  project: Project; conversations: ConversationSummary[]; suggestions: string[];
  onSend: (t: string) => void; onOpen: (id: string) => void; onShowAll: () => void; onBrief: () => void;
  /** null = 还在加载/失败 → 不画文件一节。 */
  files: ProjectFile[] | null; onFiles: () => void;
};

export default function ProjectHome({ project: p, conversations, suggestions, onSend, onOpen, onShowAll, onBrief, files, onFiles }: Props) {
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
      {files && (
        <section className="section enter" style={nth()}>
          <div className="section-title"><span>文件</span>
            {files.length > 0 && <button className="btn btn-ghost btn-sm" onClick={onFiles}>{files.length > PROJECT_FILES_MAX ? `全部 ${files.length} 个` : "管理"}</button>}
          </div>
          <div className="list">
            {files.length === 0 ? (
              <button className="row" onClick={onFiles}>
                <span className="row-icon"><IconUpload /></span>
                <div className="row-body"><div className="row-title">放点资料进来</div><div className="row-sub">上传后，在这个项目里聊天我都能直接读</div></div>
              </button>
            ) : projectRecentFiles(files).map((f) => (
              <a key={f.path} className="row" href={fileUrl(projectFilePath(p.id, f))} target="_blank" rel="noreferrer">
                <span className="row-icon file-ext">{extOf(f.name)}</span>
                <div className="row-body"><div className="row-title">{f.name}</div><div className="row-sub">{projectFileLine(f)}</div></div>
                {f.modified ? <span className="row-hint">{formatWhen(new Date(f.modified * 1000).toISOString())}</span> : null}
              </a>
            ))}
          </div>
        </section>
      )}
      <ComputerSection ws={p.id} enter={i++} />{/* v1.25：项目沙盒在不在跑、在忙什么；加载中/失败不画 */}
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

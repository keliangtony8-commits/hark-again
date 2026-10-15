// v2.95 项目 = 一段对话：项目页的两件小东西（= App features/projects/project_switcher.dart），规格见 docs/devlog.md「2026-10-15 v2.95」。
// ProjectSwitcher：项目页左上 ≡ 打开的“项目切换”栏——列出所有项目（按最近活动，行尾项目状态胶囊，当前项目高亮），
//   点一个就换到那个项目的聊天。和主聊天“≡ 打开历史对话”同构：抽屉 = 同层级切换，左上钮在抽屉开着时转成 + = 新建项目。
//   窄屏是抽屉（从药丸那一行下面滑出，左上钮不被盖住才能 morph，CSS 在 chat.css .chat.project .convs）；宽屏常驻左侧，标题旁自带 +。
//   外形复用历史面板的 .convs / .conv-item（同一个组件位，CSS 决定形态）。
// ProjectPill：顶栏下那一行（chat-caption）在项目里写的东西——项目名药丸（emoji 名字 ▾），进页时落下一次（float-in），
//   点它 = 项目菜单（文件 / 电脑 / 规则与档案 / 编辑 / 删除，和列表行 ⋯ 同一份）。主聊天那一行仍写对话标题。
import type { Project } from "../../lib/types";
import { IconChevronDown, IconComputer, IconDoc, IconEdit, IconFile, IconPlus, IconTrash } from "../../ui/icons";
import { Menu } from "../../ui/kit";
import StatusCapsule from "../chat/StatusCapsule";
import { byActivity } from "./projectHomeRules";

type SwitcherProps = {
  projects: Project[];
  loading: boolean;
  currentId: string;
  onPick: (p: Project) => void;
  onNew: () => void;
};

export default function ProjectSwitcher({ projects, loading, currentId, onPick, onNew }: SwitcherProps) {
  const list = byActivity(projects);
  return (
    <aside className="convs glass-drawer project-switcher" aria-label="项目">
      <div className="convs-head">
        <span className="convs-title">项目</span>
        {/* 窄屏抽屉里新建 = 左上那颗转成 + 的钮，这里隐藏（chat.css）；宽屏常驻栏靠它 */}
        <button className="icon-btn" onClick={onNew} aria-label="新建项目" title="新建项目"><IconPlus /></button>
      </div>
      <nav className="conv-list">
        {loading && list.length === 0
          ? [0, 1, 2].map((i) => <div key={i} className="skeleton switcher-skel" />)
          : list.map((p, i) => {
              const current = p.id === currentId;
              return (
                <button key={p.id} className={`conv-item switcher-row ${current ? "active" : ""}`} onClick={() => onPick(p)}
                  aria-current={current ? "page" : undefined} style={{ animationDelay: `calc(var(--stagger) * ${Math.min(i, 8)})` }}>
                  <span className="switcher-emoji" aria-hidden>{p.emoji}</span>
                  <span className="conv-title">{p.name}</span>
                  {p.status && <StatusCapsule status={p.status} />}
                </button>
              );
            })}
      </nav>
    </aside>
  );
}

type PillProps = {
  project: Project | null;
  onFiles: () => void; onComputer: () => void; onBrief: () => void; onEdit: () => void; onDelete: () => void;
};

/** 项目页顶栏下那一行：项目名药丸，点开项目菜单。 */
export function ProjectPill({ project, onFiles, onComputer, onBrief, onEdit, onDelete }: PillProps) {
  const label = project ? `${project.emoji} ${project.name}` : "项目";
  return (
    <div className="project-pill-slot">
      <Menu label={`项目菜单：${label}`} align="left" triggerClass="project-pill glass raised"
        trigger={<><span className="project-pill-name">{label}</span><IconChevronDown size={14} /></>}
        items={[
          { label: "项目文件", icon: <IconFile />, onSelect: onFiles },
          { label: "电脑", icon: <IconComputer size={16} />, onSelect: onComputer },
          { label: "规则与档案", icon: <IconDoc size={16} />, onSelect: onBrief },
          { label: "编辑项目", icon: <IconEdit />, onSelect: onEdit },
          { label: "删除项目", icon: <IconTrash />, danger: true, onSelect: onDelete },
        ]} />
    </div>
  );
}

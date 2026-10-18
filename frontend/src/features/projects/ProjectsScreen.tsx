import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import type { Project } from "../../lib/types";
import { ShellLead } from "../../shell/ShellLead";
import { confirmDialog } from "../../ui/dialog";
import { IconComputer, IconDoc, IconEdit, IconFile, IconFolder, IconPlus, IconTrash } from "../../ui/icons";
import { Hint, Page, Sheet, stagger, type MenuItem } from "../../ui/kit";
import { useFocusMenu } from "../../ui/FocusMenu";
import MenuPlus from "../chat/MenuPlus";
import { STATUS_LABEL } from "../chat/StatusCapsule";
import ProjectFiles from "./ProjectFiles";
import { DIR_ENTRY } from "./directory";
import { byActivity, projectIsCurrent } from "./projectHomeRules";
import ProjectBrief from "./ProjectBrief";
import ProjectForm from "./ProjectForm";
import "./projects.css";


/**
 * 项目目录（v3.5.2 照 Hark 真机截图：项目标签 = 一个目录，= App projects_screen）：顶栏下直接一行行项目名——裸字（--fs-dir 24，单行省略，按最近活动排序），
 * 没有页大标题、卡片底、emoji、⋯；状态（= 那段对话的状态，服务器 status）是行尾一个小字。不是“当前”的项目变灰（projectIsCurrent）。
 * 菜单 = 右键 / 长按（含键盘菜单键、Shift+F10）弹原地聚焦菜单（ui/FocusMenu，和消息菜单同一套）；同样的操作项目内顶栏下的项目名里也有。
 * 点一行 = 进那个项目的那段对话（v2.95 项目 = 一段对话），带 DIR_ENTRY 标记：项目内 ☰ 据此“退一页”回到这里（= 浏览器返回）。
 * 顶栏左侧 + = 新建；它和项目内的 ☰（回目录）是同一颗钮（MenuPlus 记着上一颗的形状，进出项目时原地 morph）。
 */
export default function ProjectsScreen() {
  const projects = useResource<Project>("/api/projects");
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [briefOf, setBriefOf] = useState<Project | null>(null);
  const [filesOf, setFilesOf] = useState<Project | null>(null);
  const list = byActivity(projects.items);

  const remove = async (p: Project) => {
    if (!(await confirmDialog({ title: `删除“${p.name}”？`, text: "项目里的对话、文件和档案会一起删除，不能恢复。" }))) return false;
    await projects.remove(p.id);
    return true;
  };

  return (
    <Page>
      <ShellLead><MenuPlus plus label="新建项目" onClick={() => setCreating(true)} /></ShellLead>
      {projects.loading ? (
        <div className="project-list" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="skeleton project-skel" />)}</div>
      ) : list.length === 0 ? (
        <div className="fade-in">
          <Hint icon={<IconFolder size={26} />} title="还没有项目"
            text="把需要很多步、很多天的事放进项目：备考、求职、旅行、课程设计。每个项目有自己的一段对话、文件和规则。"
            action={<button className="pill primary project-new" onClick={() => setCreating(true)}><IconPlus size={18} />新建项目</button>} />
        </div>
      ) : (
        <div className="project-list">
          {list.map((p, i) => (
            <ProjectRow key={p.id} project={p} index={i} quiet={!projectIsCurrent(i, p)} items={() => [
              { label: "项目文件", icon: <IconFile />, onSelect: () => setFilesOf(p) },
              { label: "电脑", icon: <IconComputer size={16} />, onSelect: () => nav(`/projects/${p.id}/computer`) },
              { label: "规则与档案", icon: <IconDoc size={16} />, onSelect: () => setBriefOf(p) },
              { label: "编辑项目", icon: <IconEdit />, onSelect: () => setEditing(p) },
              { label: "删除项目", icon: <IconTrash />, danger: true, onSelect: () => { void remove(p); } },
            ]} />
          ))}
        </div>
      )}
      {creating && (
        <Sheet title="新建项目" onClose={() => setCreating(false)}>
          <ProjectForm submitLabel="创建" onCancel={() => setCreating(false)}
            onSubmit={async (v) => { const p = await projects.create(v); setCreating(false); if (p?.id) nav(`/projects/${p.id}`, { state: DIR_ENTRY }); }} />
        </Sheet>
      )}
      {editing && (
        <Sheet title="编辑项目" onClose={() => setEditing(null)}>
          <ProjectForm initial={editing} submitLabel="保存" onCancel={() => setEditing(null)}
            onSubmit={async (v) => { await projects.update(editing.id, v); setEditing(null); }}
            onDelete={async () => { if (await remove(editing)) setEditing(null); }} />
        </Sheet>
      )}
      {briefOf && <ProjectBrief project={briefOf} onSaved={() => { void projects.reload(); }} onClose={() => setBriefOf(null)} />}
      {filesOf && <ProjectFiles projectId={filesOf.id} onClose={() => setFilesOf(null)} />}
    </Page>
  );
}

const LONG_PRESS_MS = 500; // = Flutter 长按时长（App _ProjectRow 的 onLongPress）

/** 目录的一行（= App _ProjectRow）：点 = 进项目；右键 / 长按 = 原地聚焦菜单。
 *  安卓 Chrome 长按、桌面右键、键盘菜单键都会发 contextmenu；iOS Safari 长按不发，用触摸计时补上，触发后吞掉随之而来的那次点按。 */
function ProjectRow({ project: p, index, quiet, items }: { project: Project; index: number; quiet: boolean; items: () => MenuItem[] }) {
  const link = useRef<HTMLAnchorElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const fired = useRef(false);
  const menu = useFocusMenu(items, { label: `${p.name}的菜单` });
  const cancel = () => { window.clearTimeout(timer.current); timer.current = undefined; };
  return (
    <div className={`project-row enter ${quiet ? "is-quiet" : ""}`} style={stagger(index)}>
      <Link to={`/projects/${p.id}`} state={DIR_ENTRY} ref={link} className="project-row-link" aria-haspopup="menu"
        onContextMenu={(e) => { e.preventDefault(); cancel(); fired.current = true; menu.open(link.current); }}
        onTouchStart={() => { fired.current = false; cancel(); timer.current = window.setTimeout(() => { timer.current = undefined; fired.current = true; menu.open(link.current); }, LONG_PRESS_MS); }}
        onTouchMove={cancel} onTouchEnd={cancel} onTouchCancel={cancel}
        onClick={(e) => { if (fired.current) { e.preventDefault(); fired.current = false; } }}>
        <span className="project-row-name">{p.name}</span>
        {p.status && <span className="project-row-status" key={p.status}>{STATUS_LABEL[p.status]}</span>}
      </Link>
      {menu.node}
    </div>
  );
}

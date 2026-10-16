import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import type { Project } from "../../lib/types";
import { ShellLead } from "../../shell/ShellLead";
import { confirmDialog } from "../../ui/dialog";
import { IconComputer, IconDoc, IconEdit, IconFile, IconFolder, IconMore, IconPlus, IconTrash } from "../../ui/icons";
import { Hint, Menu, Page, Sheet, stagger } from "../../ui/kit";
import MenuPlus from "../chat/MenuPlus";
import StatusCapsule from "../chat/StatusCapsule";
import ProjectFiles from "./ProjectFiles";
import { byActivity, projectIsCurrent } from "./projectHomeRules";
import ProjectBrief from "./ProjectBrief";
import ProjectForm from "./ProjectForm";
import "./projects.css";


/**
 * 项目列表（v3.2.2 按 Hark 真机截图，= App projects_screen）：一项 = 占满整行的大字项目名（可折行，按最近活动排序）
 * + 下一行状态胶囊（= 那段对话的状态，服务器 status）；没有页头小标签、没有 emoji。⋯ 菜单在胶囊那一行的右端（电脑没有长按），
 * 不占名字的宽度。不是“当前”的项目变灰（projectIsCurrent）。没有卡片网格、没有输入框。
 * 点一行 = 进那个项目的那段对话（v2.95 项目 = 一段对话）。
 * 顶栏左侧 + = 新建；它和项目页的 ≡（项目切换）是同一颗钮（MenuPlus 记着上一颗的形状，进出项目时原地 morph）。
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
      <div className="project-hero" aria-hidden />
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
            <div key={p.id} className={`project-row enter ${projectIsCurrent(i, p) ? "" : "is-quiet"}`} style={stagger(i)}>
              <Link to={`/projects/${p.id}`} className="project-row-link">
                <span className="project-row-name">{p.name}</span>
                <span className="project-row-status">{p.status && <StatusCapsule status={p.status} />}</span>
              </Link>
              <Menu label={`${p.name}的菜单`} trigger={<IconMore />} items={[
                { label: "项目文件", icon: <IconFile />, onSelect: () => setFilesOf(p) },
                { label: "电脑", icon: <IconComputer size={16} />, onSelect: () => nav(`/projects/${p.id}/computer`) },
                { label: "规则与档案", icon: <IconDoc size={16} />, onSelect: () => setBriefOf(p) },
                { label: "编辑项目", icon: <IconEdit />, onSelect: () => setEditing(p) },
                { label: "删除项目", icon: <IconTrash />, danger: true, onSelect: () => { void remove(p); } },
              ]} />
            </div>
          ))}
        </div>
      )}
      {creating && (
        <Sheet title="新建项目" onClose={() => setCreating(false)}>
          <ProjectForm submitLabel="创建" onCancel={() => setCreating(false)}
            onSubmit={async (v) => { const p = await projects.create(v); setCreating(false); if (p?.id) nav(`/projects/${p.id}`); }} />
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

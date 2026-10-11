import { useState } from "react";
import { Link } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { formatWhen } from "../../lib/format";
import { briefLine } from "../../lib/projects";
import type { Project } from "../../lib/types";
import LaunchComposer from "../../shell/LaunchComposer";
import { ShellLead } from "../../shell/ShellLead";
import { confirmDialog } from "../../ui/dialog";
import { IconDoc, IconEdit, IconFolder, IconMore, IconPlus, IconTrash } from "../../ui/icons";
import { Hint, Menu, Page, Sheet, stagger } from "../../ui/kit";
import ProjectBrief from "./ProjectBrief";
import ProjectForm from "./ProjectForm";
import "./projects.css";

const activeAt = (p: Project) => p.last_active_at ?? p.updated_at;

/** 最近有动静的排前面（= App byActivity）。 */
export const byActivity = (list: Project[]) => [...list].sort((a, b) => (Date.parse(activeAt(b) ?? "") || 0) - (Date.parse(activeAt(a) ?? "") || 0));

/** 一行活动摘要：“3 个对话 · 更新于 今天 09:12”。旧服务器没有统计字段时退回项目自身的更新时间。 */
const activity = (p: Project) => {
  const n = p.conversation_count ?? 0;
  return `${n > 0 ? `${n} 个对话` : "还没有对话"} · 更新于 ${formatWhen(activeAt(p))}`;
};

/** 页头小标签：“3 个项目 · 最近 今天 09:12”；加载中为空（行高照占）。 */
const summary = (loading: boolean, list: Project[]) =>
  loading ? "" : list.length === 0 ? "长期的事放这里" : `${list.length} 个项目 · 最近 ${formatWhen(activeAt(list[0]))}`;

/**
 * 项目列表（v0.73，= App projects_screen）：页头小标签 + 衬线“项目”，下面是矮玻璃卡网格（按最近活动排序）。
 * 加载中 = 同高同圆角的骨架卡；卡片右上 ⋯ = 编辑 / 规则与档案 / 删除。顶栏左侧 + = 新建，底部同一个输入胶囊。
 */
export default function ProjectsScreen() {
  const projects = useResource<Project>("/api/projects");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [briefOf, setBriefOf] = useState<Project | null>(null);
  const list = byActivity(projects.items);
  const label = summary(projects.loading, list);

  const remove = async (p: Project) => {
    if (!(await confirmDialog({ title: `删除“${p.name}”？`, text: "项目里的对话、文件和档案会一起删除，不能恢复。" }))) return false;
    await projects.remove(p.id);
    return true;
  };

  return (
    <Page footer={<LaunchComposer />}>
      <ShellLead>
        <button className="glass-btn glass" onClick={() => setCreating(true)} aria-label="新建项目" title="新建项目"><IconPlus /></button>
      </ShellLead>
      <div className="page-hero">
        <span key={label} className="page-hero-label enter">{label}</span>
        <h1>项目</h1>
      </div>
      {projects.loading ? (
        <div className="project-grid" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="skeleton project-skel" />)}</div>
      ) : list.length === 0 ? (
        <div className="glass-card fade-in">
          <Hint icon={<IconFolder size={26} />} title="还没有项目"
            text="把需要很多步、很多天的事放进项目：备考、求职、旅行、课程设计。每个项目有自己的对话和规则。"
            action={<button className="pill primary project-new" onClick={() => setCreating(true)}><IconPlus size={18} />新建项目</button>} />
        </div>
      ) : (
        <div className="project-grid">
          {list.map((p, i) => (
            <div key={p.id} className="project-card enter" style={stagger(i)}>
              <Link to={`/projects/${p.id}`} className="project-card-link">
                <div className="project-card-head">
                  <span className="project-emoji">{p.emoji}</span>
                  <span className="project-name">{p.name}</span>
                </div>
                <div className="project-rules">{p.rules.trim().split("\n")[0] || briefLine(p.brief) || "还没有规则和档案"}</div>
                <div className="project-meta">{activity(p)}</div>
              </Link>
              <Menu trigger={<IconMore />} items={[
                { label: "编辑", icon: <IconEdit />, onSelect: () => setEditing(p) },
                { label: "规则与档案", icon: <IconDoc size={16} />, onSelect: () => setBriefOf(p) },
                { label: "删除项目", icon: <IconTrash />, danger: true, onSelect: () => { void remove(p); } },
              ]} />
            </div>
          ))}
        </div>
      )}
      {creating && (
        <Sheet title="新建项目" onClose={() => setCreating(false)}>
          <ProjectForm submitLabel="创建" onCancel={() => setCreating(false)}
            onSubmit={async (v) => { await projects.create(v); setCreating(false); }} />
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
    </Page>
  );
}

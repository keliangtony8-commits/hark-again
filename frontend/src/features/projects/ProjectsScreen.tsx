import { useState } from "react";
import { Link } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { formatWhen } from "../../lib/format";
import { briefLine } from "../../lib/projects";
import type { Project } from "../../lib/types";
import LaunchComposer from "../../shell/LaunchComposer";
import { ShellLead } from "../../shell/ShellLead";
import { IconFolder, IconPlus } from "../../ui/icons";
import { Hint, Page, Sheet, Skeleton } from "../../ui/kit";
import ProjectForm from "./ProjectForm";
import "./projects.css";

/** 一行活动摘要：“3 个对话 · 更新于 今天 09:12”。旧服务器没有统计字段时退回项目自身的更新时间。 */
const activity = (p: Project) => {
  const n = p.conversation_count ?? 0;
  const at = p.last_active_at ?? p.updated_at;
  return `${n > 0 ? `${n} 个对话` : "还没有对话"} · 更新于 ${formatWhen(at)}`;
};

/** 项目列表（设计 v2）：玻璃卡网格（图标 + 名字 + 规则首行 + 活动摘要），顶栏左侧 + = 新建，底部同一个输入胶囊。 */
export default function ProjectsScreen() {
  const projects = useResource<Project>("/api/projects");
  const [creating, setCreating] = useState(false);

  return (
    <Page footer={<LaunchComposer />}>
      <ShellLead>
        <button className="glass-btn glass" onClick={() => setCreating(true)} aria-label="新建项目" title="新建项目"><IconPlus /></button>
      </ShellLead>
      <h1 className="page-title">项目</h1>
      {projects.loading ? <Skeleton /> : projects.items.length === 0 ? (
        <div className="glass-card">
          <Hint icon={<IconFolder size={26} />} title="还没有项目"
            text="把需要很多步、很多天的事放进项目：备考、求职、旅行、课程设计。每个项目有自己的对话和规则。"
            action={<button className="pill primary project-new" onClick={() => setCreating(true)}><IconPlus size={18} />新建项目</button>} />
        </div>
      ) : (
        <div className="project-grid">
          {projects.items.map((p, i) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="project-card" style={{ animationDelay: `calc(var(--stagger) * ${i})` }}>
              <div className="project-card-head">
                <span className="row-icon">{p.emoji}</span>
                <span className="project-name">{p.name}</span>
              </div>
              <div className="project-rules">{p.rules.trim().split("\n")[0] || briefLine(p.brief) || "还没有规则和档案"}</div>
              <div className="project-meta">{activity(p)}</div>
            </Link>
          ))}
        </div>
      )}
      {creating && (
        <Sheet title="新建项目" onClose={() => setCreating(false)}>
          <ProjectForm submitLabel="创建" onCancel={() => setCreating(false)}
            onSubmit={async (v) => { await projects.create(v); setCreating(false); }} />
        </Sheet>
      )}
    </Page>
  );
}

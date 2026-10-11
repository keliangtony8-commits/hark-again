import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import type { Project } from "../../lib/types";
import { IconBack, IconDoc, IconFile, IconSettings } from "../../ui/icons";
import { Sheet } from "../../ui/kit";
import ChatScreen from "../chat/ChatScreen";
import ProjectBrief from "./ProjectBrief";
import ProjectFiles from "./ProjectFiles";
import ProjectForm from "./ProjectForm";
import { confirmDialog } from "../../ui/dialog";

/** 项目详情 = 带项目上下文的聊天屏（含文件与沙盒工具）+ 文件面板 + 项目档案 + 项目设置（名称/图标/规则）。 */
export default function ProjectScreen() {
  const { pid = "" } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showBrief, setShowBrief] = useState(false);

  useEffect(() => { http.get<Project>(`/api/projects/${pid}`).then(setProject).catch(() => nav("/projects")); }, [pid, nav]);
  if (!project) return null;

  return (
    <>
      <ChatScreen
        key={pid}
        projectId={pid}
        listTitle={`${project.emoji} ${project.name}`}
        headerTitle={project.name}
        emptyGreeting={project.rules.trim() ? "项目规则已生效，直接开始吧。" : "在这个项目里，想先做什么？"}
        leading={<button className="icon-btn" onClick={() => nav("/projects")} aria-label="返回"><IconBack /></button>}
        trailing={<>
          <button className="icon-btn" onClick={() => setShowFiles(true)} aria-label="项目文件"><IconFile /></button>
          <button className="icon-btn" onClick={() => setShowBrief(true)} aria-label="项目档案"><IconDoc /></button>
          <button className="icon-btn" onClick={() => setEditing(true)} aria-label="项目设置"><IconSettings /></button>
        </>}
      />
      {showFiles && <ProjectFiles projectId={pid} onClose={() => setShowFiles(false)} />}
      {showBrief && <ProjectBrief project={project} onSaved={setProject} onClose={() => setShowBrief(false)} />}
      {editing && (
        <Sheet title="项目设置" onClose={() => setEditing(false)}>
          <ProjectForm initial={project} submitLabel="保存" onCancel={() => setEditing(false)}
            onSubmit={async (v) => { setProject(await http.patch<Project>(`/api/projects/${pid}`, v)); setEditing(false); }}
            onDelete={async () => { if (await confirmDialog({ title: "删除这个项目？", text: "项目里的对话和档案会一起删除。" })) { await http.del(`/api/projects/${pid}`); nav("/projects"); } }} />
        </Sheet>
      )}
    </>
  );
}

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import type { Project } from "../../lib/types";
import { IconBack, IconDoc, IconEdit, IconFile, IconMore, IconTrash } from "../../ui/icons";
import { Menu, Sheet } from "../../ui/kit";
import ChatScreen from "../chat/ChatScreen";
import ProjectBrief from "./ProjectBrief";
import ProjectFiles from "./ProjectFiles";
import ProjectForm from "./ProjectForm";
import ProjectHome from "./ProjectHome";
import { confirmDialog } from "../../ui/dialog";

const SUGGESTIONS = ["总结一下这个项目现在的进度", "帮我列个下一步计划"];

/** 项目详情 = 带项目上下文的聊天屏（含文件与沙盒工具）+ 文件面板 + 项目档案 + 项目设置（名称/图标/规则）。
 *  v1.10：标题栏右侧只留一颗 ⋯（文件 / 规则与档案 / 设置 / 删除，= App showProjectMenu）；没打开对话时是项目首屏 ProjectHome。 */
export default function ProjectScreen() {
  const { pid = "" } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showBrief, setShowBrief] = useState(false);

  useEffect(() => { http.get<Project>(`/api/projects/${pid}`).then(setProject).catch(() => nav("/projects")); }, [pid, nav]);
  if (!project) return null;
  const remove = async () => {
    if (await confirmDialog({ title: `删除“${project.name}”？`, text: "项目里的对话、文件和档案会一起删除，不能恢复。" })) {
      await http.del(`/api/projects/${pid}`); nav("/projects");
    }
  };

  return (
    <>
      <ChatScreen
        key={pid}
        projectId={pid}
        listTitle={`${project.emoji} ${project.name}`}
        headerTitle={project.name}
        empty={(c) => <ProjectHome project={project} conversations={c.conversations} suggestions={SUGGESTIONS}
          onSend={c.send} onOpen={c.open} onShowAll={c.showAll} onBrief={() => setShowBrief(true)} />}
        leading={<button className="icon-btn" onClick={() => nav("/projects")} aria-label="返回"><IconBack /></button>}
        trailing={<Menu label="项目菜单" trigger={<IconMore />} items={[
          { label: "项目文件", icon: <IconFile />, onSelect: () => setShowFiles(true) },
          { label: "规则与档案", icon: <IconDoc size={16} />, onSelect: () => setShowBrief(true) },
          { label: "编辑项目", icon: <IconEdit />, onSelect: () => setEditing(true) },
          { label: "删除项目", icon: <IconTrash />, danger: true, onSelect: () => { void remove(); } },
        ]} />}
      />
      {showFiles && <ProjectFiles projectId={pid} onClose={() => setShowFiles(false)} />}
      {showBrief && <ProjectBrief project={project} onSaved={setProject} onClose={() => setShowBrief(false)} />}
      {editing && (
        <Sheet title="项目设置" onClose={() => setEditing(false)}>
          <ProjectForm initial={project} submitLabel="保存" onCancel={() => setEditing(false)}
            onSubmit={async (v) => { setProject(await http.patch<Project>(`/api/projects/${pid}`, v)); setEditing(false); }}
            onDelete={() => { void remove(); }} />
        </Sheet>
      )}
    </>
  );
}

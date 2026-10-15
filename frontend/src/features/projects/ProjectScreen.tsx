import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import type { Project } from "../../lib/types";
import { IconBack, IconComputer, IconDoc, IconEdit, IconFile, IconMore, IconTrash } from "../../ui/icons";
import { Menu, Sheet } from "../../ui/kit";
import ChatScreen from "../chat/ChatScreen";
import ProjectBrief from "./ProjectBrief";
import ProjectFiles from "./ProjectFiles";
import ProjectForm from "./ProjectForm";
import ProjectHome from "./ProjectHome";
import { confirmDialog } from "../../ui/dialog";

/** 项目详情（v2.93 §Q）= 带项目上下文的聊天屏，仍在一级外壳下（顶栏不让位）。
 *  标题行：‹ 返回项目列表 + 项目名 + ⋯（文件 / 电脑 / 规则与档案 / 编辑 / 删除，= App showProjectMenu）；
 *  窄屏左上 ≡ = 本项目对话列表（ChatScreen）。没打开对话时是项目首屏 ProjectHome（本项目对话列表）。 */
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
        headerTitle={`${project.emoji} ${project.name}`}
        empty={(c) => <ProjectHome conversations={c.conversations} onOpen={c.open} />}
        back={<button className="icon-btn" onClick={() => nav("/projects")} aria-label="返回项目列表" title="返回项目列表"><IconBack /></button>}
        trailing={<Menu label="项目菜单" trigger={<IconMore size={20} />} items={[
          { label: "项目文件", icon: <IconFile />, onSelect: () => setShowFiles(true) },
          { label: "电脑", icon: <IconComputer size={16} />, onSelect: () => nav(`/projects/${pid}/computer`) },
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

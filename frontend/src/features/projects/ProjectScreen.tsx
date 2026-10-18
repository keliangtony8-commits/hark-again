import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import { useResource } from "../../hooks/useResource";
import type { Project } from "../../lib/types";
import { IconComputer, IconDoc, IconEdit, IconFile, IconTrash } from "../../ui/icons";
import { Menu, Sheet } from "../../ui/kit";
import ChatScreen from "../chat/ChatScreen";
import ProjectBrief from "./ProjectBrief";
import ProjectFiles from "./ProjectFiles";
import ProjectForm from "./ProjectForm";
import { cameFromDirectory } from "./directory";
import { confirmDialog } from "../../ui/dialog";
import "./projects.css";

/** 项目详情（v2.95 项目 = 一段对话，= App ProjectDetailScreen）= 那一段对话的聊天屏，仍在一级外壳下（顶栏不让位）。
 *  顶栏下一行纯文字项目名（ProjectTitle，点开 文件 / 电脑 / 规则与档案 / 编辑 / 删除，同目录行的菜单），下面直接是聊天。
 *  v3.5.2 照 Hark：左上 ☰ = 回项目目录（路由内导航：从目录进来就退一页 = 浏览器返回，否则去 /projects），不再有项目切换栏 / 药丸。 */
export default function ProjectScreen() {
  const { pid = "" } = useParams();
  const nav = useNavigate();
  const location = useLocation();
  // 进页时记下是不是从目录来的（路由状态之后可能被聊天屏清掉）；换到别的项目时按那次跳转重新记
  const [dirOf, setDirOf] = useState<string | null>(() => (cameFromDirectory(location.state) ? pid : null));
  const [seen, setSeen] = useState(pid);
  if (seen !== pid) { setSeen(pid); setDirOf(cameFromDirectory(location.state) ? pid : null); }
  const fromDir = dirOf === pid;
  const projects = useResource<Project>("/api/projects");
  const [loaded, setLoaded] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showBrief, setShowBrief] = useState(false);

  useEffect(() => { http.get<Project>(`/api/projects/${pid}`).then(setLoaded).catch(() => nav("/projects")); }, [pid, nav]);
  // 详情还没拉到时先用列表里那条，名字不闪
  const project = loaded?.id === pid ? loaded : projects.items.find((p) => p.id === pid) ?? null;
  if (!project) return null;

  const toDirectory = () => (fromDir ? nav(-1) : nav("/projects"));
  const saved = (p: Project) => { setLoaded(p); void projects.reload().catch(() => {}); };
  const remove = async () => {
    if (await confirmDialog({ title: `删除“${project.name}”？`, text: "项目的对话、文件和档案会一起删除，不能恢复。" })) {
      await http.del(`/api/projects/${pid}`); nav("/projects");
    }
  };

  return (
    <>
      <ChatScreen
        key={pid}
        projectId={pid}
        onBack={toDirectory}
        caption={<ProjectTitle project={project}
          onFiles={() => setShowFiles(true)}
          onComputer={() => nav(`/projects/${pid}/computer`)}
          onBrief={() => setShowBrief(true)}
          onEdit={() => setEditing(true)}
          onDelete={() => { void remove(); }} />}
      />
      {showFiles && <ProjectFiles projectId={pid} onClose={() => setShowFiles(false)} />}
      {showBrief && <ProjectBrief project={project} onSaved={setLoaded} onClose={() => setShowBrief(false)} />}
      {editing && (
        <Sheet title="项目设置" onClose={() => setEditing(false)}>
          <ProjectForm initial={project} submitLabel="保存" onCancel={() => setEditing(false)}
            onSubmit={async (v) => { saved(await http.patch<Project>(`/api/projects/${pid}`, v)); setEditing(false); }}
            onDelete={() => { void remove(); }} />
        </Sheet>
      )}
    </>
  );
}

type TitleProps = {
  project: Project;
  onFiles: () => void; onComputer: () => void; onBrief: () => void; onEdit: () => void; onDelete: () => void;
};

/** 项目内顶栏下那一行（v3.5.2，= App ProjectTitle）：纯文字项目名（同主聊天的对话标题小字，无底、无 ⌄、无 emoji），点开项目菜单。 */
function ProjectTitle({ project, onFiles, onComputer, onBrief, onEdit, onDelete }: TitleProps) {
  return (
    <div className="chat-top-name">
      <Menu label={`项目菜单：${project.name}`} align="left" triggerClass="project-title" trigger={project.name}
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

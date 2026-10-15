import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../lib/api";
import { useResource } from "../../hooks/useResource";
import type { Project } from "../../lib/types";
import { Sheet } from "../../ui/kit";
import ChatScreen from "../chat/ChatScreen";
import ProjectBrief from "./ProjectBrief";
import ProjectFiles from "./ProjectFiles";
import ProjectForm from "./ProjectForm";
import ProjectSwitcher, { ProjectPill } from "./ProjectSwitcher";
import { confirmDialog } from "../../ui/dialog";
import "./projects.css";

/** 项目详情（v2.95 项目 = 一段对话，= App ProjectDetailScreen）= 那一段对话的聊天屏，仍在一级外壳下（顶栏不让位）。
 *  顶栏下一枚项目名药丸（ProjectPill，点开 文件 / 电脑 / 规则与档案 / 编辑 / 删除，同列表行 ⋯），下面直接是聊天。
 *  左上 ≡ = 项目切换栏（ProjectSwitcher；开着时转成 + = 新建项目），宽屏常驻左侧。回项目列表 = 再点顶栏“项目”。 */
export default function ProjectScreen() {
  const { pid = "" } = useParams();
  const nav = useNavigate();
  const projects = useResource<Project>("/api/projects");
  const [loaded, setLoaded] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showBrief, setShowBrief] = useState(false);

  useEffect(() => { http.get<Project>(`/api/projects/${pid}`).then(setLoaded).catch(() => nav("/projects")); }, [pid, nav]);
  // 抽屉里换项目：新项目还没拉到时先用列表里那条，药丸不闪旧名字
  const project = loaded?.id === pid ? loaded : projects.items.find((p) => p.id === pid) ?? null;
  if (!project) return null;

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
        caption={<ProjectPill project={project}
          onFiles={() => setShowFiles(true)}
          onComputer={() => nav(`/projects/${pid}/computer`)}
          onBrief={() => setShowBrief(true)}
          onEdit={() => setEditing(true)}
          onDelete={() => { void remove(); }} />}
        switcher={{
          render: (close) => <ProjectSwitcher projects={projects.items} loading={projects.loading} currentId={pid}
            onPick={(p) => { close(); if (p.id !== pid) nav(`/projects/${p.id}`); }}
            onNew={() => { close(); setCreating(true); }} />,
          onOpen: () => { void projects.reload().catch(() => {}); },
          onNew: () => setCreating(true),
        }}
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
      {creating && (
        <Sheet title="新建项目" onClose={() => setCreating(false)}>
          <ProjectForm submitLabel="创建" onCancel={() => setCreating(false)}
            onSubmit={async (v) => { const p = await projects.create(v); setCreating(false); if (p?.id) nav(`/projects/${p.id}`); }} />
        </Sheet>
      )}
    </>
  );
}

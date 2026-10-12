// 工作区 = 云端电脑上的一个文件夹 + 一个沙盒——与服务器 app/workspaces.py、App core/workspace.dart 同一规则（唯一入口）：
// 项目对话 → 项目自己的工作区（id = 项目 id）；主聊天 → 个人工作区（id = "me"，“我的文件”）。

export const PERSONAL_WORKSPACE = "me";

/** 一段对话所在的工作区：没有项目（主聊天）= 个人工作区。 */
export const workspaceOf = (projectId?: string | null) => projectId || PERSONAL_WORKSPACE;

export const isPersonalWorkspace = (ws?: string | null) => ws === PERSONAL_WORKSPACE;

/** 文件夹的名字：抽屉标题、附件来源、“存成文件”的目标都用它。 */
export const workspaceFilesTitle = (ws?: string | null) => (isPersonalWorkspace(ws) ? "我的文件" : "项目文件");

/** 文件夹是空的时的说明。 */
export const workspaceEmptyText = (ws: string) => isPersonalWorkspace(ws)
  ? "上传资料后，在主聊天里我可以直接读它们，也能在云端电脑上跑代码处理；我生成的文件也会放在这里。"
  : "上传资料让我参考，或者让我在这个项目里写代码、跑命令，生成的文件都会出现在这里。";

/** 引用选择器里文件夹是空的时的说明。 */
export const workspacePickEmptyText = (ws: string) => isPersonalWorkspace(ws)
  ? "先在“我的 → 我的文件”里上传资料，再回来引用。"
  : "先在项目的“文件”里上传资料，再回来引用。";

/** 工作区里一个文件的下载路径（未带 token，交给 fileUrl）：每段路径各自编码——唯一规则（= App core/workspace.dart workspaceFilePath）。 */
export const workspaceFilePath = (ws: string, rel: string) =>
  `/api/projects/${ws}/files/${rel.split("/").map(encodeURIComponent).join("/")}`;

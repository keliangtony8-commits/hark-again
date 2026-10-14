// 工作区 = 云端电脑上的一个文件夹 + 一个沙盒，规则和服务器 app/workspaces.py 一致（唯一入口）：
// 项目对话 → 项目自己的工作区（id = 项目 id）；主聊天 → 个人工作区（id = 'me'，“我的文件”）。
// 文件接口、文件块、后台任务都用工作区 id，客户端不再区分“有没有项目”。

const personalWorkspace = 'me';

/// 一段对话所在的工作区：projectId 为空（主聊天）= 个人工作区。
String workspaceOf(String projectId) => projectId.isEmpty ? personalWorkspace : projectId;

bool isPersonalWorkspace(String ws) => ws == personalWorkspace;

/// 文件夹的名字：标题、附件来源、“存成文件”目标都用它。
String workspaceFilesTitle(String ws) => isPersonalWorkspace(ws) ? '我的文件' : '项目文件';

/// 文件夹是空的时的说明。
String workspaceEmptyText(String ws) => isPersonalWorkspace(ws)
    ? '上传资料后，我可以在主聊天中直接读取，也能在云端电脑上运行代码处理；我生成的文件也会存放在这里。'
    : '上传资料后，我可以在此项目的对话中直接读取，也能在沙箱中运行代码处理。';

/// 引用选择器里文件夹是空的时的说明。
String workspacePickEmptyText(String ws) =>
    isPersonalWorkspace(ws) ? '先在“我的 → 我的文件”里上传资料，再回来引用。' : '先在项目的“文件”里上传资料，再回来引用。';

/// 工作区里一个文件的下载路径（未带 token，由 Api.fileUrl 补上）：每段路径各自编码——唯一规则。
String workspaceFilePath(String ws, String rel) =>
    '/api/projects/$ws/files/${rel.split('/').map(Uri.encodeComponent).join('/')}';

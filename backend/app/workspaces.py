"""工作区（“云电脑”上的一个文件夹 + 一个沙盒容器）的唯一规则。

每段对话都有工作区（对标 Hark：主聊天也能跑命令、读写文件）：
- 项目对话 → 项目自己的工作区，id = 项目 id（data/projects/<id>，容器 sbx-<id>）；
- 主聊天和定时任务 → 用户的个人工作区，id = PERSONAL（data/projects/me，容器 sbx-me），跨对话保留。
项目 id 是 32 位十六进制，"me" 永远不会和它撞。
文件、沙盒、后台任务（Job.project_id 存的就是工作区 id）、长输出落盘都按工作区 id 走，不再区分主聊天/项目。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project

# 容器里的环境（与 sandbox/image/Dockerfile 预装清单 + workspace-env.sh 同步）：模型据此知道什么装得上、装了留不留得住
PREINSTALLED = "python3、node/npm、git、curl、gcc/make、jq、ripgrep、zip/unzip、sqlite3、poppler-utils（pdftotext）、ImageMagick、中文字体、procps（ps/top）"
HOME_DIR = ".home"  # 工作区里的家目录（隐藏）：pip/npm 用户级安装、git 全局配置都在这里
ENVIRONMENT = (f"沙盒是非 root 的 Debian（没有 sudo/apt），已预装：{PREINSTALLED}。"
               "Python 包直接 pip install、Node 命令行工具 npm i -g：都装进工作区（~/.local），以后的对话和后台任务都能接着用，"
               "容器重建也不丢，不用每次重装；项目自己的依赖照常用 .venv / node_modules。"
               "缺系统软件就换 pip/npm 上的替代品，实在没有就告诉用户需要往沙盒镜像里加什么。"
               "找文件用 glob、搜内容用 grep（比 run_command find/grep 快，不唤醒沙盒），改文件用 edit_file。"
               "做了网页/小工具要给用户看：后台启动服务（监听 0.0.0.0）后用 preview_port 出预览卡，别让用户自己找端口。")

PERSONAL = "me"
PERSONAL_NAME = "我的文件"


def of(project_id: str | None) -> str:
    """对话 / 任务所在的工作区：项目对话 = 项目，其余 = 个人工作区。"""
    return project_id or PERSONAL


def is_personal(ws: str | None) -> bool:
    return ws == PERSONAL


async def name(db: AsyncSession, ws: str) -> str | None:
    """给人看的名字；不存在的工作区 → None（接口据此 404，不再为任意 id 建目录）。"""
    if is_personal(ws):
        return PERSONAL_NAME
    p = await db.get(Project, ws) if ws else None
    return p.name if p is not None else None


def prompt_line(ws: str) -> str:
    """系统提示里那一句：告诉模型这段对话的工作区是什么、能留多久。"""
    if is_personal(ws):
        return ("你有一台云端 Linux 电脑：用户的个人工作区（文件工具 + run_command 共用，跨对话保留，"
                "用户在“我的文件”里能看到）。需要算、跑代码、处理文件、生成产物时直接用它；"
                "和某个项目有关的活建议用户到那个项目里做。" + ENVIRONMENT)
    return "可以用文件工具和 run_command 操作项目工作区（只属于这个项目）。" + ENVIRONMENT

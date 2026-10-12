"""工具注册表。

每个工具一个文件放在 agent/builtin/，用 @tool 注册；内核只认识注册表，不认识具体工具。
工具返回 ToolResult：content 回给模型看，blocks 直接展示给用户（表格、链接卡等），images 给模型看图（vision.for_tool）。
跑得久的工具可在执行中用 ctx.live(block) 推进度块（见 ToolContext.live）。
"""
import importlib
import inspect
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..plan_mode import State as PlanState
from ..turn_changes import Tracker as ChangeTracker
from ..workspace_instructions import Tracker
from ..workspaces import of as workspace_of
from .approvals import FormReply


Approver = Callable[[str, str, str], Awaitable[bool]]  # (approval_id, 标题, 详情) -> 是否批准
Asker = Callable[[str, dict], Awaitable["FormReply | None"]]  # (form_id, 表单卡) -> 用户填的值；None = 取消


async def deny_all(_id: str, _title: str, _detail: str) -> bool:
    """无人值守（定时任务）时的审批策略：高风险操作一律不做。"""
    return False


def no_live(_block: dict) -> None:
    """不在聊天里跑（或工具没在执行）时，实时块无处可推：丢掉。"""


async def nobody(_id: str, _form: dict) -> "FormReply | None":
    """无人值守时没人填表：一律当作取消。"""
    return None


@dataclass
class ToolContext:
    db: AsyncSession
    project_id: str | None = None
    approve: Approver = deny_all
    conversation_id: str | None = None  # 当前对话（分享对话等“作用于这段对话本身”的工具用）
    ask: Asker = nobody  # 在聊天里弹表单卡问用户（登录、验证码）
    task_id: str | None = None  # 这一轮是哪个定时任务在跑（None = 用户在聊天）；如早间简报不把自己列进今天的日程
    # 工具运行中推“实时块”（如命令的最新输出）：内核把第一次推的插进回复，之后原地替换；
    # 工具结束时 ToolResult.blocks[0] 就是它的最终形态（没有块则保留最后一次推的、去掉 live）。只由内核在执行期间挂上。
    live: Callable[[dict], None] = no_live
    model: str | None = None  # 这一轮实际用的模型别名（loop.run 填上；子助手沿用它，Codex：spawned agents inherit your model）
    # 对话选的思考强度（None = 模型默认）；实际发哪档由 reasoning.resolve 按当时的模型定。子助手同样沿用（Codex child_config）
    effort: str | None = None
    # 只许用这些工具（None = 不限）：子助手的工具白名单（agent/subagent.py CHILD_TOOLS），不在名单里的不给模型、也不执行
    allow: frozenset[str] | None = None
    depth: int = 0  # 0 = 主助手；1 = 子助手（不能再派，Codex DEFAULT_AGENT_MAX_DEPTH = 1）
    # 这一轮已告知模型的子目录规则文件（app/workspace_instructions.py）；每个 ToolContext 一个，并行调用的副本共用同一个
    instructions: Tracker = field(default_factory=Tracker)
    # 这一轮 write_file / edit_file 碰过的文件基线（app/turn_changes.py）：收尾出净改动卡 + 整轮撤销；并行副本、子助手共用
    changes: ChangeTracker = field(default_factory=ChangeTracker)
    # 计划模式（app/plan_mode.py）：None = 没开；State.active 时只放只读工具，exit_plan_mode 批准后 lift()。并行副本共用
    plan: "PlanState | None" = None
    host: bool = False  # 服务器主机模式开着（run_turn 每轮从 host_mode.enabled 读）：scope="host" 的工具才出现

    @property
    def workspace(self) -> str:
        """这段对话的工作区 id（项目 = 项目 id；主聊天、定时任务 = 个人工作区）。规则在 app/workspaces.py。"""
        return workspace_of(self.project_id)


@dataclass
class Approval:
    """risk 的富返回值：理由 + 工具自己画的审批卡（可带 options：批准范围，用户选的以 grant= 传给 grants=True 的工具）。
    risk 返回普通字符串 = 通用审批卡（或 Tool.card 画的卡）。"""
    reason: str
    card: dict | None = None
    rejected: str | None = None  # 用户没批准时还给模型的话（None = 通用的“已取消，别绕过”）；如方案卡：没批准 = 问他改哪里


@dataclass
class ToolImage:
    """工具拿到、要给模型“看”的图（原始字节）。怎么给（原图还是描述）由 vision.for_tool 决定，工具不用管。"""
    name: str
    data: bytes


@dataclass
class ToolResult:
    content: str
    blocks: list[dict] = field(default_factory=list)
    images: list[ToolImage] = field(default_factory=list)
    failed: str = ""  # 非空 = 这一步没成（活动时间线记 error + 这句原因），内容照常交给模型
    # 改了工作区里的文件：file_edit.change() 的摘要（apply_patch 一次改几个文件 → 列表），随时间线那一步落库，两端显示 +N −M 与 diff
    change: dict | list[dict] | None = None
    # 这次调用前用户批准过的那张卡要补的字段（执行后才知道的结果，如方案没存成 → {"path": ""}）；内核合并进卡，没批准卡就忽略
    card: dict | None = None


@dataclass
class Tool:
    name: str
    label: str            # 给用户看的进行时文案，如“正在搜索”
    description: str      # 给模型看
    parameters: dict      # JSON Schema
    run: Callable[..., Awaitable[ToolResult]]
    scope: str = "always"  # always（含文件与沙盒：每段对话都有工作区）| project（只在项目对话里，如项目档案）| conversation（需要知道当前对话）| host（服务器主机模式开着）
    # (参数, 上下文) → 需要审批的理由（或 Approval，可以是 awaitable）；None = 直接执行
    risk: "Callable[[dict, ToolContext], object] | None" = None
    # 需要审批时的卡片：返回一个带 state 的块（如订单卡），内核补上 id；None = 通用审批卡。参数不对就抛 ValueError。
    card: Callable[[dict], dict] | None = None
    # 执行前要问用户的表单（如登录卡）：返回表单卡（不带 id/state）或 None = 不用问。
    # 用户填完，值以 form=FormReply 传给 run；取消则不执行。模型传来的 form 参数一律丢弃。
    form: Callable[[ToolContext, dict], Awaitable[dict | None]] | None = None
    grants: bool = False  # 审批卡带批准范围选项：批准后用户选的范围以 grant= 传给 run（模型传的 grant 一律丢弃）
    # 能和同一步里别的只读调用同时跑（agent/parallel.py）：True，或 (参数) → bool 按这次参数判断。默认独占。
    # 前提：不改共享状态、不碰 ctx.db（共用的 AsyncSession 不能并发）、不要审批/表单。
    parallel: "bool | Callable[[dict], bool]" = False
    quiet: bool = False  # 控制类工具（update_plan）：不进活动时间线、不亮“正在…”，用户看它自己的卡片就够了（Codex 的 builtin control tool）

    @property
    def accepts(self) -> set[str] | None:
        """run 能收的参数名（agent/tool_args.py 丢掉别的，免得 TypeError）；带 **kwargs = None（全收）。"""
        ps = inspect.signature(self.run).parameters
        if any(p.kind is p.VAR_KEYWORD for p in ps.values()):
            return None
        return {n for n in ps if n != "ctx"}

    def available(self, ctx: ToolContext) -> bool:
        if ctx.allow is not None and self.name not in ctx.allow:
            return False
        if self.scope == "project":
            return ctx.project_id is not None
        if self.scope == "conversation":
            return ctx.conversation_id is not None
        if self.scope == "host":
            return ctx.host
        return True


REGISTRY: dict[str, Tool] = {}


def tool(name: str, label: str, description: str, parameters: dict, scope: str = "always",
         risk: "Callable[[dict, ToolContext], str | None] | None" = None, card: Callable[[dict], dict] | None = None,
         form: Callable[[ToolContext, dict], Awaitable[dict | None]] | None = None, quiet: bool = False,
         grants: bool = False, parallel: "bool | Callable[[dict], bool]" = False):
    def deco(fn):
        REGISTRY[name] = Tool(name, label, description, parameters, fn, scope, risk, card, form, grants, parallel, quiet)
        return fn
    return deco


def schemas(ctx: ToolContext) -> list[dict]:
    """只把当前上下文可用的工具交给模型：少给一个工具就少一段 token。"""
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in REGISTRY.values() if t.available(ctx)
    ]


def load_builtin() -> None:
    from . import builtin
    # 按模块名排序导入：工具定义的顺序固定（目录列举顺序不保证），每次请求的 tools 段逐字相同才能命中提示缓存
    for m in sorted(pkgutil.iter_modules(builtin.__path__), key=lambda m: m.name):
        importlib.import_module(f"{builtin.__name__}.{m.name}")

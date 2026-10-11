"""工具注册表。

每个工具一个文件放在 agent/builtin/，用 @tool 注册；内核只认识注册表，不认识具体工具。
工具返回 ToolResult：content 回给模型看，blocks 直接展示给用户（表格、链接卡等）。
"""
import importlib
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession


Approver = Callable[[str, str, str], Awaitable[bool]]  # (approval_id, 标题, 详情) -> 是否批准


async def deny_all(_id: str, _title: str, _detail: str) -> bool:
    """无人值守（定时任务）时的审批策略：高风险操作一律不做。"""
    return False


@dataclass
class ToolContext:
    db: AsyncSession
    project_id: str | None = None
    approve: Approver = deny_all
    conversation_id: str | None = None  # 当前对话（分享对话等“作用于这段对话本身”的工具用）


@dataclass
class ToolResult:
    content: str
    blocks: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    label: str            # 给用户看的进行时文案，如“正在搜索”
    description: str      # 给模型看
    parameters: dict      # JSON Schema
    run: Callable[..., Awaitable[ToolResult]]
    scope: str = "always"  # always | project（只在项目对话里提供，如文件与沙盒）| conversation（需要知道当前对话）
    risk: Callable[[dict], str | None] | None = None  # 返回需要审批的理由；None = 直接执行

    def available(self, ctx: ToolContext) -> bool:
        if self.scope == "project":
            return ctx.project_id is not None
        if self.scope == "conversation":
            return ctx.conversation_id is not None
        return True


REGISTRY: dict[str, Tool] = {}


def tool(name: str, label: str, description: str, parameters: dict, scope: str = "always",
         risk: Callable[[dict], str | None] | None = None):
    def deco(fn):
        REGISTRY[name] = Tool(name, label, description, parameters, fn, scope, risk)
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
    for m in pkgutil.iter_modules(builtin.__path__):
        importlib.import_module(f"{builtin.__name__}.{m.name}")

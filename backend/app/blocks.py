"""消息块协议：前后端唯一契约。

新增一种卡片 = 这里加一个类 + 前端 blocks/ 加一个组件 + registry 登记。
主流程（agent loop / 路由 / 渲染器）一行不用改。
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str  # Markdown


class LinkItem(BaseModel):
    url: str
    label: str | None = None
    title: str | None = None


class LinksBlock(BaseModel):
    type: Literal["links"] = "links"
    items: list[LinkItem]


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: str | None = None
    columns: list[str]
    rows: list[list[str]]
    note: str | None = None


class CodeBlock(BaseModel):
    type: Literal["code"] = "code"
    language: str = ""
    title: str | None = None
    source: str


class FileBlock(BaseModel):
    """文件卡片。source=upload：聊天附件（id 为上传 id）；source=project：项目文件（id 为相对路径）。"""
    type: Literal["file"] = "file"
    source: Literal["upload", "project"] = "upload"
    id: str
    name: str
    mime: str = "application/octet-stream"
    size: int = 0
    project_id: str | None = None


class ApprovalBlock(BaseModel):
    """高风险操作的审批卡。state 从 pending 变为 approved / rejected / expired。"""
    type: Literal["approval"] = "approval"
    id: str
    title: str
    detail: str
    state: Literal["pending", "approved", "rejected", "expired"] = "pending"


class BrowserBlock(BaseModel):
    """云浏览器实时画面卡：显示截图，用户可点击/打字接管。"""
    type: Literal["browser"] = "browser"
    session: str = "main"


class PageBlock(BaseModel):
    """生成的网页：预览 + 打开 + 复制链接。"""
    type: Literal["page"] = "page"
    slug: str
    title: str
    url: str


class StatItem(BaseModel):
    label: str  # 小字标签：“今日最高”“日落”“本月花费”
    value: str  # 大字数值，原样显示（带单位）：“26°C”“18:42”“¥12.30”
    note: str | None = None  # 一句变化/补充：“比昨天 ↑3°”


class StatsBlock(BaseModel):
    """几个关键数字（面板、简报）：每项一块 标签 + 大数字 的小卡片。两三项最好，最多 6 项。"""
    type: Literal["stats"] = "stats"
    items: list[StatItem] = Field(min_length=1, max_length=6)


Block = Annotated[Union[TextBlock, LinksBlock, TableBlock, CodeBlock, FileBlock, ApprovalBlock, BrowserBlock,
                        PageBlock, StatsBlock],
                  Field(discriminator="type")]


def text_to_blocks(text: str) -> list[dict]:
    return [TextBlock(text=text).model_dump()]


def blocks_to_text(blocks: list[dict]) -> str:
    """把历史消息压回纯文本喂给模型。"""
    parts = []
    for b in blocks:
        t = b.get("type")
        if t == "text":
            parts.append(b["text"])
        elif t == "code":
            parts.append(f"```{b.get('language','')}\n{b['source']}\n```")
        elif t == "table":
            parts.append(" | ".join(b["columns"]) + "\n" + "\n".join(" | ".join(r) for r in b["rows"]))
        elif t == "stats":
            parts.append("\n".join(f"{i['label']}：{i['value']}" + (f"（{i['note']}）" if i.get("note") else "") for i in b["items"]))
        elif t == "links":
            parts.append("\n".join(i["url"] for i in b["items"]))
        elif t == "page":
            parts.append(f"[网页「{b['title']}」{b['url']}，slug: {b['slug']}]")
        elif t == "approval":
            parts.append(f"[审批：{b['title']}——{b['state']}]")
        elif t == "file":
            parts.append(f"[文件：{b['name']}]")
    return "\n\n".join(parts)

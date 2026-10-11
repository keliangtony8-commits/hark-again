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


class MemoryItem(BaseModel):
    id: str
    content: str
    category: str = "general"
    previous: str | None = None  # updated：改前的内容（撤销用）


class MemoryBlock(BaseModel):
    """记忆卡：本轮回复里记住/改了/忘掉了哪些事。只由记忆工具产出（memory_store.card）。
    不存“已撤销”状态：客户端对照当前记忆列表推算（saved 的 id 不在了 = 已撤销；updated 内容回到 previous = 已撤销；
    forgotten 的内容又在了 = 已恢复），所以重开对话也一致。"""
    type: Literal["memory"] = "memory"
    action: Literal["saved", "updated", "forgotten"]
    items: list[MemoryItem] = Field(min_length=1)


class DraftBlock(BaseModel):
    """草稿卡：用户要拿去以自己名义发出的文字（邮件连主题行、微信消息、帖子、请假条）。
    原样显示（不渲染 Markdown），一键复制 / 分享。"""
    type: Literal["draft"] = "draft"
    title: str  # 是什么、发给谁：“给房东的邮件”“朋友圈文案”
    body: str


class SummaryBlock(BaseModel):
    """摘要卡：用户会自己读的长内容（计划、行程、简报、清单），带标题的一份 Markdown 文档。"""
    type: Literal["summary"] = "summary"
    title: str
    subtitle: str | None = None  # 来源或范围：“杭州 · 10 月 18–19 日”“来自 xx.com”
    markdown: str


class ImageItem(BaseModel):
    url: str = Field(pattern=r"^https?://")
    caption: str | None = None


class ImagesBlock(BaseModel):
    """图片卡：用户想看样子时的一组网络图片（地址来自搜索/网页，不编造），最多 6 张。"""
    type: Literal["images"] = "images"
    items: list[ImageItem] = Field(min_length=1, max_length=6)


Block = Annotated[Union[TextBlock, LinksBlock, TableBlock, CodeBlock, FileBlock, ApprovalBlock, BrowserBlock,
                        PageBlock, StatsBlock, MemoryBlock, DraftBlock, SummaryBlock, ImagesBlock],
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
        elif t == "memory":
            verb = {"saved": "已记住", "updated": "已修改记忆", "forgotten": "已忘掉"}.get(b["action"], "记忆")
            parts.append(f"[{verb}：" + "；".join(i["content"] for i in b["items"]) + "]")
        elif t == "file":
            parts.append(f"[文件：{b['name']}]")
        elif t == "draft":
            parts.append(f"[草稿「{b['title']}」]\n{b['body']}")
        elif t == "summary":
            parts.append(f"# {b['title']}\n" + (f"{b['subtitle']}\n" if b.get("subtitle") else "") + b["markdown"])
        elif t == "images":
            parts.append("[图片：" + "；".join((i.get("caption") or "") + " " + i["url"] for i in b["items"]) + "]")
    return "\n\n".join(parts)

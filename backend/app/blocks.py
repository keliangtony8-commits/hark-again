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
    """live=true：命令还在跑，source 是最近的输出（run_command 运行中原地更新）；跑完换成不带 live 的最终块。"""
    type: Literal["code"] = "code"
    language: str = ""
    title: str | None = None
    source: str
    live: bool = False


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
    session: str = "main"  # 会话名（按网站起名，app/browser_sessions.py）；旧卡 main
    site: str | None = None  # 打开的网站主域名（卡头显示）
    live: bool = False  # browser_open 正在打开页面（还没画面时客户端显示“正在打开”，不当作没开）


class JobBlock(BaseModel):
    """项目沙盒里的后台任务卡（app/jobs.py）。运行中客户端轮询 /api/jobs/{id} 显示进度、可取消；结束时服务器把块改成终态。"""
    type: Literal["job"] = "job"
    id: str
    title: str
    command: str
    state: Literal["running", "done", "failed", "timed_out", "cancelled", "lost"] = "running"
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    tail: str | None = None  # 结束时日志的最后一段
    stop_reason: str | None = None  # 被护栏自动停掉的原因（卡住 / 输出过大），state=cancelled


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


class ProductItem(BaseModel):
    name: str
    price: str | None = None  # 原样显示，数在前单位在后：“¥189”“¥89 / 晚”
    image: str | None = Field(default=None, pattern=r"^https?://")  # 来自商品页的真实图；打不开的服务器已置空
    url: str | None = Field(default=None, pattern=r"^https?://")  # 读到这一项的那个页面
    meta: str | None = None  # 一行补充：“4.8 分 · 京东自营”“明天到”


class ProductsBlock(BaseModel):
    """商品宫格：挑东西、看样子也是挑选的一部分时（商品、二手、酒店、民宿、花）。一格 = 图 + 名字 + 价格。"""
    type: Literal["products"] = "products"
    title: str | None = None
    pick: str | None = None  # 一句推荐和理由，显示在卡片底部
    items: list[ProductItem] = Field(min_length=1, max_length=12)


class OrderLine(BaseModel):
    name: str
    price: str  # 原样：“¥59.00”
    qty: int = Field(default=1, ge=1)
    note: str | None = None  # 规格：“黑色 · M 码”
    image: str | None = Field(default=None, pattern=r"^https?://")


class OrderFee(BaseModel):
    label: str  # 运费、优惠、税
    amount: str  # 原样：“-¥10.00”


ORDER_STATES = ("pending", "approved", "rejected", "expired", "placed")


class OrderBlock(BaseModel):
    """订单卡：下单/付款前给用户确认的那一步，或下单后的回执。
    pending = 等用户在卡上点“确认下单”（和审批卡共用 approval.reply，id 即审批 id）；approved / rejected / expired 同审批卡；
    placed = 已下单的回执（带 order_number，没有按钮）。金额全部原样显示，服务器不算账。"""
    type: Literal["order"] = "order"
    id: str
    merchant: str  # 付给谁、哪家店：“瑞幸咖啡 · 五道口店”
    items: list[OrderLine] = Field(min_length=1)
    breakdown: list[OrderFee] = Field(default_factory=list)
    total: str
    payment: str | None = None  # 页面上的叫法：“招行信用卡 9258”
    destination: str | None = None  # 送到哪 / 什么时候：“宿舍 6 号楼，放门口”“周六 19:00”
    order_number: str | None = None
    action: str = "确认下单"  # 按钮上的字（≤12 字）
    state: Literal["pending", "approved", "rejected", "expired", "placed"] = "pending"


class FormField(BaseModel):
    name: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,23}$")
    label: str
    kind: Literal["text", "email", "password", "code", "phone", "multiline"] = "text"  # password 遮住；code 数字键盘 + 短信验证码自动填充；phone 电话键盘；multiline 多行（地址、备注）
    value: str | None = None  # 预填（只放不敏感的，如用户名）
    options: list[str] | None = Field(default=None, max_length=6)  # 可点选的候选（点了填进框里，仍可改写）
    optional: bool = False  # 选填：空着也能提交


class FormAnswer(BaseModel):
    label: str
    value: str


class FormBlock(BaseModel):
    """表单卡：任务进行中向用户要东西（网站登录、验证码、助手缺的信息）。和审批卡一样挂起等答复（form.reply，id 即表单 id）。
    pending → submitted / cancelled / expired。login / code 的值不写进卡片：只交给发起的工具，不落库、不给模型看；
    info（ask_user）是用户有意告诉助手的，提交后写进 answers（卡片上回显、进历史，下一轮模型也记得）。"""
    type: Literal["form"] = "form"
    id: str
    purpose: Literal["login", "code", "info"] = "info"
    title: str
    site: str | None = None  # 网站域名，卡片上显示“在 xxx 上”
    fields: list[FormField] = Field(min_length=1, max_length=6)
    remember: bool = False  # 是否提供“记住”（login → 保险箱；info → 长期记忆）
    action: str = "提交"
    state: Literal["pending", "submitted", "cancelled", "expired"] = "pending"
    note: str | None = None  # 为什么要问（info 卡标题下一行小字）
    answers: list[FormAnswer] | None = None  # 只有 info 卡提交后才有；选填没填的不列


Block = Annotated[Union[TextBlock, LinksBlock, TableBlock, CodeBlock, FileBlock, ApprovalBlock, BrowserBlock,
                        PageBlock, StatsBlock, MemoryBlock, DraftBlock, SummaryBlock, ImagesBlock, ProductsBlock,
                        OrderBlock, FormBlock, JobBlock],
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
        elif t == "form":
            state = {"pending": "等用户填写", "submitted": "用户已填写", "cancelled": "用户取消了", "expired": "已过期"}.get(b.get("state"), "")
            site = f"（{b['site']}）" if b.get("site") else ""
            answers = "".join(f"\n{a['label']}：{a['value']}" for a in b.get("answers") or [])
            parts.append(f"[表单：{b['title']}{site}——{state}]{answers}")
        elif t == "memory":
            verb = {"saved": "已记住", "updated": "已修改记忆", "forgotten": "已忘掉"}.get(b["action"], "记忆")
            parts.append(f"[{verb}：" + "；".join(i["content"] for i in b["items"]) + "]")
        elif t == "file":
            parts.append(f"[文件：{b['name']}]")
        elif t == "job":
            state = {"running": "运行中（结束时你会收到通知，也可用 job_status 查看）", "done": "已完成", "failed": "失败",
                     "timed_out": "超时被终止", "cancelled": "已取消", "lost": "中断了"}.get(b.get("state"), "")
            if b.get("stop_reason"):
                state = f"被自动停止（{b['stop_reason']}）"
            code = f"，退出码 {b['exit_code']}" if b.get("exit_code") not in (None, 0) and b.get("state") != "cancelled" else ""
            tail = f"\n最后的输出：\n{b['tail'][-600:]}" if b.get("tail") else ""
            parts.append(f"[后台任务 {b['id']}「{b['title']}」——{state}{code}]{tail}")
        elif t == "draft":
            parts.append(f"[草稿「{b['title']}」]\n{b['body']}")
        elif t == "summary":
            parts.append(f"# {b['title']}\n" + (f"{b['subtitle']}\n" if b.get("subtitle") else "") + b["markdown"])
        elif t == "images":
            parts.append("[图片：" + "；".join((i.get("caption") or "") + " " + i["url"] for i in b["items"]) + "]")
        elif t == "products":
            lines = [" ".join(x for x in (i["name"], i.get("price"), i.get("meta"), i.get("url")) if x) for i in b["items"]]
            parts.append("[商品" + (f"「{b['title']}」" if b.get("title") else "") + "：\n" + "\n".join(lines) + "]"
                         + (f"\n推荐：{b['pick']}" if b.get("pick") else ""))
        elif t == "order":
            state = {"pending": "等用户确认", "approved": "用户已确认", "rejected": "用户拒绝了", "expired": "已过期",
                     "placed": "已下单"}.get(b.get("state"), "")
            items = "；".join(f"{i['name']} ×{i.get('qty', 1)} {i['price']}" for i in b["items"])
            no = f"，订单号 {b['order_number']}" if b.get("order_number") else ""
            parts.append(f"[订单 {b['merchant']}：{items}；合计 {b['total']}——{state}{no}]")
    return "\n\n".join(parts)

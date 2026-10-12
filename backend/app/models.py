"""持久化模型。消息内容统一存为“块列表”(JSON)，与 blocks.py 协议一致。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, event, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .blocks import blocks_to_text
from .db import Base
from .wire_time import iso


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    # 标题从哪来（app/conversation_title.py）：first = 第一句话截取（第一轮后自动换成模型起的）/ auto / user = 用户改过 /
    # fixed = 程序给的（定时任务等），只有 first 会被自动改
    title_source: Mapped[str] = mapped_column(String(8), default="fixed", server_default="fixed")
    # 预留：Phase 3 的 Project 归属
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 这个对话用的聊天模型别名（settings.chat_models 的键）；None = 默认。解析见 llm.chat_model
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 选了“自动”（model_router.AUTO）时上一轮实际路由到的别名：客户端显示“自动 · 快速”，“继续”这类接话沿用它
    routed_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 这个对话选的思考强度（reasoning.EFFORTS 的键）；None = 模型默认。实际发哪档见 reasoning.resolve
    reasoning: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 滚动摘要（context.py 维护）：summary 概括了从开头到 summary_upto 这条消息（含）为止的内容；
    # 更早的原文不再发给模型。summary_upto 指向的消息不在了（被重答删掉）就视为作废。
    summary: Mapped[str] = mapped_column(Text, default="", server_default="", info={"private": True})
    summary_upto: Mapped[str | None] = mapped_column(String(32), nullable=True, info={"private": True})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="done", server_default="done")  # done | stopped（用户中途停止）| interrupted（服务器崩溃/重启打断，turn_journal 恢复）| wrapped（预算用完收尾）| looped（原地打转被叫停）
    # 活动时间线：这条回复里每次工具调用一步（app/activity.py 定义形状）；用户消息、老消息为空
    steps: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # 工具轨迹：这条回复里模型调过的工具 + 截短的结果（OpenAI 消息形状，agent/tool_trace.py 定义），只给下一轮的模型看，不上协议
    trace: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # 纯文本副本，只给搜索用（JSON 里的中文可能被转义，直接 LIKE 不可靠）；由下方监听器自动维护，调用方不用管
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def to_wire(self) -> dict:
        """协议里的消息形状；status 只在不是 done 时带上，老客户端无感。
        created_at 一律带时区（SQLite 读回来是无时区的，按 UTC 补上），客户端按本地日期画日期分隔。"""
        out = {"id": self.id, "role": self.role, "blocks": self.blocks}
        if self.created_at:
            out["created_at"] = iso(self.created_at)
        if self.status and self.status != "done":
            out["status"] = self.status
        if self.steps:
            out["steps"] = self.steps
        return out


class TurnJournal(Base):
    """一轮回答进行中的检查点（崩溃恢复，app/turn_journal.py 是唯一入口）。正常结束就删；
    进程死了留下的行由 turn_journal.recover 转成 status=interrupted 的助手消息。"""
    __tablename__ = "turn_journals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner: Mapped[str] = mapped_column(String(48))  # "<进程>:<启动 id>"
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    trace: Mapped[list] = mapped_column(JSON, default=list)  # 到目前为止的工具轨迹（tool_trace.record；恢复后进 messages.trace）
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    """独立工作区：自己的对话、规则（注入系统提示）、文件（Phase 3 接沙盒）。"""
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(8), default="📁")
    rules: Mapped[str] = mapped_column(String, default="")
    # 项目档案（project_brief.py）：目标、决定、文件、做法的活文档，用户和助手都能改；注入项目对话的系统提示。
    brief: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_by: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 最后一次谁改的：user | assistant
    brief_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Memory(Base):
    """长期记忆：一条一个事实/偏好。可查看、编辑、遗忘。检索逻辑在 memory_store.py。"""
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    category: Mapped[str] = mapped_column(String(32), default="general")  # profile|food|travel|work|general…
    content: Mapped[str] = mapped_column(String)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True, info={"private": True})  # 内容改了就清空，检索时懒补
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class MemoryDigest(Base):
    """“我对你的了解”：把全部记忆浓缩成一段话（单行表，id 固定 "me"）。
    只在用户点生成时调模型（花 token）；fingerprint = 生成时记忆集合的指纹，对不上就是“过期”，由客户端提示重新生成。"""
    __tablename__ = "memory_digest"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="me")
    text: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    memory_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScheduledTask(Base):
    """定时任务：worker 按 cron 执行。output 决定结果去向：
    report = 进 Home 收件箱（每次一段新对话）；panel = 原地刷新 Home 上的面板（不留对话）。
    两种计划二选一（app/schedule.py 校验）：cron = 重复；run_at = 一次性（cron 为空串），跑过即“已完成”。"""
    __tablename__ = "scheduled_tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(120))
    prompt: Mapped[str] = mapped_column(String)
    cron: Mapped[str] = mapped_column(String(64), default="")  # 标准 5 段 cron，按用户时区；一次性任务为空串
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 一次性任务的时刻（UTC）
    active: Mapped[bool] = mapped_column(default=True)
    output: Mapped[str] = mapped_column(String(16), default="report", server_default="report")
    run_requested: Mapped[bool] = mapped_column(default=False)  # “立即运行”，由 worker 领取
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 上一次结束的运行：ok | error；没跑过 = null
    fail_streak: Mapped[int] = mapped_column(default=0, server_default="0")  # 连续失败次数（成功归零；见 app/task_runs.py）
    paused_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)  # failures = 连续失败自动暂停；用户手动停 = null
    # 这个任务每次运行用的模型别名 / 思考强度（null = 默认）；规则同对话（llm.chat_model / reasoning.resolve），校验见 task_store.check_choice
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TaskRun(Base):
    """定时任务的一次运行（见 app/task_runs.py）。每个任务只留最近 KEEP 条。
    conversation_id：report 任务的那段对话（可点开）；panel 任务执行完就删对话，所以为 null。"""
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")  # schedule | manual
    status: Mapped[str] = mapped_column(String(16), default="running")    # running | ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HomeCard(Base):
    """Home 上的卡片：kind=action（主动建议，可执行/忽略）| panel（可刷新的面板）
    | report（定时任务的结果，进收件箱，点开是完整对话）。内容同样是块列表，复用聊天的渲染器。"""
    __tablename__ = "home_cards"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    action_prompt: Mapped[str | None] = mapped_column(String, nullable=True)  # 点“去做”时发给 Agent 的话
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # 客户端里的去处（"usage" = 用量页，"project:<id>" = 某个项目…，规则见 app/card_targets.py）；客户端各自映射成按钮，不认识的值忽略
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 主按钮上的字（空 = “去做”）；origin=agent 表示智能体提议的卡（规则见 app/home_offers.py），空 = 系统提醒/接口建的
    action_label: Mapped[str | None] = mapped_column(String(24), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 建议卡的配图（卡顶一张图）和原页链接（“来源 · 域名”）：都只收 http(s)，配图由工具先探测能打开才存（app/home_offers.py）
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 系统提醒的主体（"task:<id>"、"connector:github"、"mcp:<id>"…）：收起/顶替按它，规则见 app/system_alerts.py；其余卡为空
    alert_subject: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    # 报告卡的“一眼”：摘要卡标题 + 一句话，投递时由 app/report_gist.py 从块里取出；其余卡为空
    headline: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gist: Mapped[str | None] = mapped_column(String(240), nullable=True)
    dismissed: Mapped[bool] = mapped_column(default=False)
    # 未读：新报告/新建议为 True；用户打开对应对话（或点“全部已读”）后清掉。面板刷新不算新消息。
    unread: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 稍后提醒：非空 = 先收起，到点由 worker 叫醒（清空 + 重新未读 + 顶到最前），见 app/card_snooze.py
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Secret(Base):
    """保险箱条目。明文只以密文形式落库，接口永不返回明文，模型只知道名字和适用域名。"""
    __tablename__ = "secrets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(16), default="api_key")   # api_key：按域名进请求头；login：浏览器里代填
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 仅 login；用户名不算机密
    hosts: Mapped[list] = mapped_column(JSON, default=list)            # 只注入到这些域名（含子域名）
    header_name: Mapped[str] = mapped_column(String(64), default="Authorization")
    header_prefix: Mapped[str] = mapped_column(String(32), default="Bearer ")
    ciphertext: Mapped[str] = mapped_column(String)
    preview: Mapped[str] = mapped_column(String(16))                   # 末 4 位，供界面辨认
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Connection(Base):
    """OAuth 连接（一个服务一个账户）。Token 整包加密存储，过期自动刷新。"""
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    account: Mapped[str] = mapped_column(String(200), default="")
    ciphertext: Mapped[str] = mapped_column(String)  # {"access_token","refresh_token"} 的密文
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class McpServer(Base):
    """用户自己的 MCP 服务器（Streamable HTTP）。令牌可选，同样加密。"""
    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    token_ciphertext: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageRecord(Base):
    """一次模型调用的用量（llm.py 每次调用后写一行，见 usage.py）。
    conversation_id 不设外键：对话删了，花掉的钱还在账上。cost 按写入时的单价算好存下，改单价不改历史。"""
    __tablename__ = "usage"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    model: Mapped[str] = mapped_column(String(64))                 # LiteLLM 别名：fast / smart / embed …
    kind: Mapped[str] = mapped_column(String(16))                  # chat | summary | embed
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)  # prompt_tokens 里命中提示缓存的部分（prompt_cache.cached_of）
    cost: Mapped[float] = mapped_column(Float, default=0.0)        # settings.currency
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class AlertSent(Base):
    """“这条提醒已经发过”的去重表：key 唯一（如 budget:2026-10:80:30）。
    不放在卡片上，是因为用户删卡/忽略卡后不该再被同一条提醒打扰。"""
    __tablename__ = "alerts_sent"
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppSetting(Base):
    """少量全局开关（键值）。现在只有 host_mode（服务器主机模式，默认关；规则在 app/host_mode.py）。"""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class HostRule(Base):
    """用户在主机命令审批卡上点了“以后都允许”留下的前缀规则（Codex execpolicy 的 allow prefix_rule）。
    prefix = 命令开头的字面词，如 ["systemctl", "status"]；以它开头的主机命令以后不再弹卡。只有用户能加（审批卡），能在“我的电脑”里删。"""
    __tablename__ = "host_rules"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    prefix: Mapped[list] = mapped_column(JSON)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Memory.content, "set")
def _content_changed(target: Memory, value, old, initiator) -> None:
    """内容一变向量就作废（不管从界面还是工具改的），检索时再补。"""
    if value != old:
        target.embedding = None


@event.listens_for(Message.blocks, "set")
def _blocks_changed(target: Message, value, old, initiator) -> None:
    """块一变就重算搜索文本：所有写消息的地方（WS、worker、runner）自动覆盖。"""
    target.search_text = blocks_to_text(value or [])


class Job(Base):
    """项目沙盒里的后台任务（app/jobs.py 是唯一入口）：装依赖、训练、爬取这类超过一条命令时限的活。
    进程、日志、退出码都在工作区 .jobs/<id>/ 里，这里只记归属和结论。
    state: running | done | failed | timed_out | cancelled | lost（容器重启/进程消失，没留下退出码）
    followup: none | pending（结束了，等 worker 在原对话里接着回一句）| done | seen（模型自己查过结果）| skipped
      | held（连着叫醒助手的轮数到上限了，留到用户下次说话时并进那一轮）；followup_at：哪一轮接着说的（同一轮的任务同一个时间）
    read_offset: 模型已经看过的日志字节数（job_status 只给这之后的新输出）
    idle_timeout: 连续这么多秒没有新输出就判定卡住并停掉（0 = 不判）；stop_reason: 被护栏自动停掉的原因（state=cancelled）"""
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    command: Mapped[str] = mapped_column(Text)
    timeout: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="running", server_default="running", index=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followup: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    tail: Mapped[str] = mapped_column(Text, default="", server_default="")  # 结束时日志的最后一段
    idle_timeout: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    read_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

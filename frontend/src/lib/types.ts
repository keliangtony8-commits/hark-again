// 与 backend/app/blocks.py 一一对应：这是前后端唯一契约
export type TextBlock = { type: "text"; text: string };
export type LinksBlock = { type: "links"; items: { url: string; label?: string; title?: string }[] };
export type TableBlock = { type: "table"; title?: string; columns: string[]; rows: string[][]; note?: string };
/** live：命令还在跑，source 是最近的输出（服务器 block.update 原地换），跑完换成不带 live 的最终块。 */
export type CodeBlock = { type: "code"; language?: string; title?: string; source: string; live?: boolean };
export type FileBlock = { type: "file"; source: "upload" | "project"; id: string; name: string; mime: string; size: number; project_id?: string | null };
export type ApprovalBlock = { type: "approval"; id: string; title: string; detail: string; state: "pending" | "approved" | "rejected" | "expired" };
export type BrowserBlock = { type: "browser"; session: string };
export type PageBlock = { type: "page"; slug: string; title: string; url: string };
export type StatsBlock = { type: "stats"; items: { label: string; value: string; note?: string | null }[] };
/** 记忆卡：本轮回复记住/改了/忘掉了什么（= backend blocks.MemoryBlock）。“已撤销”不在块里，见 lib/memory.ts memoryCardState。 */
export type MemoryBlock = {
  type: "memory"; action: "saved" | "updated" | "forgotten";
  items: { id: string; content: string; category: string; previous?: string | null }[];
};
/** 草稿卡：用户以自己名义发出去的文字（原样显示，复制/分享）。 */
export type DraftBlock = { type: "draft"; title: string; body: string };
/** 摘要卡：用户自己读的长文，带标题的一份 Markdown。 */
export type SummaryBlock = { type: "summary"; title: string; subtitle?: string | null; markdown: string };
/** 图片卡：想看样子时的 1–6 张网络图片。 */
export type ImagesBlock = { type: "images"; items: { url: string; caption?: string | null }[] };
/** 商品宫格（v0.81）：挑要买/要订、样子也算数的一组东西；image/url 只认 http(s)，坏图服务器已置空。 */
export type ProductsBlock = { type: "products"; title?: string | null; pick?: string | null;
  items: { name: string; price?: string | null; image?: string | null; url?: string | null; meta?: string | null }[] };
/** 订单卡（v0.81）：pending = 等用户确认（按钮走 approval.reply，id 即审批 id）；placed = 回执（带订单号）。金额原样显示。 */
export type OrderBlock = { type: "order"; id: string; merchant: string;
  items: { name: string; price: string; qty?: number; note?: string | null; image?: string | null }[];
  breakdown?: { label: string; amount: string }[]; total: string; payment?: string | null; destination?: string | null;
  order_number?: string | null; action?: string; state: "pending" | "approved" | "rejected" | "expired" | "placed" };
/** 表单卡（浏览器任务里的登录 / 验证码）：答复走 form.reply；用户填的值不写进卡片。 */
/** options = 可点选的候选（点了填进框，仍可改）；optional = 选填。 */
export type FormInput = { name: string; label: string; kind?: "text" | "email" | "password" | "code" | "phone" | "multiline"; value?: string | null;
  options?: string[] | null; optional?: boolean };
/** note = 为什么问（info 卡）；answers 只有 info 卡提交后才有（用户有意告诉助手的，login/code 的值从不进卡片）。 */
export type FormBlock = { type: "form"; id: string; purpose?: "login" | "code" | "info"; title: string; site?: string | null;
  fields: FormInput[]; remember?: boolean; action?: string; state: "pending" | "submitted" | "cancelled" | "expired";
  note?: string | null; answers?: { label: string; value: string }[] | null };
/** 项目沙盒里的后台任务卡（后端 app/jobs.py）。运行中卡片自己轮询 /api/jobs/{id}（lib/jobs.ts）。 */
export type JobState = "running" | "done" | "failed" | "timed_out" | "cancelled" | "lost";
export type JobBlock = { type: "job"; id: string; title: string; command: string; state: JobState;
  started_at?: string | null; finished_at?: string | null; exit_code?: number | null; tail?: string | null;
  /** 被服务器护栏自动停掉的原因（卡住没输出 / 输出过大）；用户或助手取消的没有。 */
  stop_reason?: string | null };
/** /api/jobs/{id} 的快照。followup=pending：结束了，服务器还要在这段对话里接着说一轮。 */
export type JobInfo = { id: string; title: string; command: string; state: JobState; exit_code?: number | null;
  followup: "none" | "pending" | "done" | "seen" | "skipped"; elapsed: number; tail: string;
  started_at?: string | null; finished_at?: string | null; stop_reason?: string | null };
export type Block = TextBlock | LinksBlock | TableBlock | CodeBlock | FileBlock | ApprovalBlock | BrowserBlock | PageBlock | StatsBlock | MemoryBlock
  | DraftBlock | SummaryBlock | ImagesBlock | ProductsBlock | OrderBlock | FormBlock | JobBlock;
export type SitePage = { id: string; slug: string; title: string; url: string; updated: number; published?: boolean; source?: string }; // published 缺省 = 已发布（老服务器）；source = "conversation:<id>" 是分享对话生成的
/** 对话分享状态（/api/conversations/{id}/share）：没 slug = 从没分享；有 slug 但 shared=false = 停止过（再分享原链接恢复）；stale = 快照后对话有新内容。 */
export type ConversationShare = { shared: boolean; stale?: boolean } & Partial<SitePage>;

export type Role = "user" | "assistant";
export type ToolRun = { id: string; name: string; label: string; state: "running" | "done" | "error" };
/** 发件箱状态（只在本机）：queued = 待发送，failed = 发送失败；没有 = 已进服务器。 */
export type Outbox = "queued" | "failed";
/** status 只在不是正常说完时出现：stopped = 用户中途停止，内容是半截的。 */
/** created_at：服务器时间（带时区 ISO）；本地刚发的 = 发出时刻；生成中的占位没有。用于聊天里的日期分隔。 */
/** thought：推理模型的思考（thinking.delta 累积，只留尾部），服务器不存；message.done 时接到正式消息上（本次会话可展开回看）。
 *  thinkFrom/thinkTo：第一段 / 最近一段思考到达的本机时间（ms），算“已思考 N 秒”。 */
export type Message = { id: string; role: Role; blocks: Block[]; status?: "stopped"; pending?: boolean; tools?: ToolRun[]; outbox?: Outbox; created_at?: string; thought?: string; thinkFrom?: number; thinkTo?: number };
/** 对话列表项。snippet + message_id 只在搜索命中正文时出现（见 docs/protocol.md）：打开后定位到那条消息。 */
export type ConversationSummary = { id: string; title: string; pinned: boolean; model?: string | null; updated_at: string; snippet?: string; message_id?: string };

export type ServerEvent =
  | { type: "message.start"; conversation_id: string; user_message_id: string; title: string; replaced?: string[]; user_message?: Message }
  | { type: "block.start"; index: number; block: Block }
  | { type: "block.update"; index: number; block: Block }
  | { type: "block.delta"; index: number; text: string }
  | { type: "thinking.delta"; text: string }
  | ({ type: "tool.status" } & ToolRun)
  | { type: "message.done"; message: Message }
  | { type: "message.stopped"; conversation_id: string }
  | { type: "error"; message: string };

// ---- 其他资源（对应 backend/app/models.py） ----
/** conversation_count / last_active_at：服务器算好的只读字段（旧服务器没有）。 */
/** brief = 项目档案（Markdown 活文档，用户和助手都能改）；brief_by = 最后谁改的。老服务器没有这三个字段。 */
export type Project = { id: string; name: string; emoji: string; rules: string; updated_at: string;
  brief?: string; brief_by?: "user" | "assistant" | null; brief_updated_at?: string | null; conversation_count?: number; last_active_at?: string | null };
export type Memory = { id: string; category: string; content: string; updated_at: string };
export type ScheduledTask = { id: string; name: string; prompt: string; cron: string; active: boolean; output: "report" | "panel"; run_requested: boolean; last_run_at: string | null; last_status: "ok" | "error" | null;
  /** 连着失败几次（成功归零）；paused_reason "failures" = 连续失败被自动暂停，手动停 = null（老服务器没有这两个字段） */
  fail_streak?: number; paused_reason?: string | null;
  /** 服务端算好的下次运行（只读）；停用或 cron 无效 = null */
  next_run_at: string | null;
  /** 一次性任务的时刻（与 cron 二选一，cron 为空串）；重复任务 = null。done：一次性任务已跑过（只读） */
  run_at?: string | null; done?: boolean };
/** 定时任务的一次运行（GET /api/tasks/{id}/runs，新的在前）；conversation_id：报告那次的对话，面板任务或对话已删为 null。 */
export type TaskRun = { id: string; trigger: "schedule" | "manual"; status: "running" | "ok" | "error"; error: string | null; conversation_id: string | null; started_at: string; finished_at: string | null; duration_ms: number | null };
export type HomeCard = { id: string; kind: "action" | "panel" | "report"; conversation_id: string | null; task_id: string | null; title: string; blocks: Block[]; action_prompt: string | null; target: string | null;
  /** 主按钮上的字，空 = “去做”；origin "agent" = 助手提议的卡：点主按钮 POST /api/cards/{id}/start，
   *  之后 conversation_id 指向开出来的对话（卡变成“已交给助手 · 查看对话”），见 backend app/home_offers.py */
  action_label?: string | null; origin?: string | null;
  /** 建议卡卡顶配图 / 原页链接（只认 http(s)，见 features/home/OfferMedia.tsx）。旧服务器没有。 */
  image_url?: string | null; link_url?: string | null; dismissed: boolean; unread: boolean; updated_at: string;
  /** 稍后提醒到这个时刻：非空就先不显示，到点服务端放回（清空 + 重新未读）。旧服务器没有这个字段。 */
  snoozed_until?: string | null;
  /** 报告卡的“一眼”：摘要卡标题 + 一句话（backend app/report_gist.py；拼法见 lib/reportGlance.ts）。旧服务器没有。 */
  headline?: string | null; gist?: string | null };
export type InboxItem = { id: string; kind: HomeCard["kind"]; title: string; conversation_id: string | null; created_at: string;
  headline?: string | null; gist?: string | null };
export type InboxSummary = { unread: number; latest: InboxItem | null };
/** builtin = 内置原样（只读）；customized = 内置的自定义版（同 id 顶替内置，可改、可恢复默认）；都 false = 自己写的。
 * enabled = false：停用，留在库里但模型看不到（旧服务器没有这个字段 = 启用）。 */
export type Skill = { id: string; name: string; description: string; body: string; builtin: boolean; customized?: boolean; enabled?: boolean };
export type Upload = { id: string; name: string; mime: string; size: number };
/** 一条消息要带的文件：刚上传的（Upload）或引用的项目文件（source=project 的 FileBlock）。 */
export type OutgoingFile = Upload | FileBlock;
export type ProjectFile = { path: string; name: string; size: number; mime: string; modified: number };
export type Connector = { id: string; name: string; desc: string; logo: string; configured: boolean; account: string | null };
/** problem：还没恢复的问题 "auth"（令牌被拒）| "down"（连不上）| null（规则见后端 connectors/mcp.py）。 */
export type McpServerInfo = { id: string; name: string; url: string; has_token: boolean; problem?: string | null };
export type VaultSecret = { id: string; kind: "api_key" | "login"; name: string; username: string | null; hosts: string[]; header_name: string; header_prefix: string; preview: string; created_at: string };


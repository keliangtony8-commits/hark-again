// 与 backend/app/blocks.py 一一对应：这是前后端唯一契约
export type TextBlock = { type: "text"; text: string };
export type LinksBlock = { type: "links"; items: { url: string; label?: string; title?: string }[] };
export type TableBlock = { type: "table"; title?: string; columns: string[]; rows: string[][]; note?: string };
export type CodeBlock = { type: "code"; language?: string; title?: string; source: string };
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
export type Block = TextBlock | LinksBlock | TableBlock | CodeBlock | FileBlock | ApprovalBlock | BrowserBlock | PageBlock | StatsBlock | MemoryBlock
  | DraftBlock | SummaryBlock | ImagesBlock | ProductsBlock | OrderBlock;
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
  /** 服务端算好的下次运行（只读）；停用或 cron 无效 = null */
  next_run_at: string | null;
  /** 一次性任务的时刻（与 cron 二选一，cron 为空串）；重复任务 = null。done：一次性任务已跑过（只读） */
  run_at?: string | null; done?: boolean };
/** 定时任务的一次运行（GET /api/tasks/{id}/runs，新的在前）；conversation_id：报告那次的对话，面板任务或对话已删为 null。 */
export type TaskRun = { id: string; trigger: "schedule" | "manual"; status: "running" | "ok" | "error"; error: string | null; conversation_id: string | null; started_at: string; finished_at: string | null; duration_ms: number | null };
export type HomeCard = { id: string; kind: "action" | "panel" | "report"; conversation_id: string | null; task_id: string | null; title: string; blocks: Block[]; action_prompt: string | null; target: string | null; dismissed: boolean; unread: boolean; updated_at: string;
  /** 稍后提醒到这个时刻：非空就先不显示，到点服务端放回（清空 + 重新未读）。旧服务器没有这个字段。 */
  snoozed_until?: string | null };
export type InboxItem = { id: string; kind: HomeCard["kind"]; title: string; conversation_id: string | null; created_at: string };
export type InboxSummary = { unread: number; latest: InboxItem | null };
/** builtin = 内置原样（只读）；customized = 内置的自定义版（同 id 顶替内置，可改、可恢复默认）；都 false = 自己写的。
 * enabled = false：停用，留在库里但模型看不到（旧服务器没有这个字段 = 启用）。 */
export type Skill = { id: string; name: string; description: string; body: string; builtin: boolean; customized?: boolean; enabled?: boolean };
export type Upload = { id: string; name: string; mime: string; size: number };
export type ProjectFile = { path: string; name: string; size: number; mime: string; modified: number };
export type Connector = { id: string; name: string; desc: string; logo: string; configured: boolean; account: string | null };
export type McpServerInfo = { id: string; name: string; url: string; has_token: boolean };
export type VaultSecret = { id: string; kind: "api_key" | "login"; name: string; username: string | null; hosts: string[]; header_name: string; header_prefix: string; preview: string; created_at: string };


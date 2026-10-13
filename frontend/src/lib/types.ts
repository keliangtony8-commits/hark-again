import type { RetryNotice } from "./retry";
// 与 backend/app/blocks.py 一一对应：这是前后端唯一契约
export type TextBlock = { type: "text"; text: string };
export type LinksBlock = { type: "links"; items: { url: string; label?: string; title?: string }[] };
export type TableBlock = { type: "table"; title?: string; columns: string[]; rows: string[][]; note?: string };
/** live：命令还在跑，source 是最近的输出（服务器 block.update 原地换），跑完换成不带 live 的最终块。 */
export type CodeBlock = { type: "code"; language?: string; title?: string; source: string; live?: boolean };
/** v1.81 用户消息里 `$技能` 点名的技能（后端 app/skill_mentions.py）：只有 id + 名字，气泡上方一枚小标签。 */
export type SkillBlock = { type: "skill"; id: string; name: string };
/** v1.91 用户消息里 `@子助手` 点名交给子助手（后端 app/agent_mentions.py）：气泡上方一枚标签。 */
/** v1.91 `@子助手`；v1.97 追问：target = 子助手编号、title = 子任务标题、gone = 它的上下文已经不在了。 */
export type AgentBlock = { type: "agent"; id?: string; name?: string; target?: string | null; title?: string | null; gone?: boolean | null };
export type FileBlock = { type: "file"; source: "upload" | "project"; id: string; name: string; mime: string; size: number; project_id?: string | null };
/** 审批卡。主机命令卡（v1.49 target = host）多带机器名、note（为什么要你看一眼；warn = 危险提示）、批准范围 options（第一个 = 批准按钮）、批准后 granted。 */
export type ApprovalOption = { id: string; label: string };
export type ApprovalBlock = {
  type: "approval"; id: string; title: string; detail: string; state: "pending" | "approved" | "rejected" | "expired";
  target?: "sandbox" | "host" | null; host?: string | null; note?: string | null; warn?: boolean;
  options?: ApprovalOption[]; granted?: string | null;
};
/** 云浏览器实时画面：session = 按网站起的会话名（旧卡 main），site = 网站，live = 还在打开（v1.26）。 */
/** 助手请你接管浏览器（backend browser_handoff）：pending → done / cancelled / expired；交还 = form.reply（id 即它）。 */
export type BrowserHandoff = { id: string; reason: string; state: "pending" | "done" | "cancelled" | "expired" };
/** 浏览器和工作区之间搬过的文件（v1.32，backend app/browser_files.py）：upload = 传到网页上的工作区文件，download = 网页下载、存进工作区的。 */
export type BrowserFile = { kind: "upload" | "download"; name: string; path: string };
export type BrowserBlock = {
  type: "browser"; session: string; site?: string; live?: boolean; handoff?: BrowserHandoff | null;
  files?: BrowserFile[]; workspace?: string | null;
};
export type PageBlock = { type: "page"; slug: string; title: string; url: string };
/** 端口预览（v1.30，app/preview.py）：工作区里跑着的网页服务，链接带期限。 */
export type PreviewBlock = { type: "preview"; workspace: string; port: number; url: string; title?: string | null; command?: string; expires_at?: string | null };
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
/** options = 可点选的候选（点了填进框，仍可改）；optional = 选填；min_length = 至少几个字符（要环境变量卡）。 */
export type FormInput = { name: string; label: string; kind?: "text" | "email" | "password" | "code" | "phone" | "multiline"; value?: string | null;
  options?: string[] | null; optional?: boolean; min_length?: number | null };
/** note = 为什么问；answers 只有 info 卡提交后才有（用户有意告诉助手的，login/code/env 的值从不进卡片；
 *  env = request_env 要的命令环境变量，值只存进保险箱）。 */
export type FormBlock = { type: "form"; id: string; purpose?: "login" | "code" | "info" | "env"; title: string; site?: string | null;
  fields: FormInput[]; remember?: boolean; action?: string; state: "pending" | "submitted" | "cancelled" | "expired";
  note?: string | null; answers?: { label: string; value: string }[] | null };
/** 填了但不够长（空着不算，空着归必填规则）。 */
export const tooShort = (f: FormInput, v: string) => !!v.trim() && v.length < (f.min_length ?? 0);
/** 填好了没有：必填不空、填了的够长。 */
export const formComplete = (b: FormBlock, values: Record<string, string>) =>
  b.fields.every((f) => (f.optional || (values[f.name] ?? "").trim()) && !tooShort(f, values[f.name] ?? ""));
/** 输入框下那行“你填的去哪了”。 */
export const formPrivacy = (purpose: FormBlock["purpose"]) =>
  purpose === "info" ? "你填的内容会交给助手，用来接着办这件事"
    : purpose === "env" ? "只存进保险箱，助手只知道名字；在 我的 → 保险箱 里可以换值或删除"
    : "只交给浏览器填写，助手看不到";
/** 项目沙盒里的后台任务卡（后端 app/jobs.py）。运行中卡片自己轮询 /api/jobs/{id}（lib/jobs.ts）。 */
export type JobState = "running" | "done" | "failed" | "timed_out" | "cancelled" | "lost";
export type PlanStatus = "pending" | "in_progress" | "completed";
export type PlanItem = { content: string; status: PlanStatus };
/** 计划清单（v1.47，后端 app/plan.py）：一条回复一张，助手边做边勾；settled = 这一轮已结束。 */
export type PlanBlock = { type: "plan"; items: PlanItem[]; explanation?: string | null; settled?: boolean };
export type DelegateState = "running" | "done" | "partial" | "failed" | "stopped";
export type DelegateTask = { id?: string | null; round?: number | null; title: string; state: DelegateState; steps?: number; now?: string | null; seconds?: number | null;
  result?: string | null; note?: string | null };
/** 子助手（v1.48，后端 agent/subagent.py）：一次并行派出的几个子任务；live = 还在跑。 */
export type DelegateBlock = { type: "delegate"; tasks: DelegateTask[]; live?: boolean | null };
/** 用户自己跑的命令（v1.77，输入框 !命令，后端 app/user_shell.py；不经过助手）。一条回复里只有它一张。 */
export type ShellState = "running" | "done" | "failed" | "timeout" | "stopped" | "refused" | "error";
export type ShellBlock = { type: "shell"; command: string; state: ShellState; output: string; exit_code?: number | null;
  seconds?: number | null; note?: string | null };
export type JobBlock = { type: "job"; id: string; title: string; command: string; state: JobState;
  started_at?: string | null; finished_at?: string | null; exit_code?: number | null; tail?: string | null;
  /** 被服务器护栏自动停掉的原因（卡住没输出 / 输出过大）；用户或助手取消的没有。 */
  stop_reason?: string | null;
  /** v1.80 常驻任务（后端 app/job_restart.py）：意外退出自动重启；restarts = 重启过几次。 */
  keep_alive?: boolean | null; restarts?: number | null;
  /** v1.92 给它单独定的内存上限 / 结束时的内存峰值（字节，后端 app/job_memory.py）。 */
  memory_max?: number | null; memory_peak?: number | null;
  /** v1.96 结算时的磁盘账（后端 app/job_disk.py）。 */
  disk?: JobDisk | null;
  /** v2.04 前台命令到点没跑完、转进后台接着跑的（后端 jobs.adopt）。 */
  promoted?: boolean | null };
/** /api/jobs/{id} 的快照。followup=pending：结束了，服务器还要在这段对话里接着说一轮。 */
export type JobInfo = { id: string; title: string; command: string; state: JobState; exit_code?: number | null;
  followup: "none" | "pending" | "done" | "seen" | "skipped"; elapsed: number; tail: string;
  started_at?: string | null; finished_at?: string | null; stop_reason?: string | null;
  /** v1.80 常驻：restart_at 不为空 = 进程刚退出、等这个时刻重启（state 仍是 running）。老服务器没有这三个字段。 */
  keep_alive?: boolean; restarts?: number; restart_at?: string | null;
  /** v1.90 现在占多少（后端 app/job_usage.py）：进程确实在跑、问得到沙盒才有；null/缺 = 不知道（不是 0）。cpu = 占配额 %。 */
  usage?: JobUsage | null;
  /** v1.92 内存上限 / 峰值（字节）；box = 整台沙盒此刻的内存（在跑才有），快满了卡片提醒。 */
  memory_max?: number | null; memory_peak?: number | null; box?: JobBox | null;
  /** v1.96 磁盘账：运行中现数（服务器缓存 30 秒），结束了是结算时的；null = 没数。 */
  disk?: JobDisk | null;
  /** v2.04 前台命令转进后台的（老服务器没有这个字段）。 */
  promoted?: boolean };
/** v1.96 日志 + 运行期间工作区里新写或改过的文件（按顶层条目分组，最多 3 组）；overlap = 同时段还在跑的其他任务数。 */
export type JobDisk = { log: number; written: number; files: number; top: { path: string; size: number }[]; overlap: number; partial: boolean };
export type JobBox = { used: number; limit: number };
export type JobUsage = { cpu: number; cpu_seconds: number; memory: number; processes: number };
export type Block = TextBlock | LinksBlock | TableBlock | CodeBlock | FileBlock | ApprovalBlock | BrowserBlock | PageBlock | StatsBlock | MemoryBlock
  | DraftBlock | SummaryBlock | ImagesBlock | ProductsBlock | OrderBlock | FormBlock | JobBlock | PreviewBlock | PlanBlock | DelegateBlock | ChangesBlock | PlanReviewBlock | ShellBlock | SkillBlock | AgentBlock;
export type SitePage = { id: string; slug: string; title: string; url: string; updated: number; published?: boolean; source?: string }; // published 缺省 = 已发布（老服务器）；source = "conversation:<id>" 是分享对话生成的
/** 对话分享状态（/api/conversations/{id}/share）：没 slug = 从没分享；有 slug 但 shared=false = 停止过（再分享原链接恢复）；stale = 快照后对话有新内容。 */
export type ConversationShare = { shared: boolean; stale?: boolean } & Partial<SitePage>;

export type Role = "user" | "assistant";
/** 活动时间线的一步（v1.28，backend/app/activity.py）：每次工具调用一步，随消息落库（Message.steps）。 */
/** 这一步改了工作区文件（v1.34 write_file / edit_file；形状见 backend/app/file_edit.py）。hidden = 像密钥的文件，不给 diff。 */
export type FileChange = { path: string; added: number; removed: number; diff: string; created?: boolean; hidden?: boolean; big?: boolean; deleted?: boolean; moved_from?: string; command?: boolean;
  /** v2.16 权限变了的那句话（后端 turn_changes.mode_note：“加了可执行”…），原样显示 */ mode?: string | null };
/** v1.68 这一轮改过的文件（后端 app/turn_changes.py）：token 非空 = 能整轮撤销。 */
/** v1.71 计划模式下交给你批准的方案（后端 app/plan_mode.py）：批准 / 再改改走 approval.reply。 */
/** workspace + path（v1.72）= 批准后方案存进工作区的位置（老卡没有）。 */
export type PlanReviewBlock = { type: "plan_review"; id: string; title: string; plan: string; state: "pending" | "approved" | "rejected" | "expired"; workspace?: string; path?: string };
export type ChangesBlock = { type: "changes"; token: string; files: FileChange[]; more?: number | null; undone?: boolean | null };
export type ActivityStep = { id: string; tool: string; title: string; detail: string; state: "running" | "done" | "error" | "denied" | "stopped"; at?: string; ms?: number; note?: string; change?: FileChange; changes?: FileChange[] };
/** WS tool.status：step = 完整的一步（老服务器没有）。 */
export type ToolRun = { id: string; name: string; label: string; state: ActivityStep["state"]; step?: ActivityStep };
/** 发件箱状态（只在本机）：queued = 待发送，failed = 发送失败；没有 = 已进服务器。 */
export type Outbox = "queued" | "failed";
/** status 只在不是正常说完时出现：stopped = 用户中途停止；interrupted = 服务器进程中途没了（崩溃/重启），内容是半截的；
 *  wrapped = 步数/用量预算用完收尾；looped = 原地打转被叫停（v1.56，内容完整但事没做完）。 */
/** created_at：服务器时间（带时区 ISO）；本地刚发的 = 发出时刻；生成中的占位没有。用于聊天里的日期分隔。 */
/** thought：推理模型的思考（thinking.delta 累积，只留尾部），服务器不存；message.done 时接到正式消息上（本次会话可展开回看）。
 *  thinkFrom/thinkTo：第一段 / 最近一段思考到达的本机时间（ms），算“已思考 N 秒”。 */
export type Message = { id: string; role: Role; blocks: Block[]; status?: "stopped" | "interrupted" | "wrapped" | "looped" | "steer"; pending?: boolean; steps?: ActivityStep[]; outbox?: Outbox; created_at?: string; thought?: string; thinkFrom?: number; thinkTo?: number;
  /** 模型调用失败在自动重试 / 已换备用模型（v1.50 turn.retry，lib/retry.ts）：只在生成中的占位消息上。 */
  retry?: RetryNotice };
/** 对话列表项。snippet + message_id 只在搜索命中正文时出现（见 docs/protocol.md）：打开后定位到那条消息。 */
export type ConversationSummary = { id: string; title: string; pinned: boolean; model?: string | null; reasoning?: string | null; routed_model?: string | null; mode?: string | null; updated_at: string; snippet?: string; message_id?: string };

/** v1.61 续传：一轮里的事件都带 turn_id + 从 1 起连续的 seq（老服务器没有）。 */
export type TurnCursor = { turn_id?: string; seq?: number };
export type ServerEvent = TurnCursor & (
  | { type: "message.start"; conversation_id: string; user_message_id: string; title: string; replaced?: string[]; user_message?: Message; client_id?: string }
  /** 回答途中补充（v1.83 steering）：服务器收下了一句，并进正在跑的这一轮；client_id = 发起那台设备的本地 id。 */
  | { type: "turn.steered"; conversation_id: string; message: Message; client_id?: string }
  | { type: "block.start"; index: number; block: Block }
  | { type: "block.update"; index: number; block: Block }
  | { type: "block.delta"; index: number; text: string }
  | { type: "thinking.delta"; text: string }
  | { type: "turn.model"; model: string; label?: string; complexity?: string; source?: string; reason?: string }
  | { type: "turn.retry"; attempt: number; max: number; delay_ms: number; reason: string; code?: string; fallback?: string; fallback_label?: string }
  | ({ type: "tool.status" } & ToolRun)
  | { type: "message.done"; message: Message }
  | { type: "message.stopped"; conversation_id: string }
  /** v1.67：第一轮回复后服务器在后台起好的短标题（在 message.done 之后到达） */
  | { type: "conversation.title"; conversation_id: string; title: string }
  | { type: "conversation.mode"; conversation_id: string; mode: string }
  | { type: "error"; message: string }
  /** 对 turn.resume 的答复：live=false = 没这轮（以 GET 为准）；gap = 游标太旧，随后来 turn.snapshot */
  | { type: "turn.resumed"; turn_id: string | null; conversation_id: string | null; live: boolean; ended?: boolean; gap?: boolean }
  /** 折叠好的“到目前为止”：整份替换生成中的那条 */
  | { type: "turn.snapshot"; turn_id: string; seq: number; conversation_id: string | null; message: { blocks: Block[]; steps: ActivityStep[] }; steered?: Message[] });

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
  run_at?: string | null; done?: boolean;
  /** 每次运行用的模型别名 / 思考强度（null = 默认；老服务器没有） */
  model?: string | null; reasoning?: string | null;
  /** v1.84 定时脚本：kind "script" = prompt 是 shell 命令，到点直接在工作区跑、不调模型；notify 何时告诉（failure | always | change）；
   *  project_id 在哪个项目的工作区跑（null = 我的文件）。老服务器没有 = agent / failure。 */
  kind?: "agent" | "script"; notify?: "failure" | "always" | "change"; project_id?: string | null;
  /** v2.13 助手记下的做法 / 观察（每次运行开头读到，后端 app/task_brief.py）；skipped_at 被跳过的那次（还没到的才有）。老服务器没有 */
  runbook?: string | null; note?: string | null; skipped_at?: string | null;
  /** v2.15 碰壁（后端 app/task_wall.py）：最近一次运行碰到的障碍一句话 + 经过；wall_fixable 要你处理；wall_open 去哪页（cardTargets 键）。
   *  只读服务端给的这几个，不解析 wall 字符串。没碰壁 / 老服务器 = null */
  wall?: string | null; wall_label?: string | null; wall_reason?: string | null; wall_fixable?: boolean; wall_open?: string | null };
/** 定时任务的一次运行（GET /api/tasks/{id}/runs，新的在前）；conversation_id：报告那次的对话，面板任务或对话已删为 null。 */
export type TaskRun = { id: string; trigger: "schedule" | "manual"; status: "running" | "ok" | "error"; error: string | null; conversation_id: string | null; started_at: string; finished_at: string | null; duration_ms: number | null;
  /** 定时脚本这次跑的后台任务（没开对话时点开看日志）；老服务器没有 */
  job_id?: string | null;
  /** v2.13 这次没东西可报、没打扰你的一句原因（不进收件箱）；说了话 = null。老服务器没有 */
  silent_reason?: string | null;
  /** v2.15 这次碰的壁（一句话；error 里是“壁：经过”）；没碰壁 = null */
  wall?: string | null; wall_label?: string | null };
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
export type VaultSecret = { id: string; kind: "api_key" | "login" | "env"; name: string; username: string | null; hosts: string[]; header_name: string; header_prefix: string; preview: string; created_at: string };


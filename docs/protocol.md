# 客户端协议（所有客户端共用的唯一契约）

后端只通过这份协议和客户端对话。Flutter App（安卓/iOS）、网页版都按它实现，互不依赖。
改协议 = 先改这份文档和 `backend/app/blocks.py`，再改各端。机器可读版本：`GET /openapi.json`。

## 1. 鉴权
- `POST /api/auth/login` `{username, password}` → `{token}`（JWT）
- REST：请求头 `Authorization: Bearer <token>`
- WebSocket、图片/下载地址（带不了请求头）：`?token=<token>`
- 401 → 客户端清掉 token 回登录页

## 2. 聊天（WebSocket `/ws?token=`）

> 客户端约定：连接断了就退避重连；断线期间用户发的消息在客户端标“待发送”，连上再发 `user.message`；回复中途断线时，连上后 `GET /api/conversations/{id}` 补全（服务器照常落库）。`approval.reply`、`message.regenerate` 不排队。服务器按到达顺序一轮接一轮处理（不会丢掉刚结束时立刻发来的下一条）。
> 重新生成：客户端先在本地撤掉旧回复；收到 `error` 或回复开始前断线 → `GET /api/conversations/{id}` 以服务器为准。
> 停止：生成中发 `message.cancel`，停止键置灰，等服务器回 `message.done`（半截回复，`status: "stopped"`）或 `message.stopped`（还没吐字）再收尾；客户端不在本地先砍。断线 = 服务器也停下并把半截落库（`status: "stopped"`），重连后 `GET` 能看到。
> 复制：纯客户端，把回复的块转成 Markdown（text 原样、code 加围栏、table 转 Markdown 表、links 列表；审批/浏览器等过程卡片不复制）。
> 编辑：只能改最后一条用户消息（已在服务器上、不在生成中）。客户端先本地改气泡、撤掉后面的回复，再用 `message.start.user_message` 覆盖；被拒/断线同“重新生成”。
客户端 → 服务器：
| type | 字段 | 说明 |
|---|---|---|
| `user.message` | `text`, `conversation_id?`, `project_id?`, `attachments?: [uploadId]`, `model?` | 发一条消息；一次只跑一轮。`model` = 这个对话改用的模型别名（`GET /api/catalog/models` 里的 id；`""` = 回默认；不认识的忽略），记到对话上、本轮起生效。客户端只在本机改过且还没 PATCH 成功（或新对话）时带 |
| `message.regenerate` | `conversation_id`, `message_id?`, `text?`, `model?` | 重新生成最后一条回复：删掉最后一条用户消息之后的回复，同一条用户消息再跑一轮（不保留旧版本）。`message_id` = 客户端眼中的最后一条回复，不是最新的就回 `error`、什么都不删；不带 = 上一轮失败没有回复时“重试”。带 `text` = **编辑**：最后一条用户消息的文字原地换成它（id 不变、附件保留、标题不动；文字空且没附件 → `error`）再答。带 `model` = 换模型重答（同 user.message，记到对话上）。不排队，线不通直接提示 |
| `message.cancel` | `conversation_id?` | 停止正在生成的这一轮。带 id 就必须对得上正在跑的对话；没有在跑的轮次就忽略（刚好已说完）。不排队 |
| `approval.reply` | `id`, `approved: bool` | 回答审批卡 |

服务器 → 客户端（一轮的顺序）：
| type | 字段 | 说明 |
|---|---|---|
| `message.start` | `conversation_id`, `user_message_id`, `title`, `replaced?: [id]`, `user_message?: {id, role, blocks, created_at?}` | 新对话时用它拿到 id；重新生成时 `replaced` = 被删的旧回复；编辑时 `user_message` = 改好的用户消息（客户端用它覆盖本地气泡） |
| `block.start` | `index`, `block` | 新增第 index 个块 |
| `block.delta` | `index`, `text` | 追加文字到第 index 个 text 块 |
| `block.update` | `index`, `block` | 整块替换（审批卡状态变化） |
| `tool.status` | `id`, `name`, `label`, `state: running\|done` | 工具进度条 |
| `message.done` | `message: {id, role, blocks, status?, created_at?}` | 一轮结束，以它为准落盘。`status: "stopped"` = 被停止的半截回复（等待中的审批卡变 `expired`） |
| `message.stopped` | `conversation_id` | 还没产出任何内容就被停止：不存回复，用户消息留着（可“重试”） |
| `error` | `message` | 本轮失败 |

## 3. 消息块（`blocks.py` 是定义源）
每条消息 = `blocks: Block[]`，按 `type` 区分。客户端遇到不认识的 type 必须忽略，不能崩。
| type | 字段 |
|---|---|
| `text` | `text`（Markdown，含表格） |
| `links` | `items: [{url, label?, title?}]` |
| `table` | `title?`, `columns[]`, `rows[][]`, `note?` |
| `code` | `language`, `title?`, `source` |
| `file` | `source: upload\|project`, `id`, `name`, `mime`, `size`, `project_id?` |
| `approval` | `id`, `title`, `detail`, `state: pending\|approved\|rejected\|expired` |
| `browser` | `session`（实时画面：`GET /api/browser/screen?token=` 轮询；接管：`POST /api/browser/mouse {x,y}` 0–1 归一化坐标，`POST /api/browser/keyboard {text?, key?}`） |
| `page` | `slug`, `title`, `url` |
| `stats` | `items: [{label, value, note?}]`（1–6 项；关键数字小卡片，标签 + 大数字 + 一句变化；模型用 `show_stats` 工具产出，面板刷新优先用它） |

文件地址：upload → `/api/uploads/{id}?token=`；project → `/api/projects/{project_id}/files/{id}?token=`

## 4. REST 资源
统一形状：列表 `GET`，新建 `POST`，改 `PATCH`，删 `DELETE`，每项都有 `id`。
| 资源 | 路径 | 备注 |
|---|---|---|
| 对话 | `/api/conversations` | `GET ?q=&project_id=` 搜标题+内容（置顶在前，内容命中带 `snippet` + `message_id`＝最近一条命中的消息，客户端打开后滚到它并闪一下；标题命中两者都不带）；`PATCH /{id} {title?, pinned?, model?}` 不改 `updated_at`（`model` 非法 422，`""` = 回默认）；列表项和详情都带 `model`（`null` = 默认）；`GET /{id}` 返回 messages（每条 `{id, role, blocks, status?, created_at?}`，`status` 只在 `stopped` 时出现；`created_at` 是带时区的 ISO 时间（v0.45 起，客户端按本地日期画日期分隔，没有就不画）） |
| 项目 | `/api/projects` | `brief` = 项目档案（Markdown，≤8000 字，超出 422；PATCH 时去首尾空白，内容真变了才把 `brief_by` 设为 `user`、`brief_updated_at` 设为现在；助手用 `project_brief` 工具改时 `brief_by=assistant`；老服务器没有这三个字段）；只读 `conversation_count`（项目内对话数）、`last_active_at`（项目或其中任一对话的最后更新）；文件：`/api/projects/{pid}/files[/{path}]`（multipart 上传） |
| 记忆 | `/api/memories` | 每项 `{id, category, content, created_at, updated_at}`；`category` 常用 `profile\|food\|travel\|work\|shopping\|general`，客户端认识的显示中文名、不认识的原样显示。搜索、分类筛选都在客户端做（记忆全量已在列表里） |
| 我对你的了解 | `/api/memory-digest` | `GET` → `{text\|null, generated_at\|null, count（生成时的记忆数）, memories（现在的记忆数）, stale}`，零模型调用；`stale` = 生成后记忆有增删改。`POST` 用便宜模型重写一次（记账 kind=digest）返回同样形状；没有记忆 → 删掉旧概括返回 text=null；模型失败 502，旧概括不动。客户端从不自动 POST（花 token），只在用户点“生成/更新”时调 |
| 定时任务 | `/api/tasks` | 计划二选一：`cron`（重复，5 段，用户时区）或 `run_at`（一次性，ISO 时间，此时 `cron` 为 `""`），两者都给/都不给/cron 无效 → 422；PATCH 合并后同样校验，换成一次性传 `{run_at, cron: ""}`、换回重复传 `{cron, run_at: null}`；`done`（只读）= 一次性任务已跑过（last_run_at ≥ run_at），此时 `next_run_at` 为 null，把 run_at 改到以后即重新排上，“立即运行”不消耗这次提醒；`output: report\|panel`（面板 = output=panel 的任务 + 一张 kind=panel 的卡；PATCH 改面板任务的 `name` 时服务端同步改卡片 `title`，客户端编辑面板只 PATCH 任务）；`last_status: ok\|error\|null`（上一次结束的运行）；`next_run_at`（只读，服务端按 cron + 用户时区算好的下次运行，与 worker 同一套计算；停用或 cron 无效为 null；过期未跑显示为现在）；`POST /{id}/run` 立即运行；`GET /{id}/runs?limit=1..30` 最近运行记录，新的在前：`[{id, trigger: schedule\|manual, status: running\|ok\|error, error, conversation_id（报告那次的对话；面板或对话已删为 null）, started_at, finished_at, duration_ms}]`，任务不存在 404 |
| Home 卡片 | `/api/cards` | `kind: action\|panel\|report`；面板刷新 = 对其 `task_id` 调 run；`unread` 新报告/新建议为 true（面板刷新不算）；`target` 可选，客户端里的固定去处（目前只有 `usage` = 用量页，显示“查看用量”按钮），不认识的值忽略。预算提醒就是一张 `kind=action, target=usage` 的卡 |
| 收件箱 | `/api/inbox` | `GET` → `{unread, latest: {id,kind,title,conversation_id,created_at}\|null}`（轮询用，很轻）；`POST /read {ids?}` 不传 ids = 全部已读，返回同样的摘要。`GET /api/conversations/{id}` 会顺带把该对话的报告标为已读 |
| 模型 | `GET /api/catalog/models` | → `{default, models: [{id, label}]}`（服务器 CHAT_MODELS，顺序即切换顺序）。客户端缓存、不足两项不显示切换；对话的 `model` 不在列表里时按默认显示（服务器也回落到默认） |
| 技能 | `/api/catalog/skills` | 内置技能 `builtin: true` 不可改不可删；`customized: true` = 内置的自定义版（同 id，可 PUT）。`POST /{id}/customize` 复制内置为自定义版（已有则原样返回），`POST /{id}/reset` 恢复内置原文，两者都返回该技能；DELETE 只用于自己写的（内置 400，不存在 404）；POST 新建的 id 自动避开已有 id；每条带 `enabled`（缺省视为 true），`POST /{id}/enable` / `POST /{id}/disable` 开关并返回该技能，停用的仍在列表里但不进模型的技能目录、use_skill 拒绝；开关按 id 记，customize/reset 不改变它，删除用户技能时清掉 |
| 连接器 | `/api/connectors` | `GET /{provider}/start?client=web\|app` → `{url}`，客户端在浏览器打开；见下方「授权回跳」 |
| MCP | `/api/connectors/mcp` | |
| 保险箱 | `/api/vault` | `kind: api_key\|login`；永不返回明文 |
| Pages | `/api/pages` | 每项 `{id(=slug), slug, title, updated, published, url}`；公开地址 `/p/{slug}/`（`Cache-Control: no-cache`）。`PATCH /{slug} {title?, published?}`：`published=false` = 下线（文件留着、公开地址 404，与不存在同一响应），`true` = 重新发布、链接不变；改名/上下线都不动 `updated`；空标题 422，不存在 404。智能体改写下线的页面只改内容、仍是下线（工具结果会提示用户去重新发布）。老服务器没有 `published` → 客户端按已发布处理 |
| 上传 | `POST /api/uploads` | multipart `file` → `{id, name, mime, size}` |
| 语音 | `POST /api/voice/transcribe` | multipart `file` → `{text}` |
| 用量 | `GET /api/usage` | → `{currency, budget\|null, priced: [别名], today, month, daily}`，每段 `{calls, tokens, cost, models: [{model, calls, prompt_tokens, completion_tokens, cost}]}`（按 cost、token 降序）；“今天/本月”按服务器 TIMEZONE 切；没定价的别名 cost=0，客户端据 priced 显示“未定价”；`daily: [{date: "YYYY-MM-DD", calls, tokens, cost}]` 本月 1 号到今天每天一项（按 TIMEZONE 分天，空天补 0，升序），客户端按整月排格子；老服务器没有此字段时客户端不画图；`conversations: [{id, title\|null, calls, tokens, cost}]` 本月最花钱的对话（按 cost、再按 token 降序，最多 5 个；不归属对话的调用不算；对话已删 title=null，客户端显示“已删除的对话”且不可点；老服务器没有 → 不显示）；`last_month: {calls, tokens, cost, to_date: {calls, tokens, cost}}` 上个月全月合计 + 同期（上月 1 号 0 点到上月同一天同一时刻，按 TIMEZONE 日历对齐；上月没有这一天 → 同期 = 全月），客户端用“本月至今 ÷ 上月同期 − 1”显示涨跌（有定价按钱否则 token；同期为 0 不显示百分比；老服务器没有 → 不显示） |
| 某天用量 | `GET /api/usage/days/{date}` | `date` = `YYYY-MM-DD`（服务器 TIMEZONE 的本地日期，格式不对 422）→ `{currency, priced, date, total, conversations}`，total 同上面的分段形状，conversations 同报表的 conversations（那天窗口内最花钱的前 5 个对话，已删 title=null）；窗口是本地 0 点到次日 0 点，与 daily 的分桶同一条边界（柱子的数 = total 的数）；任何日期都能查，没用量全 0。客户端在用量图上“选定”某天时取（今天也取，因为报表里没有今天的对话；请求途中先用报表的 today 画模型行） |
| 分享对话 | `/api/conversations/{id}/share` | 只读网页快照（v0.63）：`GET` → `{shared:false}`（从没分享）或 Pages 项 `{id, slug, title, updated, published, url, source:"conversation:<id>"}` + `shared`（= published）+ `stale`（快照之后对话有新消息）；`POST`（无 body）生成或更新快照并公开，同一对话 slug 不变（停止过的也恢复）；`DELETE` 停止分享 = 页面下线（链接保留）。对话不存在 404。页面同时出现在 `/api/pages`；快照不含审批卡、浏览器画面，附件只写文件名 |
| 本对话用量 | `GET /api/conversations/{id}/usage` | → `{currency, priced, total}`，total 同上面的分段形状；累计这个对话的所有调用（回复、滚动摘要、记忆向量等）；对话不存在 404；删对话不删用量行（月度总账不变）。客户端在换对话和一轮回复结束时取 |
| 健康 | `GET /api/health` | 登录页“测试连接”用 |

## 5. 客户端约定
- 服务器地址由用户在登录页填写（自建，没有固定域名）
- 错误体：`{detail: string}`，直接展示给用户
- 时间：ISO 8601 带时区；展示用用户本地时区
- 新消息提醒（没有推送时）：回到前台立刻、前台时每 2 分钟拉一次 `/api/inbox`；`latest.id` 变了且未读数增加 → 端内横幅 + Home 角标。后台不轮询（省电、省钱）

## 授权回跳（OAuth）
第三方回调 `GET /api/oauth/callback`（公开，靠签名 state 验真；state 里记着发起端 `client`，只能是 `web` / `app`）。结果统一是同一条路由 `/me/connectors` 加查询参数 `connected=<provider>` 或 `error=<原因>`：
- `web`：302 到 `/#/me/connectors?…`
- `app`：返回一个小页面，自动跳 `<APP_SCHEME>://app/me/connectors?…`（默认 scheme `myassistant`），并给“回到 App”按钮兜底（有的浏览器不允许无手势跳自定义 scheme）。App 用系统深链接收，go_router 直接把 path+query 当路由打开。

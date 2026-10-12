# 客户端协议（所有客户端共用的唯一契约）

后端只通过这份协议和客户端对话。Flutter App（安卓/iOS）、网页版都按它实现，互不依赖。
改协议 = 先改这份文档和 `backend/app/blocks.py`，再改各端。机器可读版本：`GET /openapi.json`。

## 1. 鉴权
- `POST /api/auth/login` `{username, password}` → `{token}`（JWT）
- `GET /api/auth/me` → `{username}`（当前主人；“我的”页页头身份行用。老服务器没有 → 客户端只显示服务器域名）
- REST：请求头 `Authorization: Bearer <token>`
- WebSocket、图片/下载地址（带不了请求头）：`?token=<token>`
- 401 → 客户端清掉 token 回登录页

## 2. 聊天（WebSocket `/ws?token=`）

> 客户端约定：连接断了就退避重连；断线期间用户发的消息在客户端标“待发送”，连上再发 `user.message`；回复中途断线时，连上后 `GET /api/conversations/{id}` 补全（服务器照常落库）。`approval.reply`、`form.reply`、`message.regenerate` 不排队。服务器按到达顺序一轮接一轮处理（不会丢掉刚结束时立刻发来的下一条）。
> 重新生成：客户端先在本地撤掉旧回复；收到 `error` 或回复开始前断线 → `GET /api/conversations/{id}` 以服务器为准。
> 停止：生成中发 `message.cancel`，停止键置灰，等服务器回 `message.done`（半截回复，`status: "stopped"`）或 `message.stopped`（还没吐字）再收尾；客户端不在本地先砍。断线 = 服务器也停下并把半截落库（`status: "stopped"`），重连后 `GET` 能看到。
> 复制：纯客户端，把回复的块转成 Markdown（text 原样、code 加围栏、table 转 Markdown 表、links 列表；审批/浏览器等过程卡片不复制）。
> 编辑：只能改最后一条用户消息（已在服务器上、不在生成中）。客户端先本地改气泡、撤掉后面的回复，再用 `message.start.user_message` 覆盖；被拒/断线同“重新生成”。
客户端 → 服务器：
| type | 字段 | 说明 |
|---|---|---|
| `user.message` | `text`, `conversation_id?`, `project_id?`, `attachments?: [uploadId]`, `project_files?: [相对路径]`, `model?` | 发一条消息；一次只跑一轮。`project_files`（v1.13）= 引用工作区文件：只认这个对话所在工作区（已有对话以对话为准，新对话以 `project_id` 为准；主聊天 = 个人工作区 `me`，v1.21；`project_id:"me"` 当作主聊天，不会把对话挂到项目上）里真实存在的文件，越界/不存在/.git/重复丢掉，和上传合计 ≤10；存成 `source=project` 的文件块（`id` = 相对路径），内容每轮由服务器从磁盘读（文本内联 ≤6000 字，其余提示模型用 read_file；删了说已不在）。`model` = 这个对话改用的模型别名（`GET /api/catalog/models` 里的 id；`""` = 回默认；不认识的忽略），记到对话上、本轮起生效。客户端只在本机改过且还没 PATCH 成功（或新对话）时带。附件里的图片（jpeg/png/webp/gif）模型能看懂（v0.72，服务端处理，客户端无需改动）：当前这一问且模型在 VISION_MODELS 里 → 发原图（缩到 1280）；其余 → 图片的文字描述（每张描述一次并缓存） |
| `message.regenerate` | `conversation_id`, `message_id?`, `text?`, `model?` | 重新生成最后一条回复：删掉最后一条用户消息之后的回复，同一条用户消息再跑一轮（不保留旧版本）。`message_id` = 客户端眼中的最后一条回复，不是最新的就回 `error`、什么都不删；不带 = 上一轮失败没有回复时“重试”。带 `text` = **编辑**：最后一条用户消息的文字原地换成它（id 不变、附件保留、标题不动；文字空且没附件 → `error`）再答。带 `model` = 换模型重答（同 user.message，记到对话上）。不排队，线不通直接提示 |
| `message.cancel` | `conversation_id?` | 停止正在生成的这一轮。带 id 就必须对得上正在跑的对话；没有在跑的轮次就忽略（刚好已说完）。不排队 |
| `approval.reply` | `id`, `approved: bool` | 回答审批卡 |
| `form.reply` | `id`, `values: {字段: 字符串} \| null`, `remember: bool` | 回答表单卡（v0.83 登录/验证码）；`null` = 取消。只收卡上有的字段、非字符串丢弃、单值 ≤512；值只交给发起的工具，不落库、不回模型。和 `approval.reply` 一样不排队 |

服务器 → 客户端（一轮的顺序）：
| type | 字段 | 说明 |
|---|---|---|
| `message.start` | `conversation_id`, `user_message_id`, `title`, `replaced?: [id]`, `user_message?: {id, role, blocks, created_at?}` | 新对话时用它拿到 id；重新生成时 `replaced` = 被删的旧回复；编辑时 `user_message` = 改好的用户消息（客户端用它覆盖本地气泡） |
| `block.start` | `index`, `block` | 新增第 index 个块 |
| `block.delta` | `index`, `text` | 追加文字到第 index 个 text 块 |
| `block.update` | `index`, `block` | 整块替换（审批卡状态变化） |
| `tool.status` | `id`, `name`, `label`, `state: running\|done\|error\|denied`, `step?` | 工具进度条 + 活动时间线（v1.28）：`step = {id, tool, title, detail, state, at, ms?, note?}`（backend/app/activity.py；detail 只取命令/路径/网址等白名单参数；denied = 没批准/没填表，不经过 running）。客户端按 `id` 合并进 pending 消息的 steps |
| `thinking.delta` | `text` | 推理模型的思考片段（v0.65）：追加到生成中的占位消息上临时展示（客户端只留尾部 2000 字），**不属于任何块、服务器不存、`message.done` 里没有**；老服务器/非推理模型不发 |
| `message.done` | `message: {id, role, blocks, status?, created_at?, steps?}` | 一轮结束，以它为准落盘。`status: "stopped"` = 被停止的半截回复（等待中的审批卡变 `expired`） |
| `message.stopped` | `conversation_id` | 还没产出任何内容就被停止：不存回复，用户消息留着（可“重试”） |
| `error` | `message` | 本轮失败 |

## 3. 消息块（`blocks.py` 是定义源）
每条消息 = `blocks: Block[]`，按 `type` 区分。客户端遇到不认识的 type 必须忽略，不能崩。
| type | 字段 |
|---|---|
| `text` | `text`（Markdown，含表格） |
| `links` | `items: [{url, label?, title?}]` |
| `table` | `title?`, `columns[]`, `rows[][]`, `note?` |
| `code` | `language`, `title?`, `source`, `live?`（v1.24：`true` = 前台命令还在跑，`source` 是最近 ≤40 行输出，服务器约每 0.5 秒用 `block.update` 整块替换；跑完同一个 index 换成不带 `live` 的最终块（完整输出 + `# 退出码 N`）。客户端运行中显示“运行中”、不给复制、定高贴底。被停止的半截回复里不会再带 `live`） |
| `file` | `source: upload\|project`, `id`, `name`, `mime`, `size`, `project_id?`（source=project 时是工作区 id：项目 id 或 `me`；下载 `/api/projects/{project_id}/files/{id}`）。v1.22：助手用 display_file 交付的成果默认是 source=upload 快照（下载 `/api/uploads/{id}`，之后工作区改动不影响）；超过 deliver_max_mb 的退回 source=project。卡片第二行 = 种类 · 大小[ · 我的文件/项目文件]（fileKind 规则两端一致） |
| `approval` | `id`, `title`, `detail`, `state: pending\|approved\|rejected\|expired` |
| `browser` | `session`（按网站起的会话名，如 `taobao-com`；旧卡 `main`）, `site?`（网站主域名，卡头显示）, `live?`（v1.26：browser_open 还在打开，没画面时显示“正在打开”）, `handoff?: {id, reason, state: pending|done|cancelled|expired}`（v1.29：`browser_handoff` 请用户接管——验证码、滑块、扫码；pending 时客户端自动进入接管并显示“需要你来”条，交还回 `form.reply {id, values: {}}`、做不了回 `values: null`，服务器 block.update 改 state；无人值守不出；停止 → expired）。截图轮询节奏由客户端定：接管/等接管 0.6 s、打开中 1 s、看着 1.5 s，只是看着 2 分钟暂停。实时画面：`GET /api/browser/screen?token=&session=` 轮询；接管：`POST /api/browser/mouse {x,y,session}` 0–1 归一化坐标，`POST /api/browser/keyboard {text?, key?, session}`。会话列表 `GET /api/browser/sessions` → `{sessions:[{name,label,open,saved,last_used(ISO|null),cookies,domains[≤5]}], max_open}`（只给域名和个数，不给 cookie 值；服务连不上 503）；退出登录 `DELETE /api/browser/sessions/{name}`（关掉并删存档；坏名字 400） |
| `page` | `slug`, `title`, `url` |
| `preview` | v1.30 端口预览：`workspace`, `port`, `url`（签名链接，公开可开）, `title?`, `command`（在听的程序）, `expires_at`（ISO，默认 24 小时）；过期后打开是“链接失效”页 |
| `stats` | `items: [{label, value, note?}]`（1–6 项；关键数字小卡片，标签 + 大数字 + 一句变化；模型用 `show_stats` 工具产出，面板刷新优先用它） |
| `memory` | `action: saved\|updated\|forgotten`, `items: [{id, content, category, previous?}]`（记忆卡：本轮记住/改了/忘掉了什么；只由记忆工具产出。“已撤销”不在块里：客户端对照 GET /api/memories 推算——saved 的 id 不在 = 已撤销，updated 内容等于 previous = 已改回，forgotten 内容都在 = 已恢复；撤销走 /api/memories 的 DELETE / PATCH / POST。客户端收到 block.start 的记忆卡时重拉记忆列表） |
| `draft` | `title, body`（草稿卡：用户以自己名义发出的文字——邮件第一行 Subject:、消息、帖子；正文原样显示不渲染 Markdown；客户端 复制 / 系统分享。模型用 `show_draft` 产出） |
| `summary` | `title, subtitle?, markdown`（摘要卡：用户自己读的长文——计划、行程、简报；标题 + 小字来源/范围 + Markdown；超过 600 字或 14 行客户端折起，“展开全文”。`show_summary` 产出） |
| `products` | `title?`, `pick?`, `items: [{name, price?, image?, url?, meta?}]`（v0.81 商品宫格：1–12 项；image/url 只能 http(s)，`show_products` 先探测图片，打不开的 image 置 null（商品保留、客户端占位）；price 原样；pick = 一句推荐，卡底显示；客户端 2–4 列（每格 ≥148），点格子开 url；复制成 `- 名字 价格 补充 url` 列表） |
| `order` | `id`, `merchant`, `items: [{name, price, qty=1, note?, image?}]`, `breakdown: [{label, amount}]`, `total`, `payment?`, `destination?`, `order_number?`, `action`（按钮字，≤12）, `state: pending\|approved\|rejected\|expired\|placed`（v0.81 订单卡：`confirm_order` 产出 pending，就是审批卡——按钮回 `approval.reply {id, approved}`，服务器 block.update 改 state；无人值守/停止 → rejected/expired；`show_receipt` 产出 placed 回执带订单号、没按钮。金额全原样，客户端不算账；过程卡，不进复制） |
| `form` | `id`, `purpose: login\|code\|info`, `title`, `site?`, `note?`（为什么问）, `fields: [{name, label, kind: text\|email\|password\|code\|phone\|multiline, value?, options?: string[]（≤6 可点选候选）, optional?: bool}]`（1..6）, `remember`（是否提供“记住”：login → 保险箱，info → 长期记忆）, `action`（按钮字）, `state: pending\|submitted\|cancelled\|expired`, `answers?: [{label, value}]`（v0.83 表单卡：`browser_login` 在保险箱没有该站登录时、`browser_code` 要验证码时产出；v0.87 `ask_user` 产出 purpose=info，提交后服务器把非空答案写进 `answers`（回显、进历史）。客户端回 `form.reply`，服务器 block.update 改 state；必填 = 非 optional 字段非空白。无人值守 → login/code cancelled、ask_user 不出卡；停止 → expired。login/code 的值从不出现在卡片里；过程卡，不进复制、不进分享网页） |
| `job` | `id`, `title`, `command`, `state: running\|done\|failed\|timed_out\|cancelled\|lost`, `started_at`, `finished_at?`, `exit_code?`, `tail?`, `stop_reason?`（v1.20：被服务器护栏自动停掉的原因——连续没输出判卡住 / 日志超限；state=cancelled，客户端显示“已自动停止”+原因、算警示）（v1.19 后台任务卡：`run_command background=true` 产出。块里是落库时的状态；运行中客户端每 2 秒 `GET /api/jobs/{id}` 显示日志尾巴和用时，“取消”= `POST /api/jobs/{id}/cancel`；结束后服务器把块改成终态。快照 `followup=pending` = 服务器马上要在这段对话里接着说一轮：客户端继续问到它不是 pending（最多 90 秒），然后重新拉一次对话；只有亲眼看着它从运行中结束的卡才触发。过程卡，不进复制/存文件） |
| `images` | `items: [{url, caption?}]`（1–6 张网络图片，url 必须 http(s)；服务器 `show_images` 先逐张探测（状态 <400 且 content-type image/*），打不开的丢掉；客户端单张 4:3、多张横排，坏图留占位，只渲染 http(s)） |

文件地址：upload → `/api/uploads/{id}?token=`；project → `/api/projects/{project_id}/files/{id}?token=`

## 4. REST 资源
统一形状：列表 `GET`，新建 `POST`，改 `PATCH`，删 `DELETE`，每项都有 `id`。
| 资源 | 路径 | 备注 |
|---|---|---|
| 对话 | `/api/conversations` | `GET ?q=&project_id=` 搜标题+内容（置顶在前，内容命中带 `snippet` + `message_id`＝最近一条命中的消息，客户端打开后滚到它并闪一下；标题命中两者都不带）；`PATCH /{id} {title?, pinned?, model?}` 不改 `updated_at`（`model` 非法 422，`""` = 回默认）；列表项和详情都带 `model`（`null` = 默认）；`GET /{id}` 返回 messages（每条 `{id, role, blocks, status?, created_at?, steps?}`；`steps` = 这条回复用过的工具步骤（v1.28，没用工具不带；停止时还在跑的为 `stopped`），`status` 只在 `stopped` 时出现；`created_at` 是带时区的 ISO 时间（v0.45 起，客户端按本地日期画日期分隔，没有就不画）） |
| 回复存成项目文件 | `POST /api/messages/{id}/save-to-project` | body `{project_id?}`（不给 = 回复所在对话的工作区：项目，或主聊天的 `me`“我的文件”；v1.21 也可显式传 `me`）→ `{project_id, project_name, path, name, size, mime}`（`me` 的 project_name = “我的文件”）；只收助手回复，存成 Markdown 写进工作区根目录，同名加“ 2”；没内容/用户消息 400，消息或项目不存在 404（v1.15） |
| 项目 | `/api/projects` | `brief` = 项目档案（Markdown，≤8000 字，超出 422；PATCH 时去首尾空白，内容真变了才把 `brief_by` 设为 `user`、`brief_updated_at` 设为现在；助手用 `project_brief` 工具改时 `brief_by=assistant`；老服务器没有这三个字段）；只读 `conversation_count`（项目内对话数）、`last_active_at`（项目或其中任一对话的最后更新）；文件：`/api/projects/{pid}/files[/{path}]`（pid = 项目 id，或 `me` = 个人工作区“我的文件”（v1.21，主聊天和定时任务的工作区）；不存在的 pid 404，不再建目录；multipart 上传；列表每项 `path/name/size/mime/modified`，modified = Unix 秒，客户端首屏按它取最近 3 个；下载路径逐段 URL 编码）；v1.25 电脑状态：`GET /api/projects/{pid}/computer` → `{workspace, name, sandbox: {state: running\|stopped\|none\|unreachable, memory_used?, memory_limit?（字节）, started_at?, last_used_at?, idle_minutes?, outdated?}, disk_used（字节，含隐藏目录）, disk_partial, running_jobs: [同 /api/jobs 形状]}`（只看不开机；沙盒连不上 state=unreachable，其余照给）；`POST …/computer/restart` → 停掉运行中的后台任务（按用户取消）+ 删容器，返回新状态；沙盒连不上 503 且什么都不动；v1.27：`sandbox` 加 `cpu_percent`（占沙盒 CPU 配额 %）、`oom_kills`（本次开机内存超上限被内核杀的进程数）、`processes: [{pid, cpu, memory（字节）, elapsed（秒）, command}]`（按 CPU 前 8，只在运行中）；顶层加 `storage: {files, installed, logs, spill, cache, cleanable}`（字节，disk_used = 前五项和）与 `tools: [{kind: pip\|npm, name, version}]`（用户级安装）；`POST …/computer/cleanup` → `{freed, status}`（删 .spill、已结束任务的 .jobs/<id>、.home/.cache 和运行中容器 /tmp 的 pip/npm 缓存；沙盒连不上照清工作区）。后台任务内存超上限：state=failed、`stop_reason`=“内存超过这台电脑的上限，被系统强制结束”；v1.30 端口预览：状态顶层加 `ports: [{port, loopback, pid, command}]`（只在运行中；loopback = 只监听 127.0.0.1，预览连不到）；`POST …/computer/preview {port, path?}` → `{workspace, port, url, command, expires_at}`，没在听 / 只听本机 / 休眠 409（detail 写明怎么改）；公开转发 `ANY /api/preview/{token}/{path}`（无需登录，token = 工作区.端口.到期.HMAC；无结尾斜杠 307 补上；响应加 `Content-Security-Policy: sandbox …`（不透明源）、`Access-Control-Allow-Origin: *`，改写 Location 与 Set-Cookie 的 Path 到预览前缀；跨源预检直接 204；打不开时回 HTML 页：410 失效、503 休眠、502 端口上没服务 / 沙盒连不上、413 超 32 MB；不转 WebSocket） |
| 记忆 | `/api/memories` | 每项 `{id, category, content, created_at, updated_at}`；`category` 常用 `profile\|food\|travel\|work\|shopping\|general`，客户端认识的显示中文名、不认识的原样显示。搜索、分类筛选都在客户端做（记忆全量已在列表里） |
| 我对你的了解 | `/api/memory-digest` | `GET` → `{text\|null, generated_at\|null, count（生成时的记忆数）, memories（现在的记忆数）, stale}`，零模型调用；`stale` = 生成后记忆有增删改。`POST` 用便宜模型重写一次（记账 kind=digest）返回同样形状；没有记忆 → 删掉旧概括返回 text=null；模型失败 502，旧概括不动。客户端从不自动 POST（花 token），只在用户点“生成/更新”时调 |
| 定时任务 | `/api/tasks` | 计划二选一：`cron`（重复，5 段，用户时区）或 `run_at`（一次性，ISO 时间，此时 `cron` 为 `""`），两者都给/都不给/cron 无效 → 422；PATCH 合并后同样校验，换成一次性传 `{run_at, cron: ""}`、换回重复传 `{cron, run_at: null}`；`done`（只读）= 一次性任务已跑过（last_run_at ≥ run_at），此时 `next_run_at` 为 null，把 run_at 改到以后即重新排上，“立即运行”不消耗这次提醒；`output: report\|panel`（面板 = output=panel 的任务 + 一张 kind=panel 的卡；PATCH 改面板任务的 `name` 时服务端同步改卡片 `title`，客户端编辑面板只 PATCH 任务）；`last_status: ok\|error\|null`（上一次结束的运行）；`fail_streak`（只读，连续失败次数，成功归零）+ `paused_reason: failures\|null`（只读；重复任务连续失败 3 次服务端自动 `active=false, paused_reason=failures` 并发“已暂停”提醒卡；PATCH `active: true` 或手动运行成功 → 恢复、归零、收起卡；用户手动停 = null）；`next_run_at`（只读，服务端按 cron + 用户时区算好的下次运行，与 worker 同一套计算；停用或 cron 无效为 null；过期未跑显示为现在）；`POST /{id}/run` 立即运行；`GET /{id}/runs?limit=1..30` 最近运行记录，新的在前：`[{id, trigger: schedule\|manual, status: running\|ok\|error, error, conversation_id（报告那次的对话；面板或对话已删为 null）, started_at, finished_at, duration_ms}]`，任务不存在 404 |
| Home 卡片 | `/api/cards` | `kind: action\|panel\|report`；面板刷新 = 对其 `task_id` 调 run；`unread` 新报告/新建议为 true（面板刷新不算）；`target` 可选（≤64），客户端里的去处 = 名字 或 名字:id（v0.93，app/card_targets.py）：`usage` 用量、`tasks` 定时任务（有 `task_id` 去那个任务详情）、`memory`、`skills`、`connectors`、`vault`、`pages`、`project:<项目 id>`（那个项目；点建议卡“去做”开的对话放进这个项目），显示一颗去处按钮；不认识的名字忽略。助手卡可以只有 `target` 没有 `action_prompt`（只有用户本人能做的事），此时去处按钮是主按钮。预算提醒就是一张 `kind=action, target=usage` 的卡。**系统提醒**（`origin` 空，v0.95 统一由 app/system_alerts.py 发）：预算（`usage`）、任务失败（`tasks`+`task_id`）、连接失效（`connectors`，没有 `action_prompt`，标题如“GitHub 连接已失效”，重新连上或断开后服务端自动收起）、MCP 服务器连不上 / 令牌被拒（v0.97，`connectors`，没有 `action_prompt`，标题如“MCP「notes」连不上”，下次调通或删掉服务器后自动收起）。系统提醒按“主体”收起/顶替（服务端 `alert_subject`，不出现在接口里）：同在连接器页的两件事互不影响。客户端眉题规则（cardEyebrow）：没有 `action_prompt` 但有认得的去处 → “需要你亲自处理”（不分 origin）；`origin=agent` 有指令 → “可以替你做”；已开始 → “已交给助手 · 看看进展”；其余无眉题。**稍后提醒**：`PATCH {snoozed_until: ISO}`（只 action/report；须在将来、≤30 天，否则 422；同时清 `unread`），`{snoozed_until: null}` = 现在放回；`snoozed_until` 非空的卡客户端不显示（只在“为你准备”下给一行“N 条稍后提醒”），到点 worker 清空它并重新 `unread=true`、`updated_at=now`；`dismissed: true` 一并清掉推迟。响应里 `snoozed_until` 总带时区。**助手提议的建议卡**（v0.85）：`origin: "agent"`（空 = 系统提醒/接口建的）、`action_label` 主按钮上的字（空 = “去做”，POST 可带，≤24）；客户端点主按钮：系统提醒 = 把 `action_prompt` 发进新对话（不收起）；`origin=agent` 的卡（v0.89）= `POST /api/cards/{id}/start` → `{conversation_id, prompt, started}`：服务端开新对话（标题 = 卡标题）并写进卡的 `conversation_id`、清未读，不改 `updated_at`；`started=true` 时客户端打开它并发 `prompt`，`false`（已开始过，对话还在）只打开、不重发；对话被删了会重开一段；系统提醒 / 已收起 / 不存在 → 404。卡留在 Home：`origin=agent` 且 `conversation_id` 非空 = “已交给助手”，主按钮“查看对话”（同一接口），次按钮“收起”（PATCH dismissed）。同标题重新提议会清掉 `conversation_id`。由工具 offer_on_home 建（app/home_offers.py：同标题原地更新、最多 5 张，多了收起最旧的）。**配图 / 原页**（v0.91）：`image_url`（卡顶 2:1 宽图）、`link_url`（正文下“来源 · 域名”，点图也去原页），都只收 `http(s)`、≤1024（POST 非 http(s) → 422）；工具会先探测配图能打开才存，同标题重新提议没给就清掉；客户端遇到非 http(s) 值当没有。**报告卡的“一眼”**（v1.07）：`kind=report` 带 `headline`（第一张摘要卡的标题，≤80）和 `gist`（第一段正文的一句话，没有正文取摘要第一行，≤120），投递时由 app/report_gist.py 取出（迁移 0025 回填老报告），只读；客户端收件箱行副标题 = `headline · gist`，都空时退回块的纯文本；横幅第二行同理 |
| 收件箱 | `/api/inbox` | `GET` → `{unread, latest: {id,kind,title,headline,gist,conversation_id,created_at}\|null}`（headline/gist 见 /api/cards）（轮询用，很轻；latest 按 updated_at 取最近“来到”的未读——到点叫醒的“稍后再看”、重新提议的建议也算刚到）；`POST /read {ids?}` 不传 ids = 全部已读，返回同样的摘要。`GET /api/conversations/{id}` 会顺带把该对话的报告标为已读 |
| 模型 | `GET /api/catalog/models` | → `{default, models: [{id, label}]}`（服务器 CHAT_MODELS，顺序即切换顺序）。客户端缓存、不足两项不显示切换；对话的 `model` 不在列表里时按默认显示（服务器也回落到默认） |
| 技能 | `/api/catalog/skills` | 内置技能 `builtin: true` 不可改不可删；`customized: true` = 内置的自定义版（同 id，可 PUT）。`POST /{id}/customize` 复制内置为自定义版（已有则原样返回），`POST /{id}/reset` 恢复内置原文，两者都返回该技能；DELETE 只用于自己写的（内置 400，不存在 404）；POST 新建的 id 自动避开已有 id；每条带 `enabled`（缺省视为 true），`POST /{id}/enable` / `POST /{id}/disable` 开关并返回该技能，停用的仍在列表里但不进模型的技能目录、use_skill 拒绝；开关按 id 记，customize/reset 不改变它，删除用户技能时清掉 |
| 连接器 | `/api/connectors` | `GET /{provider}/start?client=web\|app` → `{url}`，客户端在浏览器打开；见下方「授权回跳」 |
| MCP | `/api/connectors/mcp` | 列表每项 `{id, name, url, has_token, problem}`；`problem`（v0.97）= 还没恢复的问题 `"auth"`（令牌被拒）\| `"down"`（连不上 / 超时 / 服务器出错）\| `null`，客户端在这一行用警示色标出（不认识的值当没有）。`GET /mcp/{id}/tools` 也是一次体检：不通 → 502 `{detail}` 并在主页放提醒，通了 → 收起旧提醒。`DELETE /mcp/{id}` 连同它的提醒一起收起 |
| 保险箱 | `/api/vault` | `kind: api_key\|login`；永不返回明文 |
| Pages | `/api/pages` | 每项 `{id(=slug), slug, title, updated, published, url}`；公开地址 `/p/{slug}/`（`Cache-Control: no-cache`）。`PATCH /{slug} {title?, published?}`：`published=false` = 下线（文件留着、公开地址 404，与不存在同一响应），`true` = 重新发布、链接不变；改名/上下线都不动 `updated`；空标题 422，不存在 404。智能体改写下线的页面只改内容、仍是下线（工具结果会提示用户去重新发布）。老服务器没有 `published` → 客户端按已发布处理 |
| 上传 | `POST /api/uploads` | multipart `file` → `{id, name, mime, size}` |
| 语音 | `/api/voice` | `GET /config` → `{stt: true, tts: "server"\|"device"}`（v0.65；老服务器没有 → 按 device）；`POST /transcribe` multipart `file` → `{text}`（任意常见录音格式：m4a/webm 服务器自己转码；识别不可用 503）；`POST /speak {text}` → `audio/mpeg`（只在 tts=server 时可用，否则 503；服务器去掉 Markdown、截到 1000 字；空文字 422），客户端 tts=device 时用系统语音朗读；v0.66 起两端回复下方的“朗读”键：tts=server → 先 POST /speak 播 mp3，失败（非 401）退回系统语音；客户端只送正文块（去 Markdown、链接读文字、不读网址/代码）；同一时间只读一段 |
| 用量 | `GET /api/usage` | → `{currency, budget\|null, priced: [别名], today, month, daily}`，每段 `{calls, tokens, cost, models: [{model, calls, prompt_tokens, completion_tokens, cost}]}`（按 cost、token 降序）；“今天/本月”按服务器 TIMEZONE 切；没定价的别名 cost=0，客户端据 priced 显示“未定价”；`daily: [{date: "YYYY-MM-DD", calls, tokens, cost}]` 本月 1 号到今天每天一项（按 TIMEZONE 分天，空天补 0，升序），客户端按整月排格子；老服务器没有此字段时客户端不画图；`conversations: [{id, title\|null, calls, tokens, cost}]` 本月最花钱的对话（按 cost、再按 token 降序，最多 5 个；不归属对话的调用不算；对话已删 title=null，客户端显示“已删除的对话”且不可点；老服务器没有 → 不显示）；`last_month: {calls, tokens, cost, to_date: {calls, tokens, cost}}` 上个月全月合计 + 同期（上月 1 号 0 点到上月同一天同一时刻，按 TIMEZONE 日历对齐；上月没有这一天 → 同期 = 全月），客户端用“本月至今 ÷ 上月同期 − 1”显示涨跌（有定价按钱否则 token；同期为 0 不显示百分比；老服务器没有 → 不显示） |
| 某天用量 | `GET /api/usage/days/{date}` | `date` = `YYYY-MM-DD`（服务器 TIMEZONE 的本地日期，格式不对 422）→ `{currency, priced, date, total, conversations}`，total 同上面的分段形状，conversations 同报表的 conversations（那天窗口内最花钱的前 5 个对话，已删 title=null）；窗口是本地 0 点到次日 0 点，与 daily 的分桶同一条边界（柱子的数 = total 的数）；任何日期都能查，没用量全 0。客户端在用量图上“选定”某天时取（今天也取，因为报表里没有今天的对话；请求途中先用报表的 today 画模型行） |
| 分享对话 | `/api/conversations/{id}/share` | 只读网页快照（v0.63）：`GET` → `{shared:false}`（从没分享）或 Pages 项 `{id, slug, title, updated, published, url, source:"conversation:<id>"}` + `shared`（= published）+ `stale`（快照之后对话有新消息）；`POST`（无 body）生成或更新快照并公开，同一对话 slug 不变（停止过的也恢复）；`DELETE` 停止分享 = 页面下线（链接保留）。对话不存在 404。页面同时出现在 `/api/pages`；快照不含审批卡、浏览器画面，附件只写文件名。助手也能在对话里分享（v0.74 工具 `share_conversation` share/unshare/status，同一链接；share 时回复带一张 `page` 块，快照到用户那句为止，所以随后 GET 会是 `stale:true`）。客户端收到 `page` 块时让 Pages 列表失效 |
| 本对话用量 | `GET /api/conversations/{id}/usage` | → `{currency, priced, total}`，total 同上面的分段形状；累计这个对话的所有调用（回复、滚动摘要、记忆向量等）；对话不存在 404；删对话不删用量行（月度总账不变）。客户端在换对话和一轮回复结束时取 |
| 后台任务 | `/api/jobs` | v1.19：`GET ?project_id=&running=true` 最近 50 个（project_id = 工作区 id，主聊天的任务是 `me`）（新的在前）；`GET /{id}?tail=4000`（200–20000 字）→ `{id, project_id, conversation_id, title, command, state, exit_code, followup: none\|pending\|done\|seen\|skipped, started_at, finished_at, elapsed（秒）, log_size, tail, stop_reason}`，读接口时顺便按磁盘结掉已结束的任务；`POST /{id}/cancel` → 同形状（已结束则原样返回；沙盒不在线 503）；不存在 404。工作区 `.jobs/`（以及 v1.23 起沙盒家目录 `.home`、长输出 `.spill`）不出现在项目文件里 |
| 健康 | `GET /api/health` | 登录页“测试连接”用 |

## 5. 客户端约定
- 服务器地址由用户在登录页填写（自建，没有固定域名）
- 错误体：`{detail: string}`，直接展示给用户
- 时间：ISO 8601 带时区（v1.18 起服务端所有 datetime 都经 app/wire_time.py 出口，SQLite 读回的无时区值按 UTC 补偏移，不再有无偏移字符串）；展示用用户本地时区
- 新消息提醒（没有推送时）：回到前台立刻、前台时每 2 分钟拉一次 `/api/inbox`；`latest.id` 变了且未读数增加 → 端内横幅 + Home 角标。后台不轮询（省电、省钱）

## 授权回跳（OAuth）
第三方回调 `GET /api/oauth/callback`（公开，靠签名 state 验真；state 里记着发起端 `client`，只能是 `web` / `app`）。结果统一是同一条路由 `/me/connectors` 加查询参数 `connected=<provider>` 或 `error=<原因>`：
- `web`：302 到 `/#/me/connectors?…`
- `app`：返回一个小页面，自动跳 `<APP_SCHEME>://app/me/connectors?…`（默认 scheme `myassistant`），并给“回到 App”按钮兜底（有的浏览器不允许无手势跳自定义 scheme）。App 用系统深链接收，go_router 直接把 path+query 当路由打开。

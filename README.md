# Assistant

```
Caddy (HTTPS, 静态前端, 反代)
  ├─ /            → frontend (React PWA)
  └─ /api, /ws    → backend (FastAPI)
                       ├─ Postgres  (会话/项目/记忆/任务/卡片，Alembic 迁移)
                       ├─ LiteLLM   (模型网关 → 阶跃 Step Plan / DeepSeek 等，花费上限；小 VPS 可直连省掉)
                       └─ SearXNG   (自托管搜索，免费)
```

## 客户端
- `app/`：**原生 App（Flutter）**，安卓优先，iOS 同一套代码。见 `app/README.md`；推到 GitHub 自动出 APK（`.github/workflows/app.yml`）
- `frontend/`：网页版，作为电脑端
- 两端都只依赖 `docs/protocol.md` 这份协议；后端不关心是哪个客户端

## 模型（默认阶跃 Step Plan）
- `.env` 填 `STEP_API_KEY`。网关别名：`fast` = step-3.7-flash（日常、能看图）、`smart` = step-5-preview（深度、也能看图）、`lite` = step-3.5-flash（摘要等后台小活）。国内账号把 `deploy/litellm/config.yaml` 的 `api_base` 和 `STEP_BASE_URL` 换成 `api.stepfun.com`。
- 推理模型的思考过程会实时显示在“思考中”小卡里（WS `thinking.delta`），不存库、不回传给模型。
- 有的供应商每个流式包都带累计用量：`llm.py` 只记最后一次（中途停止也记已花的）。
- 直连模式（不跑 LiteLLM，省约 500MB 内存）：`LLM_BASE_URL` 填供应商地址、`LLM_API_KEY`、`MODEL_MAP` 把别名翻成真实模型名，见 `.env.example`。
- 真接口测试：`STEP_API_KEY=... python backend/tests/live_stepfun.py`（约 4 次调用：工具调用往返 + 朗读→识别）。

## 语音与记忆检索
- `VOICE_PROVIDER=stepfun`（默认）：语音输入用 stepaudio-2.5-asr（App 的 m4a、网页的 webm 由后端 ffmpeg 转 wav），朗读用 stepaudio-2.5-tts（`POST /api/voice/speak`，音色 `STEP_TTS_VOICE`）。`gateway`：识别走网关 `stt` 别名，朗读用设备自带语音。逻辑全在 `backend/app/voice.py`。
- 记忆向量检索：填 `SILICONFLOW_API_KEY`（硅基流动 bge-m3，免费额度）；不填记忆退回“最近 N 条”。
- 记忆按条管理（v0.70）：上下文里每条记忆带 `#短引用`（id 前 8 位），工具 remember / update_memory / forget 只经 `memory_store`（save/update/resolve/card）；每次真改了记忆，回复里附一张 `memory` 块（记忆卡），客户端可撤销。

## 启动（一键部署，推荐）
VPS 装好 Debian 12（或 Ubuntu 22.04+），≥2 核 4GB。把代码放上去（`git clone` 私有仓库，或上传 zip 解压到 `/opt/assistant`），然后：
```bash
cd /opt/assistant && sudo bash deploy/install.sh
```
脚本会问域名（没有直接回车，用 http://IP）、阶跃 key、登录账号，其余全自动：
- 内存 <6GB = 小内存档：建 2GB swap（swappiness 10）、**直连模式**（不跑 LiteLLM 容器，省约 500MB）、云浏览器同时只开 1 个会话（超出时关掉最久没用的，登录状态保存）、项目沙盒 512MB/空闲 10 分钟停。没有 Redis。
- 装 Docker、生成 `.env`（随机 JWT/数据库密码/沙盒与浏览器 token/VAULT_KEY，已有值绝不覆盖，可重复运行）、建数据目录、构建沙盒镜像、启动、等后端健康后打印地址和密码。
- 档位开关全是 `.env` 变量（`COMPOSE_PROFILES`、`BROWSER_MAX_SESSIONS`、`BROWSER_MEM`、`SANDBOX_MEM`、`PG_SHARED_BUFFERS`…），`docker-compose.yml` 只有一份。
- 更新：`sudo bash deploy/update.sh`；备份数据库和 .env：`sudo bash deploy/backup.sh`（可放 crontab）。
- 无人值守：`ASSUME_YES=1 DOMAIN=a.com STEP_API_KEY=... sudo -E bash deploy/install.sh`。脚本离线测试：`bash deploy/tests/test_install.sh`；浏览器会话上限：`python browser/test_sessions.py`。

## 手动部署
1. `cp .env.example .env`，填 STEP_API_KEY、OWNER_PASSWORD、JWT_SECRET、DOMAIN（`COMPOSE_PROFILES=gateway` 才启动 LiteLLM）
2. `docker compose up -d --build`
3. 浏览器打开 https://你的域名 （没有域名先用 DOMAIN=:80，访问 http://IP）

### 第一次部署前（沙盒）
```bash
mkdir -p /opt/assistant/data && sudo chown -R 1000:1000 /opt/assistant/data   # 与 .env 的 HOST_DATA_DIR 一致
docker compose --profile build-only build sandbox-image                      # 构建项目沙盒镜像
```
在 `.env` 里填 `HOST_DATA_DIR`、`SANDBOX_TOKEN`、`BROWSER_TOKEN`、`VAULT_KEY`、`PUBLIC_URL`；
要连 Google/GitHub 再填对应的 OAuth 客户端（回调地址：`<PUBLIC_URL>/api/oauth/callback`）。App 里授权完会自动跳回 App（深链 scheme 默认 `myassistant`，改的话设 `APP_SCHEME` 并同步 App 的 AndroidManifest / Info.plist / `lib/core/links.dart`）。
后端冒烟测试在 `backend/tests/`（如 `python tests/smoke_oauth_return.py`、`python tests/smoke_conversations.py`、`python tests/smoke_inbox.py`，后两个会真跑一遍 Alembic 迁移）。

沙盒服务是唯一持有 Docker 权限的容器，不暴露端口；后端只能用 SANDBOX_TOKEN 调它。
每个项目一个容器：1G 内存、1 核、256 进程、无 capability，单条命令最长 120 秒，空闲 30 分钟自动停。
前台命令运行中，聊天里的命令卡每 0.5 秒刷新最近输出，点停止会杀掉沙盒里的命令（v1.24）。项目首屏的“电脑”一节和“我的 → 我的电脑”显示容器运行/休眠、内存、磁盘、正在跑的后台任务，可一键重启（停任务 + 删容器，文件和装的包都在，v1.25）。云浏览器会话按网站保存（taobao.com → 会话 taobao-com）：在一个网站登录一次，之后的任务都接着用；“我的电脑 → 浏览器登录”可看到每个网站并退出登录（v1.26）。助手用过工具的回复上方有一行“用了 N 步 · 用时”，点开按顺序回看每一步（运行了什么命令、读写了哪个文件、打开了哪个网页、哪步失败或没批准），跟着消息存库、换设备也在（v1.28）。浏览器遇到图形验证码、滑块、扫码登录这类助手过不去的步骤，会在画面卡上请你接管（“需要你来：拖动滑块完成验证”），你在画面里弄完点“完成，交还”它就接着做；画面只是看着 2 分钟后自动暂停刷新省流量（v1.29）。助手在电脑里做了网页或小工具（后台跑着服务、监听 0.0.0.0），会发一张预览卡，手机上点“打开”就能用，链接 24 小时有效；电脑页“正在监听的端口”也能一键预览（v1.30，走 `/api/preview/<签名>/`，沙盒容器接在专用网络 `assistant-sandboxes` 上，端口不对外映射；v1.75 起页面里以 / 开头的资源和接口路径（Vite/React 打包产物的 /assets/…、fetch("/api/…")、Angular 的 <base href="/">）自动补上预览前缀，不用改代码；前端路由要用 hash 路由或设 basename；v1.44 起 WebSocket 也转发，Vite 热更新、Streamlit、Gradio、Jupyter 能直接用）。浏览器任务能把工作区文件传到网页上（投简历、传图片：助手把文件放进网页的文件框，提交前照旧审批；隐藏目录里的文件不会被传出去），网页上下载的文件自动存进工作区 `downloads/`，画面卡下列出传上去 / 存下来的文件、点开就看（v1.32）。每段对话都能看“本对话全部文件”（点顶栏用量 → 全部文件，或历史菜单）：交给你的成果、你发的附件、网页下载/上传的、助手写的文件，最新在前、按来源筛选，一键打包 zip（≤200 MB，v1.33）。助手改已有文件用 edit_file 只换要改的那一段（必须唯一，不唯一会告诉它在第几行），不再整篇重写；写文件 / 改文件那一步在“用了 N 步”里带 “+3 −1”，点开看彩色 diff（.env、密钥文件只显示行数，密码类的值打码，v1.34）。助手找文件用 glob（按文件名，新改的在前）、搜内容用 grep（按正则，带文件和行号），直接读工作区不唤醒沙盒；node_modules、.venv 这类依赖目录和隐藏目录默认不搜，结果最多列 100 条、其余存进 .spill 让它分段看（v1.35）；文件名匹配超过 100 个时按顶层目录轮流各取几个（不会被一个刚装完包的大目录占满，v1.43，移植 deepseek-harness）。浏览器之前登录过的网站如果登录失效了（又弹出登录页），助手会自己发现并重新登录：保险箱里有账号就直接代填，没有就弹登录卡或请你接管；定时任务里没人在时，Home 上会出一张“taobao.com 的登录过期了”提醒，点“去做”在聊天里登一次，登好提醒自动收起；“我的电脑 → 浏览器登录”里过期的网站标“已过期”（v1.36）。命令安全规则按 shell 语法树逐条看（移植自 Codex CLI）：藏在 if/for、$( )、反引号、bash -c、eval、find -exec、timeout 前缀里的 rm -rf ~ 之类同样拦下（v1.37）。工具结果太长时给助手开头 + 结尾、全文存进 `.spill/`，总长严格不超上限；`.spill` 里只留最近 50 个、30 天内的落盘文件，你自己放进去的文件不会被清（v1.38，移植自 deepseek-harness）。助手查后台任务只拿上次看过之后的新输出，不会把同一段日志反复读进上下文；几个任务一起跑完只接一轮话；你不在时任务连着结束最多自动接 3 轮话（`JOB_FOLLOWUP_WAKES`），再多的结论等你下次说话时一并告诉它（v1.39，移植自 deepseek-harness tool-jobs）。命令输出里的颜色、进度条刷新、终端标题统一洗掉再给助手和你看；命令狂刷屏时沙盒只在内存里留开头 + 结尾，全文边跑边存进 `.spill/`（最多 64 MB）；输出是二进制（cat 了压缩包）时只说字节数，不塞乱码（v1.40，移植 Codex head_tail_buffer）。助手不会冲掉你的改动：已有的文件它得先在这段对话里读过才能整篇覆盖，读过之后被你或后台任务改过就得重读再改；edit_file 对“—”“”这类中英文标点写法不同也能找准原文（v1.41，移植 deepseek-harness 与 Codex）。家目录在工作区的 `.home`（隐藏）：助手 `pip install` / `npm i -g` 装的东西跨对话、跨容器保留；沙盒里没有 sudo/apt，要加系统软件就改 `sandbox/image/Dockerfile` 后重新 `build sandbox-image`（旧容器下次用时自动换新镜像，有后台任务在跑的除外）。

## 手机 App（Flutter 原生，安卓优先）
见 `app/README.md`：GitHub Actions 自动出 APK；首次打开在登录页填服务器地址（需 HTTPS 域名）。最近的对话、项目、首页卡片会缓存在手机上，断网也能看（纯客户端，不涉及后端）。
网页版 `frontend/` 是电脑端客户端；两端只通过 `docs/protocol.md` 和后端对话。

## 目录约定
后端 backend/app/
- blocks.py      消息块协议（前后端唯一契约）
- models.py      会话/消息/项目/记忆/定时任务/Home 卡片
- agent/         内核：loop（想→用工具→说）、context（模型看到什么：系统提示 + 预算内原文 + 滚动摘要）、tools（注册表）
- routes/        只做收发：ws、conversations、crud 工厂 + resources、catalog（技能/连接器）
- skills/        内置技能，一个 .md 一个（用户技能在 data/skills/）
- schedule.py 计划校验与时刻（check() = cron/run_at 二选一的唯一校验，接口与工具共用；is_done/due_at/next_run_at）；task_store.py 任务（含面板）增删改唯一入口（删任务连带删 Home 卡与运行记录；面板改名同步卡片标题 after_patch，接口经 crud_router 的 after_update 钩子、工具经 update()；create_panel 也在这里）；智能体工具 manage_home（agent/builtin/home.py：list/refresh/update/dismiss/snooze/unsnooze，“把天气面板改到 7 点”“这条明早再提醒我”“删掉比分面板”“收件箱那条不用管了”）；智能体工具 schedule_task（agent/builtin/tasks.py：create/list/update/cancel，一次性提醒“明早 8 点提醒我…”）
- project_brief.py 项目档案（活文档）唯一入口：PATCH 钩子盖“谁改的”戳、工具的 edit/write 规则、注入系统提示（超 6000 字截断）
- workspaces.py  工作区唯一规则（v1.21）：每段对话都有“云电脑”——项目对话 = 项目工作区（id = 项目 id），主聊天和定时任务 = 个人工作区 id "me"（data/projects/me，容器 sbx-me，“我的文件”）；ToolContext.workspace、文件/命令/后台任务/落盘工具都走它；name() 不存在 → 文件接口 404
- storage.py     文件系统唯一入口（项目工作区、附件、技能），路径防越界；project_file(pid, rel) = 项目里真实存在的文件（引用项目文件的唯一校验，v1.13：ws._project_files 存引用，agent/context._project_ref 每轮按磁盘内容给模型）
- skills_store.py 技能读写：用户目录里与内置同 id 的文件 = 自定义版（就地顶替内置，customized=true，reset 删掉即恢复）；新建 id 永远唯一，绝不覆盖或顶替；内置不能删、不能直接 PUT；停用开关存 data/skills/_disabled.json（按 id，损坏当全启用），系统提示只列 enabled_skills()，use_skill 拒绝停用的
- sandbox_client.py 调沙盒服务（前台命令 stream：NDJSON 边跑边出输出，可带 stdin ≤64KB，断开=沙盒整组杀（v1.24）；后台任务 start_job/cancel_job/job_alive）
- activity.py 活动时间线唯一规则（v1.28）：每次工具调用一步（标题、白名单参数摘要、状态、用时），随消息存 messages.steps，WS tool.status 带 step
- browser_sessions.py 云浏览器会话唯一规则（v1.26）：按网站起会话名、每段对话的当前会话（Tab）、列表 / 退出登录
- computer.py    工作区“电脑”状态唯一入口（v1.25）：容器状态/内存（沙盒 /sandboxes/{id}/status）+ 磁盘 + 运行中任务；restart = 停任务 + 删容器
- command_guard.py 命令安全规则唯一入口（v1.20）：verdict(cmd) → block（永不执行）/ ask（弹审批卡）；拆段逐条看，参考 Codex CLI
- deliver.py     交付唯一入口（v1.22，display_file 工具）：工作区文件/目录 → 文件卡；默认快照进 uploads（source=upload，之后改/删原文件不影响），目录自动打包 zip（跳过 .git/.jobs/node_modules…），超过 deliver_max_mb（默认 50）的普通文件退回工作区文件卡；write_file 不再出卡
- spill.py       长输出落盘唯一入口（v1.20）：工具结果超过 tool_result_max → 开头+结尾给模型、全文进工作区 .spill/（隐藏，留最近 50 个），read_file offset 读回；参考 deepseek-harness spill-policy
- quota.py       磁盘配额唯一规则（v1.31：WORKSPACE_DISK_MB 每工作区上限，默认 3072，0 = 不限；满了拒写文件/上传/启动后台任务、停运行中的任务，命令结果提醒模型）
- jobs.py        后台任务唯一入口（v1.19；v1.20 护栏：idle_timeout 默认 1200 秒无输出判卡住、日志超 job_log_max_mb 停，stop_reason）：工作区 .jobs/<id>/ 文件约定（run.sh/log/exit/pid/cancelled）、启动/对账/取消/丢失判定、结束后在原对话接着说（worker 每 5 秒 tick + follow_ups）
- vault.py       保险箱：加解密、按域名匹配（唯一解密点）
- schedule.py    定时任务时刻计算（due_at/is_due/next_run_at，按用户时区）：worker 判断到点与接口的 next_run_at 共用，保证界面写的就是实际会跑的时间
- worker.py      定时任务执行器（独立进程）；每次运行经 task_runs.py 记一行（start/finish）
- task_runs.py   定时任务运行记录（task_runs 表，每任务留最近 KEEP=30 条）+ scheduled_tasks.last_status + 失败提醒：连续失败的第一次放 action 卡（task_id + target=tasks，alerts_sent key=task:任务:运行），之后成功自动收起；fail_streak 记连续失败，重复任务连败 PAUSE_AFTER=3 次自动暂停（paused_reason=failures，“已暂停”卡顶替首次失败卡，once=paused），task_store.after_patch 重新启用 → task_runs.resumed() 归零收卡，手动试跑成功也自动恢复（迁移 0024）；worker 启动 recover_stale() 把残留 running 标“中断”；GET /api/tasks/{id}/runs 读
- agent/runner.py 一轮对话的完整流程，聊天和定时任务共用
- agent/approvals.py 审批挂起/答复
- connectors/    OAuth 服务声明（providers.py）、授权与刷新（oauth.py）、MCP 客户端（mcp.py）
- credentials.py 按 URL 解析凭证：OAuth 连接优先，其次保险箱
- browser_client.py 调云浏览器服务
- file_edit.py 精确改文件与改动摘要唯一规则（v1.34）：apply(唯一/replace_all/宽松匹配/CRLF) + change(diff 截断与打码)；ToolResult.change → 活动步骤 change；冒烟 tests/smoke_edit_file.py
- command_guard.py 仍是命令安全唯一规则；解析只走 shell_parse.commands(script)（tree-sitter-bash，移植自 Codex bash.rs；不可用/语法错 → 分词兜底），包装递归 _exec 深度 MAX_DEPTH=8；冒烟 tests/smoke_command_guard_port.py（v1.37）
- jobs.py 仍是后台任务唯一入口：read_new(job, chars) 从 Job.read_offset 读到末尾（utf8_start/utf8_complete 守码点边界、超长留尾巴 + dropped 字节数），job_status 写回游标、tail=true 重看；follow_ups 按对话分组一轮通知、_wakes 数用户上次发言后的叫醒轮数（followup_at 去重）到 settings.job_followup_wakes 置 held，runner 在用户发言那轮 take_held 并进系统提示；冒烟 tests/smoke_jobs_port.py（v1.39，迁移 0029）
- term_text.py 是终端文本唯一规则：strip（ansi-regex 去转义 + 杂控制字符）、frames（\r 帧）、clean、tail（实时卡）、is_binary/binary_note；sandbox/runner.py 用同一 ANSI_PATTERN（冒烟比对）+ Cleaner（块尾半截序列扣下）+ HeadTail（Codex 移植）+ _SpillFile（超长才开、边跑边写、SPILL_MAX_BYTES 64 MB）+ 二进制嗅探（result.binary 字节数）；冒烟 tests/smoke_term_output.py（v1.40）
- agent/loop_guard.py 是“原地打转”唯一规则（移植 Gemini CLI loopDetectionService，Apache-2.0 modified：工具指纹含结果、分隔线正则修正、提醒后清文字计数）；loop.run 一轮预算 AGENT_MAX_STEPS=40 / AGENT_TURN_TOKENS=600000，到了收掉工具并让模型交代进度；冒烟 tests/smoke_loop_guard.py（v1.45）
- agent/compact.py 是“一轮之内上文压缩”唯一规则（移植 deepseek-harness compaction，嫁接 Gemini chatCompressionService / Codex compact）：每次调用模型前上文过窗口 80% → 先剪较早的长工具结果（>8192 字留头 4096 + 尾 1024，最近 3 批不动），不够再把这一轮较早的步骤压成检查点（重放上文 + 指令、tool_choice=none；切口不拆工具调用与结果；合并旧检查点；摘要失败/截断/更长就不换）；供应商报上文超长 → 强制压一次再重试；窗口 CONTEXT_TOKENS=128000 / MODEL_CONTEXT 按别名；冒烟 tests/smoke_turn_compact.py（v1.46）
- app/agent/subagent.py 是“子助手”唯一规则（移植 Gemini CLI local-executor，嫁接 deepseek-harness tool-subagent / Codex multi_agents）：delegate 工具一次并行派 ≤SUBAGENT_MAX_TASKS(4) 个子任务；每个子助手 = 同一个 loop.run 跑独立上下文（只有任务说明、无主对话）、独立数据库会话、工具白名单 CHILD_TOOLS（工作区文件/命令/后台任务/网页/API/MCP/技能；无浏览器、问用户、展示卡、记忆、计划、delegate → 深度 1）、非交互（审批一律拒、表单一律取消）、沿用主助手模型；loop.Limits（步数 20 / token 30 万 / 截止时间 10 分钟 → 收工具交代进度 = partial）+ 60 秒宽限硬超时；结论交回主助手（每个 ≤6000 字），聊天里一张 delegate 实时卡；冒烟 tests/smoke_subagent.py（v1.48）
- 服务器主机模式（v1.49，默认关）：app/host_policy.py 是“主机命令要不要问”的唯一规则（移植 Codex execpolicy：Allow/Prompt/Forbidden、按段取最严、前缀规则 + 禁用前缀表、建议前缀须盖住每一段、无人值守要问的一律禁止；command_guard 的 block 批准也不放行）；app/host_mode.py 管开关（app_settings）、“以后都允许”的前缀规则（host_rules，迁移 0030）、这段对话里的批准（进程内）；工具 host_command（scope="host"，ToolContext.host 每轮从开关读）每条弹主机审批卡（仅这一次 / 这段对话里都允许 / 以后都允许 X 开头的命令；危险或会停 Docker 的只给前一两档）。执行端 deploy/host-agent/host_agent.py（标准库，root，只听 unix socket /run/assistant-host/agent.sock + 令牌，超时/断开杀整组，输出首尾截断；systemd 服务 assistant-host，MemoryMax 1G），`sudo bash deploy/install.sh --host-agent` 装；接口 GET/PUT /api/host、DELETE /api/host/rules/{id}；冒烟 tests/smoke_host_mode.py
- 模型调用重试（v1.50）：app/llm_retry.py 是“模型调用失败怎么办”的唯一规则（移植 deepseek-harness retry-policy + transport 分类：AUTH/QUOTA/RATE_LIMIT/CONTEXT/INVALID/SERVER/TIMEOUT/TRANSPORT/EMPTY_RESPONSE；只重试 RATE_LIMIT/SERVER/TIMEOUT/TRANSPORT/EMPTY，500 ms×2^n 封顶 10 s ±10%，Retry-After 只定时长不加次数、超过上限不等）。OpenAI SDK 自带重试关掉（max_retries=0），read 超时 = 流式空闲超时 LLM_IDLE_SECONDS。内核 agent/loop.py：失败先 MessageBuilder.rollback 撤回本次半截文字（块清空不删），发 Retry 事件（WS turn.retry）后等待重试；重试用完按 MODEL_FALLBACKS 换备用别名（次数清零，只换一次）；空答复用完照收。llm.complete 走 retry_call。runner 的 error 文案换成 llm_retry.user_text。配置 LLM_MAX_RETRIES / LLM_RETRY_INITIAL_MS / LLM_RETRY_MAX_MS / LLM_IDLE_SECONDS / MODEL_FALLBACKS；冒烟 tests/smoke_llm_retry.py
- turn_journal.py 是“一轮回答的崩溃恢复”唯一入口（v1.52，移植 deepseek-harness session/repair.ts，嫁接 Codex turn_aborted）：runner 每轮 open() 一行 turn_journals 检查点（owner = 进程:启动 id），工具开始/结束、新块时存块与步骤（文字每 3 s 最多一次）、心跳 20 s；正常/停止/出错由 runner 落库后 close() 删掉；进程被杀留下的行由 recover() 转成 status=interrupted 消息（loop.settle_blocks 定格块，running 步骤 → stopped + TOOL_OUTCOME_UNKNOWN）——backend/worker 启动时收同类进程上次启动留下的，每轮开始前与 GET 对话时按心跳（>90 s）收别的进程的；context.build_history 在 interrupted / stopped 回复后附 <turn_aborted> 说明；冒烟 tests/smoke_turn_journal.py
- 手动整理上文（v1.53）：agent/context.py 仍是对话历史唯一规则——_snapshot 共用视图；context_state → GET /api/conversations/{id}/context；compact_now（turn_journal.busy → 409；最后一问之前全部 _fold 进 conv.summary；摘要比原文长 → inflated 不换）→ POST …/compact。一轮内压缩（agent/compact.py）的 Compactor(pinned=) 由 loop 传 plan.pinned(builder.blocks)，检查点末尾原样钉当前计划。冒烟 tests/smoke_manual_compact.py
- agent/tool_args.py 是“工具调用参数”唯一规则（v1.51，移植 deepseek-harness json-schema.ts checkValue，嫁接 Gemini 宽松校验 + getToolSuggestion、Codex 解析报错回模型）：loop 在审批之前 parse（空串 = {}；修 ```json 围栏 / 对象后多余文字 / 二次编码；修不好给行列位置；Turn.cut = finish_reason length 时直说被截断）→ check（只拦结构：必填/类型/oneOf/anyOf/additionalProperties；enum、长度、条数、大小等软约束交给工具；安全类型修正 "5"→5 等；可选参数 null = 没给；Tool.accepts 收不下的未知参数丢掉并提醒；校验必填/类型/enum/const/oneOf/anyOf/allOf/min/max，不认识的关键字放过）；有违规不执行、不进时间线，原因回模型；修补/修正附在结果末尾；回传历史里坏 JSON 换成 {}；工具名写错给最像的 3 个；冒烟 tests/smoke_tool_args.py
- app/plan.py 是“计划清单”唯一规则（移植 deepseek-harness tool-todo，嫁接 Gemini write-todos / Codex update_plan）：update_plan 工具传完整清单（≤12 步、每步 ≤80 字、去空白后不重复、最多一步 in_progress），回给模型计数 + 整张清单；块 plan 是单例卡（MessageBuilder.SINGLETONS），原地更新，这一轮结束/被停时 settled；Tool.quiet = 控制类工具不进时间线；历史里压成一行“[计划 2/5：…]”；冒烟 tests/smoke_plan.py（v1.47）
- agent/supersede.py 是“旧页面快照只留最新一份”唯一规则（v1.42，移植 Gemini CLI snapshotSuperseder）：loop 每次调模型前把本轮更早的浏览器快照段、浏览器截图换成一句占位，前面的说明与标题网址保留。
- file_seen.py 是“看过才许覆盖”唯一规则（按对话/定时任务记 read/write/edit 看到的版本；write_file check_write、edit_file check_edit）；file_edit.seek_sequence 移植 Codex（标点归一档）；冒烟 tests/smoke_file_seen.py（v1.41）
- spill.py 仍是长输出落盘唯一入口：bound 预留最坏说明后再切（≤ limit）、existing() 认出已落盘说明沿用原文件、save 独占创建 + encode_segment 文件名、_sweep 只清 NAME_RE 形状的普通文件（DAYS=30、KEEP=50）；sandbox/runner.py._spill 是镜像；冒烟 tests/smoke_spill_port.py（v1.38，移植自 deepseek-harness spill-local/spill-policy，MIT）
- browser_sessions.py 也是登录过期唯一判定（v1.36）：login_page(snap) + observe(tab, snap, auth) → expired / signed_in；标记存浏览器服务 /state/<name>.meta.json（PUT /sessions/{n}/login-state）；提示与 Home 提醒在 agent/builtin/browser.py _view；冒烟 tests/smoke_browser_login_expiry.py
- workspace_search.py 工作区搜索唯一规则（v1.35）：glob(新→旧) + grep(分组/行号/include/fixed/context)，隐藏与依赖目录默认跳过，内联 100 条 + 全量进 .spill，文件数/大小/时间上限；工具壳在 agent/builtin/workspace.py；冒烟 tests/smoke_workspace_search.py；glob 超上限时 sample_across_top_level 按顶层目录轮流抽样（v1.43，冒烟 tests/smoke_glob_sample.py）
- preview.py 端口预览唯一规则（v1.30）：签名链接、头改写、CSP sandbox；v1.44 WebSocket 转发（ws_headers / ws_close_code / ws_relay，与 sandbox/runner.py 同一份逻辑）+ 前缀头；冒烟 tests/smoke_preview.py、tests/smoke_preview_ws.py
- conversation_files.py 本对话全部文件唯一规则（v1.33）：从消息块 + write_file 步骤收拢、去重、gone 判定、打包 zip；GET /api/conversations/{id}/files[.zip]；冒烟 tests/smoke_conversation_files.py
- browser_files.py 云浏览器 ⇄ 工作区搬文件唯一规则（v1.32）：上传路径校验（不许隐藏目录、≤5 个/20 MB）、下载搬进 downloads/（同名不覆盖、过配额）、画面卡文件清单；冒烟 tests/smoke_browser_files.py
- pages_store.py 可分享网页（/p/<slug>/，带沙盒 CSP）；meta.source 记来源，find_by_source / wire
- system_alerts.py 系统提醒唯一入口（v0.95；v0.97 改按主体）：post(subject, once, …) 去重键 = subject:once（alerts_sent，begin_nested 防并发）、去处走 card_targets、replace 收起同主体旧系统卡（home_cards.alert_subject，迁移 0023）；clear(subject) 恢复后收起并清掉去重键（再坏再提醒）；active(subject) 查还没恢复的事。主体：budget、task:<id>、connector:<provider>、mcp:<服务器 id>。connectors/mcp.py guarded(db, server, call)：Unreachable（连不上/超时/5xx/非 MCP 回应 = down，401/403 = auth）→ 提醒（open connectors，无 prompt）+ 原样抛；服务器回了话（含工具自己报的 McpError）→ 收起；mcp_tools/mcp_call 工具、GET /mcp/{id}/tools（502）都经它。用户：usage.check_budget（usage）、task_runs（task:<id>）、connectors/oauth.expired（connectors：refresh 被拒 / 过期无续期凭证 / api_request 对方 401 → 卡 + ReconnectNeeded 说明给模型；键含密文指纹，同一 token 只一次；complete/forget 收起；网络错误不算失效）。智能体提议的卡（origin=agent）永不被它收起
- home_offers.py 助手提议的 Home 建议卡唯一入口（工具 offer_on_home：kind=action + origin=agent + action_label 按钮字 + action_prompt；同标题原地更新、重新未读、清稍后提醒；同时最多 MAX_LIVE=5 张，多了收起最旧的智能体建议，系统提醒不动；manage_home list 标“你提议的”/“用户已点按钮开始做”）；start() = 点主按钮开对话并链回卡上（routes/home.py POST /api/cards/{id}/start，v0.89，复用 conversation_id 列无迁移）；v0.91 配图 image_url + 原页 link_url（clean_url 只收 http(s)；配图由工具用 display.probe_image 先探测，打不开就照放不带图；原页不合格拒卡）。迁移 0021
- card_targets.py 卡片“去处”唯一入口（v0.93）：resolve(db, open) → (target, task_id)，open = usage/memory/skills/connectors/vault/pages/tasks 或 task:<id>（→ tasks + task_id）/ project:<id>（校验存在，否则 ValueError 中文）；offer_on_home open 参数（只有本人能做的事 open 不给 prompt，卡没有“去做”）；去处是项目时 start() 开的对话放进该项目（项目删了放回主聊天）。客户端两张同样的表（App action_card.dart cardTargets、网页 lib/cardTargets.ts），新去处三处各加一行。迁移 0022（home_cards.target 32→64）
- report_gist.py 报告卡“一眼”唯一规则（v1.07）：gist(blocks) → (headline 第一张摘要卡标题 ≤80, gist 第一段正文的一句话 / 摘要第一行 / 纯文本，按句截 ≤120)；worker._deliver_report 写进 HomeCard.headline/gist，/api/inbox latest 带上，day_brief 未读行附 gist；迁移 0025 用它回填。客户端只拼 `headline · gist`（app HomeCard.glance / InboxItem.glance，web lib/reportGlance.ts）。冒烟 tests/smoke_report_gist.py
- day_brief.py “准备今天”原料唯一入口（v1.03）：gather(db, now) → DayBrief（agenda 今天按钟点的报告任务：croniter 按用户时区算今天的时刻，自动暂停的也列，手动停的/面板不列，>3 次合成一行；cards 没收起的建议/提醒，稍后提醒到今天的标回来时刻；未读报告；memories 写了今天起 WINDOW_DAYS=7 天内日期或今天星期几的记忆）.text()；只读、不调模型。工具 agent/builtin/day.py day_overview；技能 skills/prep-my-day.md 先调它再 show_summary。冒烟 tests/smoke_day_brief.py。v1.05：gather(…, exclude_task) — 定时任务里跑时（worker → run_turn(task_id=) → ToolContext.task_id）不把正在跑的简报任务列进日程、不把它自己的报告卡算未读（它的失败提醒照列），day_overview 注明“用户不在，不要提问”；冒烟 tests/smoke_morning_brief.py
- card_snooze.py Home 卡片“稍后提醒”唯一入口（check/snooze/on_patch 是 /api/cards PATCH 的 on_update 钩子；wake_due 由 worker 每轮叫醒到点的卡：清空 + 重新未读 + 顶到最前；wire 让 snoozed_until 总带时区；manage_home 的 snooze/unsnooze 也走它；建议卡和收件箱报告都能推迟，/api/inbox latest 按 updated_at 取，叫醒的报告会让客户端横幅再弹一次）
- reply_files.py 把一条回复存成项目文件唯一入口（v1.15）：markdown(blocks)（真表格、带标题链接、摘要/草稿带标题；审批/表单/记忆/浏览器卡不进文件）、file_name（摘要/草稿/表格标题 > 正文标题 > 第一行，≤24 字，非法字符去掉，都没有 = “回复 MM-DD HHMM”）、save(db, mid, pid?)（项目 = 传入或对话所在，写项目根目录，同名不覆盖“名字 2.md”）；POST /api/messages/{id}/save-to-project；冒烟 tests/smoke_save_reply.py
- conversation_share.py 分享对话唯一入口（render 服务端渲染只读快照：Markdown 子集先转义再加标签、无脚本；share/unshare/state；source="conversation:<id>"，同一对话链接不变；load(db,cid) 带消息读对话；智能体工具 share_conversation（agent/builtin/pages.py，scope=conversation：ToolContext.conversation_id 有值才提供，“把这段对话分享给朋友”/“停止分享”）与客户端分享面板同一快照同一链接）
- memory_digest.py “我对你的了解”：全部记忆 → 一段第二人称概括（单行表 memory_digest，id=me）。GET /api/memory-digest 零模型调用，只比指纹（每条记忆 id+updated_at 的哈希）报 stale；POST 才调一次 SUMMARY_MODEL（kind=digest，输入按 INPUT_CHARS 截断、profile 优先）；从不自动生成
- usage.py       用量与花费：llm.py 每次调用后 record() 一行（自己的短会话，失败吞掉）；runner 用 scope(对话id) 归属；report() 出今天/本月（用户时区）+ 本月逐日 daily + 本月最花钱的对话 conversations（_top_conversations：外连接一次查标题，前 TOP_CONVERSATIONS=5，删了的对话 title=null）供 GET /api/usage，conversation_report() 出单个对话累计供 GET /api/conversations/{id}/usage（两者共用 _aggregate 形状）；check_budget() 记账后检查本月花费是否跨过 MONTHLY_BUDGET×BUDGET_ALERTS 的某档 → Home action 卡（target=usage），去重表 alerts_sent（key=budget:年月:档:预算），新档收起旧预算卡

云浏览器服务 browser/
- service.py     唯一运行 Chromium 的服务：快照、点击、输入、截图、人工接管；拦截内网地址

沙盒服务 sandbox/
- runner.py      唯一接触 Docker 的服务（前台 /exec；后台 /jobs/start|cancel|alive：setsid 脱离启动、整组杀；空闲回收跳过有任务在跑的容器；镜像重建后旧容器下次用到时自动换新镜像）
- image/         工作区容器镜像（非 root；预装 python、node、git、jq、ripgrep、zip、sqlite3、poppler、ImageMagick、中文字体——改清单同步 backend/app/workspaces.py PREINSTALLED）；
                 workspace-env.sh → /etc/profile.d：HOME = 工作区/.home，pip / npm -g 用户级安装落在工作区，换镜像、删容器都不丢；缓存在 /tmp

前端 frontend/src/
- styles/tokens.css  设计令牌，唯一样式来源（v2.1：字重只写 var(--fw-body/title/strong)，主操作用 --ink 不用 --accent，卡片层次用 inset 0 1px 0 var(--glass-highlight) 不用外投影）；深色只认 <html data-theme="dark">，减少透明度只认 <html data-solid>（玻璃 → 实色、--blur 0）
- lib/theme.ts       外观偏好（跟随系统/浅色/深色）；index.html 首帧脚本与它同键 appearance
- lib/look.ts        本机外观偏好（设计 v2）：头像色（--avatar/--on-avatar，4 预设 + 色相环）+ 减少透明度；首帧脚本同键 look.solid
- ui/                共享原语：Page（可带 footer = 底部浮层）、PageHeader（子页面浮动玻璃标题栏）、FloatingFooter（量高度给内容让位）、Section、Sheet（v1.16 真模态：打开焦点进来、Esc 只关最上面一层、关掉焦点回原处；Menu/确认框的 Esc 在捕获阶段先处理并 preventDefault）、Toggle、Segmented、Hint、Menu（v1.12 弹层挂到 body、量位置、放不下往上翻，不会被卡片裁掉）、Highlight、图标；
                     ui/glass.css + glass.tsx 是材质零件（.glass 真玻璃只给浮层 / .glass-card 假玻璃卡 / .tile / .pill / .wide-pill / Avatar / ValueTile），与 App ui/glass.dart 一一对应，页面不自己写 backdrop-filter
- shell/             骨架（设计 v2）：页面铺满 + 浮动顶栏 TopBar（左 = 页面通过 <ShellLead> 传进来的上下文按钮，中 = 主页/聊天/项目 分段胶囊，右 = 头像 → /me）；
                     只在 / /chat /projects 显示（isShellRoot），“我的”及子页面、项目对话自带标题栏。LaunchComposer = 主页/项目页底部的输入胶囊（发出 = 新对话，聚焦磨砂 + 收起 + 建议）
- 截图回归：frontend/scripts/shots.py（假接口 + Playwright，浅/深 × 桌面/手机：一级页、聊天（含信息表单 chat-ask）、7 个子页面、2 个弹层、项目对话（存到项目文件 / 引用选择器 / 待发名片，v1.16）、登录页，输出 /tmp/shots/web；用法见文件头）。网页聊天贴底跟随在 features/chat/ChatView.tsx（pinned + ResizeObserver，只有往上翻才取消）。建议卡配图由 shots.py 的 image() 应答一张 SVG。本机缺 Chromium 依赖时：`sudo -n /tmp/pw/bin/playwright install-deps chromium`。卡片里的表单输入框是紧凑版（blocks.css .blk-form-field，与 App compactField 同义）
- 网页宽屏版式（v0.94）：页面要宽版就 `<Page wide>`（ui.css .page-inner.wide，≥1100px 放宽到 --content-wide，窄屏不变）；主页 ≥1100px 是 .home-grid 两栏（.home-main 为你准备 + aside.home-rail 面板/收件箱/今天，--rail-w），断点只此一个，别各页自造。截图 shots.py 有 `-home-end`（主页滚到底）；项目列表也用 `<Page wide>`（≥1100px 三列）。聊天页 ≥861px（有历史面板）标题是聊天列列头：.chat-caption 与 .convs-head 同高（top shell-top、高 topbar-h），左缘对齐消息，--thread-top 相应下移（v0.96）
- 网页确认/提示：只用 ui/dialog.tsx 的 `await confirmDialog({title, text, action, danger})` / `noticeDialog(title, text)`（App 根挂一个 DialogHost；居中玻璃卡 .dialog，两颗等宽胶囊，危险动作实心 --danger，= App confirmDanger）。`npm run build` 先跑 scripts/check-arch.mjs：原生 confirm/alert/prompt、styles/base.css 以外的 @keyframes、blocks/ 与 features/chat/ CSS 里的 --surface-2/--bg 都会让构建失败
- 网页玻璃规则：浮层用 .glass（模糊），列表卡 .glass-card / .list（不模糊），弹层 .sheet = --glass-sheet；坐在玻璃上的填充（输入框、分段、标签、进度条底、代码块）一律 --tile，不用 --surface-2 / --bg
- 网页材质只在 styles/ 与 ui/：投影用 `var(--elev-card|float|raised|knob)`，模糊只靠 `.glass` / `.glass.raised`（弹层、横幅）/ `.glass-drawer`（窄屏抽屉）；页面 CSS 不写 --shadow-* / backdrop-filter / --surface-2（npm run build 里的 scripts/check-arch.mjs 会拦）。
- 网页强调色克制（v0.60，= App design_test）：`var(--accent*)` 只做信号（未读点、进度/运行中、链接/搜索命中、焦点环、唯一关键状态）；数据条/图表用 `--ink`，其余文字用 `--text-2`。check-arch 规则 5 按文件登记次数（ACCENT 表），新增先登记角色。
- features/          按栏目分：home、chat、projects、me、auth
- blocks/            每种卡片一个组件，registry.ts 登记
- hooks/             useChat（消息流 + 发件箱 + 搜索定位 focus/takeFocus：ChatView 按 data-msg-id 滚到中间并加 .flash）组合 useConversations（列表/搜索/置顶/改名/删除）、useResource
- lib/socket.ts      长连接：只报连接状态（connecting/open/down）、send() 写不出去返回 false、reconnectNow()；不排队
- lib/outbox.ts      发件箱持久化（localStorage，按服务器 + 对话分开：outbox.<对话id> / outbox.new.<main|项目id>），只有 useChat 读写；退出登录清空
- 发件箱规则（与 App 相同）：消息的 outbox 状态（queued/failed）只归 useChat；一次只排/飞一条；flush effect 是唯一写出点、persist effect 是唯一持久化点；45 秒没连上或发出后回复未开始就断线 → 失败；回复中途断线 → 连上后重拉；审批回复不排队；恢复的一律是“发送失败”，不自动补发
- 消息操作（与 App 相同）：复制 = lib/copy.ts 把块转 Markdown（纯客户端）；重新生成/重试 = WS `message.regenerate`，只在最后一条回复（或失败后错误条的“重试”）上出现，useChat 的 canRegenerate 是唯一判据；先本地撤旧回复，被拒或开始前断线就重拉对话。后端：agent/runner.rewind 删旧回复（不留版本），ws._after 让各轮按序排队而不是丢弃。编辑最后一条用户消息 = `message.regenerate` 带 `text`（rewind 原地改用户消息，附件保留）；useChat.editableId 是唯一判据，编辑态是 ChatView 的界面状态（Composer 编辑条、草稿暂存、Esc 取消、空输入框按 ↑ 编辑）。导出对话 = lib/export.ts（conversationMarkdown 复用 copyText，与 App models/export.dart 同规则）+ useConversations.exportMarkdown 拉全文 → Blob 下载；行菜单“导出 Markdown”
- 停止生成（与 App 相同）：WS `message.cancel`；ws.py 的 `_Turns` 管一条连接上的轮次（排队、记住正在跑的那轮、停止时先 set 停止信号再 cancel、断线取消全部）；`agent/runner.run_turn` 被取消时把 `MessageBuilder.partial()`（去空文字块、pending 审批卡 → expired）以 `messages.status=stopped`（迁移 0010）落库并发 message.done，没内容就发 message.stopped；用户停止 → 吞掉取消、下一轮照跑，断线/关机 → 落库后继续抛。`Message.to_wire()` 是消息协议形状的唯一出口。它也带 `created_at`（带时区 ISO；SQLite 读回的无时区值按 UTC 补，客户端画日期分隔用；冒烟 tests/smoke_message_time.py）。网页：useChat canStop/stop，Composer 生成中换停止键（Esc 同效），MessageView 标“已停止”。冒烟：tests/smoke_stop.py
- lib/models.ts      可选模型（effectiveModel / toChoice，与 App ModelCatalog 同规则）+ localStorage 缓存；hooks/useModelCatalog.ts 读它，features/chat/ModelChip.tsx 经 Composer 的 accessory 插槽显示；选择只归 useChat（model / setModel）
- lib/cardTargets.ts  Home 卡 target → 按钮（文案/路由/图标），与 App features/home/action_card.dart 同表
- lib/usage.ts       用量报表类型 + 金额/token 格式（与 App models/usage.dart、ui/format.dart 同规则）；设置页 features/me/UsageCard.tsx 展示（预算条 .meter，三档 ok/near≥80%/over）；按模型列表 features/me/ModelUsageList.tsx 共用；聊天顶栏 features/chat/ChatTitle.tsx + hooks/useConversationUsage.ts（换对话/回复结束时取，出错不显示）显示本对话用量，点开 Sheet 明细；本月逐日柱状图 features/me/DailyChart.tsx（SVG，role=slider 键盘换天，柱子动效 @keyframes bar-grow，与 App usage_chart.dart 同规则：日均预算虚线、超过的天用 --warning）；本月最花钱的对话 features/me/TopConversations.tsx（点行 = nav("/chat", {state:{open:id}})，与收件箱同一条路；占比 shareOf 与 App 同规则；选一天看明细 features/me/DayBreakdown.tsx（DailyChart 的 detail，读数跟手、明细只在按下/松手/键盘时换；一律 GET /api/usage/days/{date}，今天途中/失败先用报表 today；按模型行 + 那天最花钱的对话行 .day-row，对话行点开同样 nav("/chat")，份额 dayShareOf）
- lib/usageCsv.ts    本月用量导出 CSV（纯客户端，取已加载报表；与 App models/usage_csv.dart 逐字节同规则：长表“类别”列 汇总（含上月同期/上月全月，来自 last_month）/每天/模型/对话，没定价花费留空，防公式注入，BOM+CRLF）；UsageCard 右上角下载按钮走 lib/export.ts 的 downloadText。
- features/me/MonthCompare.tsx  月卡“比上月同期”标签（lib/usage.ts monthDelta/FLAT_WITHIN，与 App MonthCompare 同规则：涨 warning、降 accent、±5% 持平、同期为 0 只给说明）。后端 usage._last_month 按日历对齐同期，报表字段 last_month。
- lib/history.ts     对话分组纯函数，与 App history.dart 同规则
- App.tsx            路由表

## 扩展规则
- 新工具：agent/builtin/ 下新建文件，用 @tool 注册，自动加载；只在项目里可用的加 scope="project"；有风险的加 risk=函数（返回理由即弹审批卡）
- 上下文预算：只在 agent/context.py 管。原文按字符预算（HISTORY_CHARS，默认 24000）从新往旧装，装不下的折叠进 conversations.summary（便宜模型 SUMMARY_MODEL，一次压到预算一半留余量）；当前一问及之后永远是原文，所以重答/编辑不碰摘要；摘要失败就硬截断，不影响聊天
- CRUD 资源要带“算出来的只读字段”（不存库）：crud_router(extra=lambda obj: {...})，所有增删改查接口一致带上（例：任务 next_run_at）
- PATCH 时要派生字段或拒绝：crud_router(on_update=fn(obj, changes))，在写库前改 changes（例：项目 brief → brief_by/brief_updated_at）
- 只读字段要查库（计数、聚合）：crud_router(annotate=async (db, objs) -> {id: {...}})，一批记录一条 GROUP BY，别在 extra 里逐条查（例：项目 conversation_count / last_active_at）
- 新块类型：blocks.py 加模型 + agent/builtin/display.py 加 show_* 工具 + App models/block.dart 与 blocks/ + 网页 blocks/registry.ts（例：stats；v0.78 draft/summary/images 三张内容卡都在 display.py，客户端 app blocks/content_blocks.dart、web blocks/ContentBlocks.tsx；v0.81 products 在 display.py、order 在 agent/builtin/orders.py，客户端 commerce_blocks.dart / CommerceBlocks.tsx）
- 要用户点头才执行的工具：`risk` 返回理由即走审批；想让审批卡就是业务卡（订单卡），再给 `card=fn(args)->块`，内核补 id/state=pending，批准/拒绝后更新 state，停止时 pending 变 expired。card 抛 ValueError = 参数不对，错误交回模型、不弹卡。冒烟 `python tests/smoke_commerce_cards.py`
- 每个对话选模型：可选列表只在 settings.chat_models（CHAT_MODELS），解析只在 llm.chat_model（不认识 → 默认）；客户端的选择经 runner.apply_model 落到 conversations.model（WS user.message / message.regenerate 的 model 字段，或 PATCH）；定时任务、摘要不读它。新增“按对话的设置”照这个路子：列 + PATCH + 随消息可带
- 模型调用：只经 llm.py（stream_turn/complete/embed），它负责记账（流式用 stream_options.include_usage，最后一包带用量）；新代码不要直接用 openai 客户端，否则花费漏记。单价 MODEL_PRICES（每百万 token，写入时算好存下，改价不改历史），MONTHLY_BUDGET 只提醒不拦截；中途停止的那次调用拿不到用量、不记。
- 系统提醒（不是定时任务产出的）一律走 system_alerts.post(subject, once, title, text, open, prompt?)：kind=action + origin 空 + 去处 open（经 card_targets.resolve，如 usage / connectors / task:<id>）+ 去重表 alerts_sent（key 自带周期），不要在卡上记“发过没”——用户删卡后不应重发；事情恢复了调 system_alerts.clear(subject)。subject = 出事的那个东西（不是去处）。只有本人能做的事（重连账号）不写 prompt，客户端眉题“需要你亲自处理”。新去处在两端的 cardTargets 表各加一行（去处要落到具体对象时 route 用占位，如 /me/tasks/{task} 由 cardRoute 换成卡上的 task_id）
- 改表结构：改 models.py → `alembic revision --autogenerate -m 说明`
- 新卡片：blocks.py 加类 → blocks/ 加组件 → registry 登记
- 新简单资源：models.py 加表 → resources.py 加一行
- 新页面：features/ 下加组件 → App.tsx 加一行路由
- 新一级栏目：shell/AppShell.tsx 的 TABS 加一项（一级页面的 .page 由 shell.css 在浮动顶栏下缓入淡出，页面自己别再写顶部遮罩；v1.06）
- 无障碍：没有可见文字的按钮/链接必须 aria-label（Toggle 的 label 是必填参数）；焦点环、减少动态、跳到主要内容都在 styles/base.css 末尾统一处理，组件里不要 outline:none

## 消息协议（WebSocket /ws）
客户端 → `{type:"user.message", conversation_id?, text}`
服务端 → `message.start` → `block.start` / `block.delta` / `block.update` / `tool.status`（交替） → `message.done`(完整块列表) / `error`
客户端 → `user.message`（text、attachments、project_files、project_id）/ `approval.reply`（id、approved）

## 安全边界
- 密钥：只在 `vault.headers_for()` 解密，直接进 HTTP 头；接口无明文读取；响应里回显的密钥会被抹掉
- 高风险动作（提交/推送代码、强删、发布、对外写请求）先弹审批卡；定时任务无人值守时一律拒绝
- 代码执行在独立沙盒服务里，后端和模型都碰不到 Docker
- OAuth Token、MCP 令牌同样加密；模型只知道“哪些域名已授权”
- 云浏览器拦截所有内网/回环地址；付款、下单、发送类按钮需审批；密码和验证码由你在实时画面里自己输
- Pages 用 CSP sandbox 提供，页面脚本拿不到 App 登录信息；元数据（含 published 下线状态）只经 pages_store 读写，公开访问只走 public_html（下线与不存在同一个 404），改内容保留发布状态

## 内存预算（参考）
postgres ~200M、litellm ~300M、searxng ~150M、backend+worker ~300M、browser 打开时 ~600M、每个沙盒容器上限 1G。
2G 内存的 VPS 能跑，但别同时开浏览器和多个项目沙盒；4G 比较从容。

## 看图（v0.72）
- `app/vision.py` 是图片进模型的唯一入口；`agent/context.py` 只调用它。当前这一问的图片：模型别名在 `VISION_MODELS` → 原图（Pillow 缩到 `IMAGE_MAX_SIDE`，统一 JPEG data URL）；更早的图或模型不能看图 → `VISION_MODEL` 写一段描述（含图中文字），缓存在 `data/captions/<上传id>.txt`，每张图只花一次钱。
- 描述失败只给图片名、这一轮照常，下一轮自动重试；单轮最多补 6 张描述。用量记为 kind=vision。
- 工具也能给模型看图：工具在 `ToolResult.images` 里放 `ToolImage(name, bytes)`，怎么给由 `vision.for_tool` 决定——能看图的别名 → 在本步工具结果之后补一条带原图的 user 消息（明确写“不是用户说的话”，只活在本轮工具循环里、不进历史）；不能看图 → 描述写进最后一个工具结果（按内容哈希缓存 `captions/sha-*.txt`）。一步最多 3 张，单张 ≤10MB。现有来源：`read_file` 读项目里的图片、`browser_look` 截云浏览器当前画面。新工具要给图只管填 images，别自己拼消息。
- 冒烟：`python tests/smoke_vision.py`、`python tests/smoke_tool_images.py`。

## 任务中的表单卡：登录 / 验证码（v0.83）
- 工具可以声明 `form=` 钩子（`agent/tools.py` `Tool.form(ctx, args) -> 表单卡 | None`）：执行前需要问用户时返回一张 `form` 卡（不带 id/state），内核（`loop._ask_form`）插卡 → `ctx.ask(id, 卡)` 等答复 → 卡片改 submitted/cancelled → 值以 `form=FormReply(values, remember)` 传给 `run`；取消就不执行。模型传来的 `form` 参数一律丢弃。
- 等答复的中心是 `agent/approvals.py`（审批 `wait/resolve` + 表单 `wait_form/resolve_form`），WebSocket `form.reply` 进来；无人值守（worker）`ctx.ask = nobody` → 取消。
- 用户填的值只在内存里交给工具：不写进卡片、不落库、不进给模型的工具结果。
- 现有使用者：`browser_login`（保险箱有该站登录就直接代填、不弹卡；没有 → 登录卡，用户可勾“记住到保险箱”）、`browser_code`（短信/邮箱验证码卡，填进指定输入框并回车）。图形验证码、扫码仍走实时画面接管。
- 冒烟：`python tests/smoke_signin_form.py`。

## 助手问你要信息：ask_user（v0.87）
- `agent/builtin/ask.py` 的 `ask_user` 复用同一条表单卡通道，purpose=info：缺只有用户知道的细节（地址、电话、人数、几选一）时一张卡问齐。`ask_card(args)` 把模型参数整理成卡：字段名服务器编（q1..q6）、去掉空 label、不收 password/code（降成 text）、候选 `options` ≤6、`optional` 选填、按钮 ≤8 字、`note` 说为什么问。
- 和 login/code 相反：info 的值是用户有意告诉助手的 → 交给模型，`loop.form_answers` 把非空答案写进卡片 `answers`（回显、落库、`blocks_to_text` 带上，下一轮模型也记得）。勾“记进记忆” → 每个答案 `label：value` 经 `memory_store.save`（profile 类）存下并附记忆卡。
- 无人值守（`ctx.ask is nobody`）不弹卡，告诉模型按已知信息做、必要时 `offer_on_home`。
- 冒烟：`python tests/smoke_ask_user.py`。
- 思考强度（v1.54）：app/reasoning.py = 唯一规则（MODEL_REASONING 解析与校验、resolve(alias, choice) 回落默认、for_helper 最低档、rejected/mark_unsupported、catalog）；llm._create 是唯一发请求处（带 reasoning_effort，400 拒收 → 去参数重发并记住）；conversations.reasoning（迁移 0032），runner.apply_choice（WS model+reasoning），ToolContext.effort → loop/compact/subagent。冒烟 tests/smoke_reasoning.py
- 跨轮工具轨迹（v1.55）：app/agent/tool_trace.py = 唯一规则（record：这一轮的 tool_calls + 结果按 Codex normalize 配对清洗、记录时截断、快照占位、打码、超额丢最早批次；valid / replay / digest）；messages.trace（迁移 0033，不上协议）；MessageBuilder.transcript/base + trace()；context._traces 最近 HISTORY_TRACE_TURNS 条重放，其余附 digest（也进摘要），_sizes 按重放大小算预算。冒烟 tests/smoke_tool_trace.py
- 回复怎么结束的 + “继续”（v1.56）：loop.Done.ended（done / wrapped 预算用完收尾 / looped 原地打转被叫停，打转优先）→ runner 存成消息 status（无迁移，String(16)）；turn_journal.history_note 给 wrapped / looped 附 <turn_wrapped> / <turn_looped> 说明。App models/reply_end.dart = 唯一规则（ReplyEnd 五种、label / continuable / warn / continueHint，continueText）；MessageView 行尾说明（窄屏省略）+ “继续”小胶囊（RiseSwitcher 收起，读屏独立节点）；ChatView 只给最后一条且能发消息时。网页 lib/messageStatus.ts（endLabel / continuable / endWarns / CONTINUE_TEXT）+ .msg-continue。冒烟 tests/smoke_reply_end.py；App test/reply_end_test.dart
- 检查点存工具轨迹（v1.57）：turn_journals.trace（迁移 0034）；Journal.save 每次存 builder.trace(missing=turn_journal.trace_missing(steps))——缺结果的调用按步骤状态补：running → TRACE_UNKNOWN，done/error → TRACE_LOST（结果在 done 事件之后才进消息列表）；算不出来只记日志存空。recover 把 valid 的轨迹带进 interrupted 消息的 messages.trace，context 照 v1.55 规则重放。tool_trace.record / MessageBuilder.trace 新增 missing（字符串或 call_id → 字符串，默认 ABORTED 不变）。冒烟 tests/smoke_journal_trace.py
- 连续写错参数（v1.58）：tool_args.Streak（每轮一个，loop 传给 _call_tool）——解析失败 / 校验不过 / 工具不存在都算一次；同一工具第 HINT_AT=3 次起在报错后附 tool_args.signature（必填在前，类型含 enum/oneOf/array<…>，说明截 60 字，最多 16 个参数）+ 换思路建议；不存在的工具第 3 次列出全部可用名；不分工具连续 STOP_AT=6 次 → stopped：同批剩下的调用回 loop.SKIPPED_BAD，回复以 tool_args.STOP_NOTE 结尾，ended=looped（客户端已有“继续”）。任何一次参数通过即清零。无迁移。冒烟 tests/smoke_bad_args.py
- 任务自己的模型 / 思考（v1.59）：scheduled_tasks.model + reasoning（迁移 0035）；规则只在 task_store.model_choice / reasoning_choice（REST 校验，""/null = 默认，非法 422）和 task_store.conversation_for（worker 开任务对话的唯一入口，抄上这两项；运行时仍走 llm.chat_model / reasoning.resolve 回落）。App features/me/task_model_picker.dart（表单里计划下面：模型 Chip + 思考 Chip，换模型清掉新模型没有的档；详情页“深度 · 思考 高”）；网页 features/me/TaskModelPicker.tsx 同规则。冒烟 tests/smoke_task_model.py
- 只读工具并行（v1.60）：agent/parallel.py 是唯一规则（移植自 deepseek-harness tool-calls + executionMode）：Tool.parallel（True 或 参数→bool；默认独占）；mode 失败即独占（risk/form/quiet/grants/解析失败/判定抛错）；groups 连续可并行成组、独占自成屏障；pool 滚动池（settings.agent_parallel_tools=8，≤1 关）事件随到随交，loop 按模型顺序提交结果；每个并行调用一份浅拷贝 ctx（ctx.live 不互相覆盖，前提：并行工具不碰 ctx.db）；标了 parallel 的：read_file/list_files/glob/grep/web_search/web_fetch；系统提示加一句 parallel.PROMPT。冒烟 tests/smoke_parallel_tools.py
- 工作区规则文件（v1.62）：app/workspace_instructions.py 是唯一规则（移植自 deepseek-harness agent-instructions，MIT）。工作区根目录的 AGENTS.md / CLAUDE.md / AGENTS.local.md / CLAUDE.local.md 每轮进系统提示（同目录内容相同只留一个，单文件 >1 MiB 不读，符号链接出了工作区不读，隐藏目录不算）；子目录里的规则在 read_file / write_file / edit_file / list_files 碰到那里时追加到工具结果（新出现 / 改过 / 删了，一轮只说一次，ToolContext.instructions）。超预算 settings.workspace_instructions_bytes（默认 16384，0 = 关）时先省最宽泛的、再截断最具体的并在开头注明。GET /api/conversations/{id}/context 多 instructions，两端在“对话记忆”卡里列出。冒烟 tests/smoke_workspace_rules.py
- 提示缓存（v1.63）：app/prompt_cache.py 是唯一规则。系统提示由 build_system_prompt 返回 Prompt：稳定段（人设、并行提示、技能、授权服务按名排序、MCP、项目/工作区、AGENTS.md、主机模式、子助手角色）在前，每轮会变的（当前时间、相关记忆、滚动摘要、压下的任务结论）在后；工具按模块名排序注册。这样一轮里十几次模型请求、以及相邻两轮，开头逐字相同，供应商自动缓存命中。命中数 cached_of(usage) 兼容 OpenAI/阶跃 prompt_tokens_details.cached_tokens、DeepSeek prompt_cache_hit_tokens、顶层 cached_tokens、cache_read_input_tokens（移植 deepseek-harness normalizeUsage 的校验），记进 usage.cached_tokens（迁移 0036）；MODEL_PRICES 第三个数 = 命中单价。PROMPT_CACHE_KEY=true 按对话发 prompt_cache_key（Codex 做法；不认的供应商 400 后自动去掉）。用量页 / 本对话用量显示“缓存命中 N%”。冒烟 tests/smoke_prompt_cache.py
- 话说一半就停（v1.64）：app/agent/next_speaker.py 是唯一规则（移植 Gemini nextSpeakerChecker）。模型一步没调用工具、本该结束时先过本地闸门：回复结尾像“接下来我去……/让我先……/Let me…”、以冒号省略号收尾、被长度上限截断、或用完工具一句没说，才可能续；问句或请用户回复的一律不续。auto 模式下闸门打开才问一次 summary_model 判官（只看最后一问 + 回复结尾，返回 {reasoning, next_speaker}），判 model 就补一句“[系统提示] 继续”再来一圈，同一条回复接着写；rules 只看规则，off 关闭；每轮最多 NEXT_SPEAKER_MAX=2 次，预算最后一步不续。无迁移、无客户端改动。冒烟 tests/smoke_next_speaker.py
- 旧输出遮盖（v1.65）：app/agent/tool_mask.py 是唯一规则（移植 Gemini toolOutputMaskingService）。每次调模型前从新往旧扫本轮的工具结果：最新一批和最近 TOOL_MASK_PROTECT_TOKENS=24000 token 的输出原样；更早的累计 ≥ TOOL_MASK_MIN_TOKENS=12000 才成批换成 <tool_output_masked> 预览（命令留退出码 + 首尾 10 行，其他首尾 250 字）+ 全文路径（工作区 .spill/，已有落盘文件就沿用）。遮过的不再变（提示缓存前缀稳定）；豁免 use_skill/ask_user/update_plan/delegate/browser_*；存不下或不省就不遮。MIN=0 关闭。无迁移、无客户端改动。冒烟 tests/smoke_tool_mask.py
- 长日志要点（v1.66）：app/agent/distill.py 是唯一规则（移植 Gemini toolDistillationService）。run_command/host_command/job_status/api_request/mcp_call 的结果超过 tool_result_max 被首尾截断（或沙盒已截断落盘）时，从被省略的中间段挑信号行（报错、失败、退出码、文件:行号、测试计数；@字符位置，可 read_file offset 回读；相同行 ×N；≤30 行）补在末尾；TOOL_DISTILL=auto 且全文 ≥ TOOL_DISTILL_CHARS=80000（≤100 万）时改为一次 summary_model 摘要（输入只发开头 + 信号行 + 结尾 ≤24k 字，15 s 超时，失败退回信号行；用量 kind distill）。rules = 只挑行；off = 照旧。总长 ≤ 上限。无迁移、无客户端改动。冒烟 tests/smoke_distill.py
- 多文件补丁（v1.69）：app/apply_patch.py 是唯一规则（移植 Codex apply-patch）。工具 apply_patch(patch)：*** Begin Patch / Add File / Delete File / Update File（+ Move to）/ @@ 定位 / 上下文与 +- 行 / End of File / End Patch；先在内存里按顺序算完整份（同一文件多段看前段结果），任何一段对不上就一个都不动，写盘 OSError 全部还原（Codex 是顺序落盘，我们改成全成或全不动）；路径限工作区、拒隐藏目录、>8 MB 不按行改、非 UTF-8 只能删或整篇 Add；覆盖 / 改名到已有文件走 file_seen.check_write，按行改 / 删走 check_edit；配额按净增长；ctx.changes 记基线（整轮撤销照样覆盖）；时间线一步 changes 列表（deleted / moved_from）。run_command 整条是 `apply_patch <<'EOF' … EOF`（可带 `cd 子目录 &&`）时不进沙盒直接按补丁改（同 Codex invocation.rs）。子助手可用。冒烟 tests/smoke_apply_patch.py（Codex 解析/替换单测翻译 + 25 个端到端场景 fixtures + 真实一轮）
- 计划模式（v1.71）：app/plan_mode.py 是唯一规则（Gemini CLI 计划模式的硬拦策略 + Codex plan 提示词骨架 + deepseek 按对话持久化与切换提示）。对话可切到“计划”（conversations.mode，迁移 0039）：系统提示加计划规则（稳定段），每次工具调用前 plan_mode.refusal 只放只读工具（读文件 / 搜索 / 看网页 / 只读子助手 / 展示卡），写入、装包、外部操作一律拒（时间线 denied）；run_command 只放 app/readonly_command.py 证明只读的脚本（移植 Gemini commandSafety：白名单 + git/sed/find/rg 细则，&& || ; | 之外的连接、重定向、$、子 shell、heredoc 都不算）。exit_plan_mode(plan) 弹方案卡（plan_review，走审批流程）：批准 → 本轮立刻拿掉系统提示里的规则继续按方案做、对话切回 default、推 conversation.mode；没批准 → 留在计划模式问要改哪里。两轮之间切换时下一轮先告诉模型一句（mode_seen）。子助手继承只读。App / 网页输入框多一枚“计划”钮。冒烟 tests/smoke_plan_mode.py
- 批准的方案存成文件（v1.72）：exit_plan_mode 批准后写进工作区 plans/<日期>-<标题>.md（plan_mode.plan_file：上一份同标题 → 原地更新，否则新文件、重名 -2），conversations.plan_path（迁移 0040，私有）；runner 每轮文件还在就在稳定段加“已批准的方案”（approved_prompt：普通模式“先读、要改先问再更新”，计划模式“默认在它上面改”）；写盘走 changes 基线 / file_seen / quota（磁盘满 → 仍批准、告诉模型没存）。方案卡多 workspace/path，conversation_files 把已批准卡的路径列为 written。冒烟 tests/smoke_plan_file.py。
- 批准的方案 → 进度清单（v1.73）：plan_mode.plan_steps(text) 认步骤（步骤类小节的编号列表 → 步骤类小节的圆点/复选框列表 → 全文第一组编号列表；2–12 步、不重复；加粗短语/链接/行内代码清理、超长截断；子项续行不打断，代码块不算），seed_items 第 1 步 in_progress；exit_plan_mode 批准后回 plan 块（explanation “按批准的方案”）+ LIFTED_SEEDED + 整张清单，认不出 → LIFTED_FREE。内核新增 ToolResult.card：执行后合并进这次调用已批准的卡（Granted.index）；方案没存成 → card {"path": ""}。冒烟 tests/smoke_plan_steps.py。
- 同时开机上限 + 腾内存（v1.74，核心回炉 9，学 E2B 容量上限 + 只留盘的暂停）：sandbox/runner.py MAX_RUNNING（SANDBOX_MAX_RUNNING，默认 3，0 不限；install.sh 小机 2）；开机前 _make_room 按 room_order（最久没用在前；in_use 计数的前台命令/预览 WebSocket 与 ROOM_GRACE_S=60 秒内用过的不挑）停闲容器，后台任务在跑的跳过，都在忙照开（软上限，持 _room_lock）。stopped_by（idle 空闲回收 / room 让位）进状态 stopped_by/stopped_at；下一条前台命令开机时结果带 woke → computer.wake_note 提醒模型重启之前前台起的程序（后台任务开机不提醒）。冒烟 tests/smoke_sandbox_room.py。
- 按宿主机剩余内存腾位置（v1.76，核心回炉 11）：_make_room 开机前读 /proc/meminfo 的 MemAvailable（mem_available/mem_short 纯函数），不够 SANDBOX_MEM + SANDBOX_HOST_RESERVE（默认 256m，0 关）时台数没超也按同样顺序停闲容器，停一台重读一次；读不到只按台数；原因仍记 room。冒烟同上 2b 段。
- 用户自己跑命令（v1.77，学 Codex `!` user_shell）：输入框整条 `!命令`（或全角 ！）不调模型，直接在工作区电脑上前台执行（app/user_shell.py 唯一入口；执行/结果整理与 run_command 共用新 app/foreground.py）；ShellBlock 卡实时输出；拦危险命令；停止 / 再跑一次 / 编辑成普通话交给助手；下一轮模型历史里是 Codex 原格式 <user_shell_command> 用户侧记录（输出 ≤10000 字中间省略，学 Gemini）。USER_SHELL / USER_SHELL_SECONDS。冒烟 tests/smoke_user_shell.py。
- 停机原因落盘（v1.78，核心回炉 12）：sandbox/runner.py 的 stopped_by / woke 只经 _mark_stopped/_woken/_take_woke/_forget 改，改完原子写 SANDBOX_STATE（默认 /state/stopped.json；compose 挂 data/sandbox，install.sh 建目录）；启动 _adopt 用 load_state（只认合法 id + idle/room，丢 >30 天/未来时间）+ reconcile（容器没了丢，记着停了却在跑 → woke）读回；写盘失败只记日志。冒烟 tests/smoke_sandbox_room.py 2c 段。
- 常驻后台任务（v1.80，核心回炉 13）：`run_command keep_alive=true` 起要一直开着的服务 / 机器人（对标 Manus Cloud Computer 常开进程）。backend/app/job_restart.py 是唯一重启规则（systemd on-failure 语义：0 = 做完不拉起；非零 / OOM / 进程没了 = 拉起；退避 5→300 秒翻倍，跑满 60 秒清零，连续 6 次很快退出就放弃并通知助手）；jobs.py 负责动作（_end 排队、worker tick 到点 _relaunch、日志追加 + 轮转进 log.1、after_restart）。“这台电脑”重启不停常驻任务。迁移 0041；冒烟 tests/smoke_job_keep_alive.py。
- 消息里的 @文件（v1.79，助手大脑 ae）：backend/app/file_mentions.py（移植自 Gemini CLI atCommandProcessor / atCommandUtils）是唯一规则：parse（邮箱、代码、全角标点、引号、转义、行号后缀）→ resolve（原样 → 去行号 → 中英交界截短 → `**/*名字*` 取最新，最多扫 5000 个文件；目录/隐藏/越界不认）；routes/ws._project_files 把它接在选择器选的后面（!命令 不解析，编辑消息时 _add_mentions 补上）。App features/chat/mentions.dart（mentionAt / rankMentions / applyMention + MentionList，输入胶囊顶部、和编辑条同一位置）；网页 lib/mentions.ts + features/chat/MentionList.tsx（↑↓ Enter/Tab Esc）。冒烟 tests/smoke_file_mentions.py；App test/mentions_test.dart。无迁移。
- 消息里的 $技能（v1.81，助手大脑 af）：backend/app/skill_mentions.py（移植自 Codex skills/src/mentions.rs + selection.rs，Apache-2.0 modified）是唯一规则：find 在启用的技能 id 里取最长前缀（中文 id 可以，后面紧跟英文名字字符不算），$ 前是字母/数字/_/$ 不算，代码里的不算，Codex 环境变量名单不算，去重、≤3 个。routes/ws 发消息时存成 skill 引用块（id + 名字），`!命令` 不认，编辑重答按新文字重认（rewind 只保留文件块）；agent/context._render 每轮按当前技能库给 `<skill>` 片段（正文 ≤8000 字，停用 / 删了只给说明）。冒烟 tests/smoke_skill_mentions.py。
- 常驻服务健康 + 手动重启（v1.82，核心 14）：backend/app/services.py 是唯一入口：health（up / restarting / gave_up）、listing（“这台电脑”的 services 一节：在跑的 + 24 小时内意外结束的，端口按进程组归到服务——沙盒端口脚本多给 pgid）、restart（在跑 → 整组杀掉、等 run.sh 写完退出码再排队重起，期间 restart_at 先推后 15 秒防 worker 抢着结算；等重启 → 马上起；放弃了 → 清零重新拉起、卡片改回运行中）。接口 POST /api/jobs/{id}/restart，工具 restart_service（子助手可用，计划模式不放行）。规则（什么算意外、退避、放弃）仍只在 job_restart.py。冒烟 tests/smoke_services.py。
- 定时脚本（v1.84，CORE 15，对标云电脑 cron）：backend/app/script_tasks.py 是唯一规则：ScheduledTask.kind=script 时 prompt 就是命令，worker.run_task 走 launch()（开 task_runs + jobs.start，TaskRun.job_id 记下；上一次还在跑就跳过）；worker.tick 在 jobs.tick 后调 settle_ready() 收尾（成功 = 退出码 0；notify failure/always/change 决定开不开对话 + 收件箱卡，change 比日志指纹 output_digest）；task_runs.recover_stale 不动后台任务还在跑的脚本运行；删项目连带删脚本（task_store.remove_for_project）。工具 schedule_task 加 command / notify。迁移 0042。冒烟 tests/smoke_script_tasks.py。
- `/init` 生成 AGENTS.md（v1.85，大脑 ah，移植 Codex /init 提示词 + 嫁接 Gemini“模型外先查已有”和非代码目录分支）：backend/app/init_command.py 是唯一规则（parse / of / render / record / existing）。存库的仍是“/init”，agent/context._render 只把当前这一问换成提示词、旧的只留一句；routes/ws._answer 发现根目录已有非空 AGENTS.md 就 _say 一句不调模型；steering 不收 /init。写出的 AGENTS.md 由 workspace_instructions 每轮自动读。App models/slash.dart + composer（开头打 / 弹命令候选、/init 提示条），网页 lib/slash.ts + Composer。冒烟 tests/smoke_init_command.py；无迁移。
- 命令环境变量（v1.86，核心回炉 16，对标 Manus 云电脑跑 24/7 机器人要用的 Token）：保险箱新增 kind=env，backend/app/command_env.py 是唯一规则（变量名 / 系统变量 / 值长度、load 解密并刷新进程内打码缓存、ensure 定期重读、scrub 把值换成 [$NAME]（长值先换、窗口边上 ≥6 字的半截也抹）、prompt 只给模型名字）。注入：foreground.run（run_command、`!命令`）→ sandbox /exec/stream 的 env；jobs._launch（新任务、自动 / 手动重启、定时脚本）→ /jobs/start 的 env，每次现取，改值重启生效。打码：foreground 的实时尾巴 / 结果、jobs.log_tail / read_new、loop._call_tool 里每个工具结果（read_file 读到写着值的文件也打码）。sandbox/runner.py check_env 第二道校验，STDIN_B64 最后写。打码挡原样泄露，不对抗故意编码；host_command 不注入。冒烟 tests/smoke_command_env.py；无迁移（kind 列复用）。
- 聊天里要环境变量（v1.88，核心回炉 17，对标 Hark request_secret）：工具 request_env（backend/app/agent/builtin/env.py）弹 purpose=env 表单卡（复用 Tool.form → _ask_form → form.reply 通道），用户填的值直接 command_env.save 存进保险箱（与保险箱接口同一个入口：校验、同名覆盖、上限、刷新打码缓存），模型只拿到“已存好 $NAME”，值不进卡片 / 历史 / 时间线 / 模型；已有同名 = “换个值”；无人值守不弹卡、指去保险箱页；系统提示改为“缺变量就调 request_env，绝不让用户把值发在聊天里”。表单值上限 512 → 8192（超长整个丢弃，不截断成错值）。冒烟 tests/smoke_request_env.py；无迁移。
- 本机斜杠命令（v1.87，大脑 ai，照 Codex tui/slash_command.rs 的 available_during_task / supports_inline_args / 点候选即执行）：/new /compact /plan /copy /status 由客户端执行、不发消息（App features/chat/slash_actions.dart、网页 features/chat/slashActions.ts，规则在 models/slash.dart / lib/slash.ts）；全部复用已有入口（open(null)、POST …/compact、setPlanMode、copyText、本对话用量页）。后端无改动。
- /model /diff（v1.89，大脑 aj，照 Codex /model（生成中不能用、接名字直接换）与 /diff）：/model 不接话 = App 弹模型列表（模型钮同一个 showModelSheet）/ 网页回一句可选；接名字走 ModelCatalog.find / lib/models.ts findModel（大小写不敏感、默认/default、全等优先、开头唯一）→ setModel 同一条 dirty/PATCH 路；/diff 用 latestChanges 找最近一张改动卡 → ChatController.seek / useChat.seek（与搜索定位同一条 focus 路：滚过去 + 闪一下）。后端无改动。
- 任务占用（v1.90，核心 18）：sandbox GET /sandboxes/{id}/groups?pgid=…（GROUPS_PY 容器内读 /proc 两次相隔 0.5 秒，按进程组累加 utime+stime+cutime+cstime 与 smaps_rollup Pss；group_usage 折算成占配额 %）；backend app/job_usage.py 唯一入口（pgid / for_jobs 同工作区合并一次、3 秒缓存 + 并发共用 / text 给模型）；GET /api/jobs/{id}、电脑状态 running_jobs / services 带 usage；job_status 工具结果带“现在占 CPU …”。App/网页任务卡 CPU 条（MeterBar / .meter）+ 内存，任务行与服务行副标题。冒烟 tests/smoke_job_usage.py。
- 回答途中补充（v1.83，大脑 ag，移植 Codex steer）：backend/app/steering.py 是唯一规则：每个对话一个收件箱，routes/ws._answer 登记、runner 拼好历史开跑模型时 start（早了会和刚落库的历史重复）、收尾 close 交还没读到的；只收纯文字（附件 / @文件 / $技能 / !命令 / >4000 字 / 一轮已 5 句 → 照常排队）。ws._steer 不 await 地 offer 后存成 status=steer 的用户消息（created_at = 收下那一刻，早于回复），live_turns.note 往这一轮的事件流推 turn.steered（快照带 steered）。agent/loop.run(inbox=)：每次调模型前把补充作为用户消息接上；本要收尾（没工具调用）时还有没读的就再来一圈（Codex needs_follow_up）。预算到头 / 打转叫停后没读的 → live_turns.follow 另起一轮（_handle_pending 回答已在库里的那句）；用户点停止不接。message.start 带回 client_id。冒烟 tests/smoke_steering.py。
- 预览绝对路径改写（v1.75，核心回炉 10）：app/preview_rewrite.py 是唯一规则（没有通配域名时学 jupyter-server-proxy 的 rewrite_response 思路自己写；E2B/Codespaces 靠每端口子域名、code-server /absproxy 要应用自己配前缀）。routes/preview.forward：wants(method, status, headers) → collect(r, kind, token)：html/css/js 且 ≤REWRITE_MAX 4 MB（gzip/deflate 解开，装 brotli 认 br，解压 ≤16 MB）→ HTML 属性/srcset/meta refresh/style url() 补前缀 + <head>（meta charset 后）注入 SHIM（fetch/XHR/WebSocket/EventSource/open/sendBeacon、script.src 等赋值与 setAttribute 的根路径或同域 URL 补前缀，不碰 history）；CSS url()/@import；JS 模块 import/from/import() 说明符 + url()；已带前缀、//、/\ 不动；读超 / 编码不认 / 字符集解不开 → 原样流式转发。改写后去 Content-Encoding、Content-Type 带 charset、Content-Length 按新正文。PREVIEW_REWRITE=false 关闭。无迁移、无客户端改动。冒烟 tests/smoke_preview_rewrite.py（含 node 里跑补丁脚本）。
- 自动选模型（v1.70）：app/model_router.py 是唯一规则（移植 Gemini CLI routing）。对话 / 定时任务可选“自动”（auto）：每轮开头先过本地规则（寒暄 → 快速；代码块 / 报错堆栈 / 超长 → 深度；“继续 / 好的”沿用上一轮；带图而快速档看不了图 → 深度；后台任务结束的系统轮沿用），拿不准再问一次最便宜的模型（中文 rubric：4 步以上 / 规划设计 / 范围大 / 深度排错 → 复杂），失败或答非所问 → 深度。一轮只定一次，记到 conversations.routed_model（迁移 0038）并推 turn.model；思考强度在自动下按路由到的模型默认档。MODEL_ROUTER=auto|rules|off、ROUTER_SIMPLE/COMPLEX/MODEL/DEFAULT。所有“模型能不能选”的检查走 model_router.choosable。App / 网页模型钮显示“自动 · 快速”，菜单里自动带说明。冒烟 tests/smoke_model_router.py
- 整轮改动卡 + 撤销（v1.68）：app/turn_changes.py 是唯一规则（移植 Codex turn_diff_tracker）。ToolContext.changes（每轮一个 Tracker，并行副本、子助手共用）：write_file / edit_file 写之前 before(root, p)，同一路径只记第一次基线（不存在 = None；>2 MB 或这一轮累计 >16 MB = BIG）。runner._drive 收尾（done 和 stopped 都走）finish → 读磁盘现状，基线 = 现状不出，每个文件 file_edit.change 出净 diff，ChangesBlock 追加在回复末尾；可撤销的基线写进 <工作区>/.turns/<token>/（storage.HIDDEN_DIRS），manifest 记收尾时 sha256，30 天过期清理。POST /api/conversations/{cid}/messages/{mid}/changes/undo：busy 409 / 任一文件 sha 变了 409 conflicts（不动）/ 过期 410；成功恢复（新建的删掉）、卡 undone、quota.forget。历史文字 turn_changes.history_text（撤销后提示“之前读到的已过期”，file_seen 也会拒绝旧版本覆盖）。崩溃恢复的回复没有改动卡。冒烟 tests/smoke_turn_changes.py
- 自动标题（v1.67）：app/conversation_title.py 是唯一规则（移植 Gemini sessionSummaryService）。conversations.title_source：first（第一句话前 40 字，ws 建对话时）→ 第一轮回复（非 stopped）落库后后台 schedule：summary_model 一次小调用（kind title，max_tokens 60，8 s 超时），选材只取用户/助手非空文字，>20 条取前 10 + 后 10，每条截 500 字；清洗去前缀/引号/书名号/句末标点、≤30 字；写回用带 title_source=first 条件的 UPDATE（起名途中用户改名不被覆盖），不改 updated_at；推 conversation.title（在 message.done 之后，续传快照停在终止事件前）。user（PATCH 改名）/ fixed（任务对话、旧数据）/ auto 不再改；前 3 个用户回合内失败下轮重试。AUTO_TITLE=false 关闭。迁移 0037。冒烟 tests/smoke_auto_title.py
- 断线续传（v1.61）：app/live_turns.py 是唯一入口（轮次任务、同对话排队、事件日志、订阅、停止都在这；routes/ws.py 只做传输）。设计移植自 Codex remote_control/websocket.rs（每轮事件带 turn_id + 连续 seq、按游标补发、有界出站队列 OUTBOX_MAX 超限断开慢客户端）+ deepseek-harness assistant-stream.ts（日志只留 LOG_MAX=2000 条，同时折叠块和步骤，游标太旧发 turn.snapshot）。断线 = 退订，不停；没人看着 settings.turn_offline_minutes（默认 30，0 = 旧行为断线即停）后按停止收尾；结束后保留 120 秒供迟到的重连拿 message.done。WS 新帧：turn.resume / turn.resumed / turn.snapshot / ping / pong（docs/protocol.md）。客户端：App chat_socket（退避 1→10 s × 0.5–1 抖动、连上满 60 s 才清零、pong 后 60 s 无回音主动重连）+ chat_controller（续传、去重、旁观、发送探询）；网页 lib/socket.ts + hooks/useChat.ts 同规则。冒烟 tests/smoke_live_turns.py
- @子助手（v1.91，大脑 ak，移植自 Gemini CLI @agent）：消息里写 `@子助手`（或 @agent / @subagent）= 这件事交给子助手。后端 app/agent_mentions.py 唯一规则（认名字、代理优先于 @文件、存 agent 块、当前这一问附 <system_note> 让模型用 delegate、更早只留一句记录、关掉子助手不认、steer 不插队）；App / 网页 @ 候选第一行是“子助手”（没有工作区也列），气泡上方一枚子助手标签。冒烟 tests/smoke_agent_mentions.py（含模型照提示真的派出子助手）。不加迁移。
- 内存去哪了（v1.94，CORE 20）：电脑页“内存”一节按大小排出谁占的内存——后台任务 / 常驻服务（整组 PSS，点了看日志）、不属于任务的程序（对话里直接跑的、nohup 的，沙盒 ps 按内存排的前 8），余下归“其它”；快满时点名最大的那个。唯一规则 app/memory_view.py，沙盒 runner.process_tables 一次 ps 出两份表（按 CPU / 按内存，带 pgid）。冒烟 tests/smoke_memory_view.py（含真 ps 一个 80 MB 进程排第一）。
- 自动选模型的账（v1.95，BRAIN am）：用量页“自动选模型”一节——本月多少轮走简单档 / 复杂档、几轮按规则零调用就定了、分类器花了多少，估算净省（同样 token 换复杂档的价钱 − 实花 − 分类器）；分类器比省下的还贵时提醒改 MODEL_ROUTER=rules。唯一规则 app/router_stats.py（routings 表 + usage.route，迁移 0044，事件形状移植自 Gemini CLI ModelRoutingEvent）。冒烟 tests/smoke_router_stats.py。
- 每个任务占了多少磁盘（v1.96，CORE 21）：后台任务结算时数一次“它运行期间工作区里新写或改过的文件”（按顶层目录分组，给最大 3 组，.home = 装的软件）+ 它自己的日志，存进 jobs.disk（迁移 0045）；运行中按需现数（缓存 30 秒）。任务卡多一行“写入 2.0 MB · 12 个文件 · 最多 images/ · 日志 300 KB”，完整日志页有明细；job_status 告诉模型。mtime 分不清是谁写的，同时段有别的任务就明说“可能含它们写的”。唯一规则 app/job_disk.py，冒烟 tests/smoke_job_disk.py。
- 磁盘谁写得最多（v1.98，CORE 22）：“我的电脑”页磁盘一节下面多一节“最近 7 天谁写得最多”——最近 7 天结束的后台任务按结算时的磁盘账（写的文件 + 日志）排前 5，每行“2 天前 · 主要写在 node_modules/ · 日志 2 MB”+ 占整个工作区的比例条，点开看完整日志和明细；日志清掉后只算写的文件。只读库里存的账，不重新遍历工作区。规则 app/job_disk.leaders，冒烟 tests/smoke_disk_leaders.py（无表结构改动）。
- 继续追问子助手（v1.97，BRAIN an）：子任务结束（含被停、超时）后留下它自己的上下文（迁移 0046 subagent_threads；剪掉没收尾的工具调用、旧工具结果截到 1500 字、整段 ≤6 万字、每段对话最多 20 个），结果里带编号；主助手调 delegate 时 tasks 项写 {continue: 编号, prompt} 就接着它的上下文问（沿用当时的模型，卡片“第 2 轮”）；用户在子任务卡上展开点“追问”，消息带一枚“追问 · 标题”标签，服务器提示主助手去续问。只有派它的那段对话能续。唯一规则 app/agent/subagent_threads.py（移植 Codex resume_agent），冒烟 tests/smoke_subagent_resume.py。
- 途中补充带附件（v1.93，助手大脑 al，学 Codex steer_input）：生成中发图片 / 文件 / @文件 / $技能（可以只发附件）也会并进正在进行的这一轮；模型看到的内容和当前这一问同一套渲染（app/agent/context.render_now：能看图的模型给原图，否则先写成描述），消息存成普通块、下一轮历史照常。仍排队的：!命令、/init、@子助手。冒烟 tests/smoke_steer_attachments.py。
- 任务内存（v1.92，核心 19）：`run_command memory_limit="512m"`（仅后台）给任务单独设上限，worker 每 5 秒采样（app/job_memory.py 唯一规则），超了先写 .jobs/<id>/memcap 再整组杀：普通任务失败并写明原因，常驻服务按崩溃退避重启；普通后台任务 run.sh 调高 oom_score_adj，整台打满时内核先杀它们、保住常驻服务；记内存峰值（结论里给人和模型看）；整台用到 90% / 任务到上限 80% 时 job_status 和任务卡提醒。沙盒 /groups 顺带返回整台内存（box）。迁移 0043，冒烟 tests/smoke_job_memory.py。
- 钟表工具（v1.99，大脑 ao）：get_current_time / convert_time / resolve_relative_date——“明天”“下周三”“10 天后”先换成准确日期和星期（明天、N 天后、下周X、N 个月后这些常见说法工具自己再算一遍，模型数错一天时以说法为准并提醒它），别的时区的钟点按那一天的夏令时换算（跳过的钟点报错、重复的注明），系统提示的“现在”带中文星期。规则 app/clock.py，冒烟 tests/smoke_clock.py（无迁移）。

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
- storage.py     文件系统唯一入口（项目工作区、附件、技能），路径防越界
- skills_store.py 技能读写：用户目录里与内置同 id 的文件 = 自定义版（就地顶替内置，customized=true，reset 删掉即恢复）；新建 id 永远唯一，绝不覆盖或顶替；内置不能删、不能直接 PUT；停用开关存 data/skills/_disabled.json（按 id，损坏当全启用），系统提示只列 enabled_skills()，use_skill 拒绝停用的
- sandbox_client.py 调沙盒服务
- vault.py       保险箱：加解密、按域名匹配（唯一解密点）
- schedule.py    定时任务时刻计算（due_at/is_due/next_run_at，按用户时区）：worker 判断到点与接口的 next_run_at 共用，保证界面写的就是实际会跑的时间
- worker.py      定时任务执行器（独立进程）；每次运行经 task_runs.py 记一行（start/finish）
- task_runs.py   定时任务运行记录（task_runs 表，每任务留最近 KEEP=30 条）+ scheduled_tasks.last_status + 失败提醒：连续失败的第一次放 action 卡（task_id + target=tasks，alerts_sent key=task:任务:运行），之后成功自动收起；worker 启动 recover_stale() 把残留 running 标“中断”；GET /api/tasks/{id}/runs 读
- agent/runner.py 一轮对话的完整流程，聊天和定时任务共用
- agent/approvals.py 审批挂起/答复
- connectors/    OAuth 服务声明（providers.py）、授权与刷新（oauth.py）、MCP 客户端（mcp.py）
- credentials.py 按 URL 解析凭证：OAuth 连接优先，其次保险箱
- browser_client.py 调云浏览器服务
- pages_store.py 可分享网页（/p/<slug>/，带沙盒 CSP）；meta.source 记来源，find_by_source / wire
- system_alerts.py 系统提醒唯一入口（v0.95；v0.97 改按主体）：post(subject, once, …) 去重键 = subject:once（alerts_sent，begin_nested 防并发）、去处走 card_targets、replace 收起同主体旧系统卡（home_cards.alert_subject，迁移 0023）；clear(subject) 恢复后收起并清掉去重键（再坏再提醒）；active(subject) 查还没恢复的事。主体：budget、task:<id>、connector:<provider>、mcp:<服务器 id>。connectors/mcp.py guarded(db, server, call)：Unreachable（连不上/超时/5xx/非 MCP 回应 = down，401/403 = auth）→ 提醒（open connectors，无 prompt）+ 原样抛；服务器回了话（含工具自己报的 McpError）→ 收起；mcp_tools/mcp_call 工具、GET /mcp/{id}/tools（502）都经它。用户：usage.check_budget（usage）、task_runs（task:<id>）、connectors/oauth.expired（connectors：refresh 被拒 / 过期无续期凭证 / api_request 对方 401 → 卡 + ReconnectNeeded 说明给模型；键含密文指纹，同一 token 只一次；complete/forget 收起；网络错误不算失效）。智能体提议的卡（origin=agent）永不被它收起
- home_offers.py 助手提议的 Home 建议卡唯一入口（工具 offer_on_home：kind=action + origin=agent + action_label 按钮字 + action_prompt；同标题原地更新、重新未读、清稍后提醒；同时最多 MAX_LIVE=5 张，多了收起最旧的智能体建议，系统提醒不动；manage_home list 标“你提议的”/“用户已点按钮开始做”）；start() = 点主按钮开对话并链回卡上（routes/home.py POST /api/cards/{id}/start，v0.89，复用 conversation_id 列无迁移）；v0.91 配图 image_url + 原页 link_url（clean_url 只收 http(s)；配图由工具用 display.probe_image 先探测，打不开就照放不带图；原页不合格拒卡）。迁移 0021
- card_targets.py 卡片“去处”唯一入口（v0.93）：resolve(db, open) → (target, task_id)，open = usage/memory/skills/connectors/vault/pages/tasks 或 task:<id>（→ tasks + task_id）/ project:<id>（校验存在，否则 ValueError 中文）；offer_on_home open 参数（只有本人能做的事 open 不给 prompt，卡没有“去做”）；去处是项目时 start() 开的对话放进该项目（项目删了放回主聊天）。客户端两张同样的表（App action_card.dart cardTargets、网页 lib/cardTargets.ts），新去处三处各加一行。迁移 0022（home_cards.target 32→64）
- card_snooze.py Home 卡片“稍后提醒”唯一入口（check/snooze/on_patch 是 /api/cards PATCH 的 on_update 钩子；wake_due 由 worker 每轮叫醒到点的卡：清空 + 重新未读 + 顶到最前；wire 让 snoozed_until 总带时区；manage_home 的 snooze/unsnooze 也走它）
- conversation_share.py 分享对话唯一入口（render 服务端渲染只读快照：Markdown 子集先转义再加标签、无脚本；share/unshare/state；source="conversation:<id>"，同一对话链接不变；load(db,cid) 带消息读对话；智能体工具 share_conversation（agent/builtin/pages.py，scope=conversation：ToolContext.conversation_id 有值才提供，“把这段对话分享给朋友”/“停止分享”）与客户端分享面板同一快照同一链接）
- memory_digest.py “我对你的了解”：全部记忆 → 一段第二人称概括（单行表 memory_digest，id=me）。GET /api/memory-digest 零模型调用，只比指纹（每条记忆 id+updated_at 的哈希）报 stale；POST 才调一次 SUMMARY_MODEL（kind=digest，输入按 INPUT_CHARS 截断、profile 优先）；从不自动生成
- usage.py       用量与花费：llm.py 每次调用后 record() 一行（自己的短会话，失败吞掉）；runner 用 scope(对话id) 归属；report() 出今天/本月（用户时区）+ 本月逐日 daily + 本月最花钱的对话 conversations（_top_conversations：外连接一次查标题，前 TOP_CONVERSATIONS=5，删了的对话 title=null）供 GET /api/usage，conversation_report() 出单个对话累计供 GET /api/conversations/{id}/usage（两者共用 _aggregate 形状）；check_budget() 记账后检查本月花费是否跨过 MONTHLY_BUDGET×BUDGET_ALERTS 的某档 → Home action 卡（target=usage），去重表 alerts_sent（key=budget:年月:档:预算），新档收起旧预算卡

云浏览器服务 browser/
- service.py     唯一运行 Chromium 的服务：快照、点击、输入、截图、人工接管；拦截内网地址

沙盒服务 sandbox/
- runner.py      唯一接触 Docker 的服务
- image/         项目容器镜像（python、node、git）

前端 frontend/src/
- styles/tokens.css  设计令牌，唯一样式来源（v2.1：字重只写 var(--fw-body/title/strong)，主操作用 --ink 不用 --accent，卡片层次用 inset 0 1px 0 var(--glass-highlight) 不用外投影）；深色只认 <html data-theme="dark">，减少透明度只认 <html data-solid>（玻璃 → 实色、--blur 0）
- lib/theme.ts       外观偏好（跟随系统/浅色/深色）；index.html 首帧脚本与它同键 appearance
- lib/look.ts        本机外观偏好（设计 v2）：头像色（--avatar/--on-avatar，4 预设 + 色相环）+ 减少透明度；首帧脚本同键 look.solid
- ui/                共享原语：Page（可带 footer = 底部浮层）、PageHeader（子页面浮动玻璃标题栏）、FloatingFooter（量高度给内容让位）、Section、Sheet、Toggle、Segmented、Hint、Menu、Highlight、图标；
                     ui/glass.css + glass.tsx 是材质零件（.glass 真玻璃只给浮层 / .glass-card 假玻璃卡 / .tile / .pill / .wide-pill / Avatar / ValueTile），与 App ui/glass.dart 一一对应，页面不自己写 backdrop-filter
- shell/             骨架（设计 v2）：页面铺满 + 浮动顶栏 TopBar（左 = 页面通过 <ShellLead> 传进来的上下文按钮，中 = 主页/聊天/项目 分段胶囊，右 = 头像 → /me）；
                     只在 / /chat /projects 显示（isShellRoot），“我的”及子页面、项目对话自带标题栏。LaunchComposer = 主页/项目页底部的输入胶囊（发出 = 新对话，聚焦磨砂 + 收起 + 建议）
- 截图回归：frontend/scripts/shots.py（假接口 + Playwright，浅/深 × 桌面/手机：一级页、聊天（含信息表单 chat-ask）、7 个子页面、2 个弹层、登录页，输出 /tmp/shots/web；用法见文件头）。网页聊天贴底跟随在 features/chat/ChatView.tsx（pinned + ResizeObserver，只有往上翻才取消）。建议卡配图由 shots.py 的 image() 应答一张 SVG。本机缺 Chromium 依赖时：`sudo -n /tmp/pw/bin/playwright install-deps chromium`。卡片里的表单输入框是紧凑版（blocks.css .blk-form-field，与 App compactField 同义）
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
- 新一级栏目：shell/AppShell.tsx 的 TABS 加一项
- 无障碍：没有可见文字的按钮/链接必须 aria-label（Toggle 的 label 是必填参数）；焦点环、减少动态、跳到主要内容都在 styles/base.css 末尾统一处理，组件里不要 outline:none

## 消息协议（WebSocket /ws）
客户端 → `{type:"user.message", conversation_id?, text}`
服务端 → `message.start` → `block.start` / `block.delta` / `block.update` / `tool.status`（交替） → `message.done`(完整块列表) / `error`
客户端 → `user.message`（text、attachments、project_id）/ `approval.reply`（id、approved）

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

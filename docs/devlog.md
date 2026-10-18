# 开发日志（全局决定）

> 本文件此前未提交进仓库（HANDOFF 引用的旧 devlog 留在旧沙盒里），自 v2.90.2 起重新开始记录。每次动手前先在这里写全局决定：放在哪、替换了什么、成本。

## 2026-10-14 v2.90.2 连接器按钮诚实化（HANDOFF §五 2a 中不需要 OAuth 凭据的部分）

**问题**：服务器 `.env` 没配 GOOGLE_/GITHUB_CLIENT_ID/SECRET 时，连接器页仍把 Google、GitHub 两行列出来（变淡、副标题“见 .env.example”）。用户看到的是“有这个功能但连不上”。

**决定**
1. **单一数据源 = 后端 `GET /api/connectors` 的 `status`**（判定只在 `app/connector_accounts.py`）。不新增接口。每项多一个 `setup`：服务器没配这个 OAuth 应用时给 `{console, callback, env}`（去哪注册、回调地址、要填的 .env 变量名），配好了为 `null`。回调地址只来自 `oauth.redirect_uri()`（即 `PUBLIC_URL`），客户端不再自己拼；变量名只来自 `Provider.env_names`；注册地址是 `providers.py` 里的数据 `console_url`。
2. **客户端只显示能用的**：`status == unconfigured` 的行整行不画（删掉原来的“变淡 + 见 .env.example”分支与 `Dimmed` 行）。已连接 / 授权失效的照常显示；若服务器后来删了配置（`setup != null`），这些行不再给“重新连接 / 重新授权”按钮，避免点了 400。
3. **缺配置时只给部署者一行**：账户区末尾一行“服务器还差一步：配置 Google / GitHub 授权”（列出缺的那些），点开是弹层引导：三步（去开发者后台创建应用、回调地址可复制、填 .env 后重启），完整步骤指向 `docs/oauth-setup.md`。一个都没配、也没连过时，账户区只剩这一行。
   - Toyuis 是单用户系统（`auth.py`：只有一个主人），能登录的就是部署者本人，所以“普通用户不显示、管理员显示一行”在现架构下等价于“登录者看到这一行”；分享出去的只读对话里没有连接器页，聊天连接卡对 unconfigured 本来就无按钮、助手也不会发（`refuse_connect`）。将来多用户时，只需在这一行外加角色判断。
4. **客户端删掉 `configured` 字段的使用**（App `Connector.configured`、Web `Connector.configured` 及其兜底推断），只认 `status` + `setup`。后端仍发 `configured`，仅为手机上还没更新的旧 APK 保留，协议里注明“新客户端不读”。
5. 文档：新增 `docs/oauth-setup.md`（GitHub OAuth App、Google OAuth 客户端测试模式 + 测试用户 + 用到的 scope、回调、.env、重启命令）；`docs/protocol.md` 记 `setup`；`.env.example` 注释指向该文档。

**替换/删除**：连接器页“未配置”变淡行（App `_AccountRow` 的 Dimmed 分支、Web `row-off` 分支）、两端 sortAccounts 的“未配置”第三档、两端 `configured` 兜底推断。
**成本**：无新接口、无迁移、无模型调用；列表每项多几十字节。

## 2026-10-15 连发分组准确率：把评测搬进仓库，重建标注集（HANDOFF §五 3）

**问题**：HANDOFF §五 3 要“按 §C 定稿规则重新标注 57 组、重跑 `eval_intake.py`、报告真实准确率”。但 `work/e2e-harness/intake_cases.jsonl`、`eval_intake.py`、`docs/home-redesign.md`（§C 定义所在）
**从来没提交进 git**（本文件第 3 行的说明也印证了：旧文档留在旧沙盒）。所以那两个数字（原来说的 70%）既不可复现，也没法在原地重标。旧证据只剩：`backend/app/message_intake.py` 的模块注释、`docs/protocol.md` 里 `turn.steered` 那行、CHANGELOG v2.90。

**决定**
1. **评测进仓库、进版本库，作为唯一真源**：`backend/tests/intake_cases.jsonl`（标注集，每组带 `why` 说明为什么这么标，便于复核）+ `backend/tests/smoke_intake_eval.py`（评测器）。以后改 `message_intake.py` 的规则必须先跑它；不再有“沙盒里有套脚本”这种事。
2. **两层分开量，数字要能复现**：
   - 规则层（免费、确定性）：逐条比对 `rule()`/`reply_to` 的判定与标注，得出**命中 / 误判 / 交给判官**三个数；只有“误判”算 bug（规则答了个确定的错），交给判官是设计内的成本。
   - 判官层（真模型、走 lite）：`EVAL_JUDGE=1` 时才跑，只对规则交给它的那几条调 `message_intake.judge()`，量“拿不准的时候便宜模型答对没有”。本地没配网关就在 VPS 的容器里跑。
3. **只修真实误判**：宁少勿多的取向（拿不准就合并）保留，规则里“问题形状的信誓旦旦”才是要修的（例：`^要`/`^用` 把“要多少钱”“用哪个好”当成补充）。
4. 不改协议、不加接口、不迁移。

**替换/删除**：替换掉旧沙盒里的 `work/e2e-harness/` 评测（已丢失，无法保留）；HANDOFF §五 3 的做法改成“先跑仓库里的标注集”。
**成本**：零模型调用（规则层）；判官层一次全跑 ≈ 57 组里的少数几条 × 约 200 token，走最便宜的 lite。

## 2026-10-15 v2.91 §N 项目页（≡↔+、对话状态胶囊、总结标题药丸）

> `docs/home-redesign.md` 已丢失，规格以 HANDOFF §五 第 4 条为准。下面是落地时的全局决定。

**归属与含义（先定清楚“项目列表”“药丸”指什么）**
- “项目列表带状态胶囊” = **项目里的对话列表**（HANDOFF §八 原话“对话条目带状态”）：项目抽屉 / 双栏历史栏 + 项目首屏“最近的对话”。主聊天的历史列表不带（主聊天不发 status，也不画）；项目网格（项目本身）不做汇总状态——需要时再议。
- “项目名药丸” = 项目对话页里浮在标题栏下方的那颗药丸，显示**这段对话的总结标题**。标题栏本来就写项目名（“📚 考研复习”），以前项目对话里根本看不到对话标题；药丸补上这一层，不和标题栏重复。主聊天不加药丸（顶栏下已有一行标题）。
- 左上 “≡ ↔ +”：手机（单栏）项目对话的标题栏左侧，返回键右边。≡ = 打开项目对话列表；列表打开时同一颗钮旋转成 + = 在本项目新开一段（拇指不用挪位）。列表从**标题栏下面**滑出（App：SubPage 里再套一层 Scaffold，抽屉只盖正文；Web：项目抽屉让出标题栏、标题栏升到遮罩之上），所以按钮全程可见、可点。平板双栏 / 电脑宽屏历史栏常驻，不出现这颗钮（双栏收起/展开钮保持原样）。

**单一来源**
1. 状态规则只在 `backend/app/conversation_status.py`：`GET /api/conversations?project_id=` 每项多 `status: running | waiting | done | null`（不带 project_id 的主列表、搜索结果不算，省一次查询）。判定顺序：
   - 本进程正有一轮在跑（`live_turns` 主路或并行路）：这一轮的块里有挂起的审批 / 表单 / 下单确认 / 方案批准 / 浏览器“需要你来” → `waiting`，否则 `running`；
   - 有本对话的后台任务在跑（非常驻 keep_alive；常驻服务会让对话永远“进行中”）或任务结束、助手还要接着说（followup=pending）→ `running`；
   - 否则看最后一条消息：助手回复且 status ∈ {done, wrapped}：最后一段文字以“？/?”收尾 = 在问你 → `waiting`；否则 `done`；
   - 其余（没有消息、最后一条是没等到回复的用户消息、回复被停止 / 打断 / 原地打转）→ `null`，不画胶囊（三种状态之外不发明第四种）。
   - 为什么“以问号收尾”算等你回复：轮次结束时挂起的卡片一律变 expired（agent/loop.py），静止时唯一能表达“在等用户”的就是回复本身在提问；判定只看最后一段，零模型成本。代价：客套式结尾问句也会算等你回复——提示词 v2.88 已要求书面、不口语，实际很少。
   - 客户端刷新：已有的 message.done / stopped / conversation.title 后刷新列表之外，加 message.start 后刷新一次（服务器此时已能看到在跑）和打开项目抽屉时刷新一次（挂起卡片出现在轮次中途）。客户端不自己推断状态。
2. 标题规则只在 `backend/app/conversation_title.py`（llm.py 是唯一模型调用路径，模型仍是 `settings.summary_model` = fast 别名，不新增第二条起标题路径）：
   - 提示词改成**名词短语、≤14 字（英文 ≤40 字母）、无标点、不口语**（例：“App 深色模式适配”）；`clean()` 去掉全部标点、口语开头（帮我 / 请 / 我想…），中文按 14 字截、英文按词截。
   - **重新总结**：新列 `conversations.title_at`（迁移 0065）= 上次起标题时这段对话有几条消息。`title_source=auto` 的对话每多约 RETITLE_EVERY=10 条消息，叫一次小模型：给它当前标题 + 最近 10 条，“话题没变就原样输出当前标题，变了给新标题”。没变只推进 title_at（不推事件、不再每轮问）；变了写回并推 `conversation.title`。user / fixed 永不碰。迁移把已有 auto 对话的 title_at 回填为当前消息数（老对话不会一升级就被改名）。
   - `first_title` 只作模型起名前的占位（不改）。列表、项目首屏、药丸都读同一个 `title`。
   - 成本：每段对话约每 10 条消息多一次 ~300 token 的 fast 调用（失败静默保持原标题）。

**动效（只动 transform / opacity，减弱动效时直接到位）**
- ≡↔+：三条 2px 线，上下两条平移到中线并分别旋转 ±90° 合成竖线，中线不动 → 十字；Motion.morph 280ms（Web `--dur-morph`），曲线 ease。App `ui/motion.dart` 的 `MenuPlusIcon`；Web `.morph-icon` 过渡。
- 药丸：出现 = 从上方 8px 落下 + 淡入，曲线用已有的 Motion.spring / `--spring`（过冲约 2–3%，≤4%）；收起 = 反向、无回弹。触发：进入一段已有对话；往上翻看历史累计 >24px；标题被重新总结（旧标题非空且变了）。收起：往下滑、停 1.5 秒、回到底部。新建对话发第一句时不弹（你刚写的，不需要提醒），占位标题出现也不弹。
  - App：`ValueNotifier<bool>` + 监听已有的 ScrollController，药丸包 `RepaintBoundary`，滚动不触发 ChatView setState；Web：passive scroll + rAF 合帧，只在显隐翻转时 setState。
- 状态胶囊：进行中 = 左侧小点做透明度呼吸（已有 PulseDot / `pulse` keyframes）；等你回复 = 墨色实心（唯一要你动手的信号）；已完成 = 安静的 tile 底、三级字。状态切换时淡入换字。

**替换 / 删除**
- App 项目对话标题栏右侧的“历史”按钮（notes 图标，`ChatScaffold.historyTooltip` 参数一起删）→ 左侧 ≡↔+；项目抽屉从 endDrawer（右侧、盖住标题栏）改为标题栏下的左抽屉。
- Web 项目标题栏里的 mobile-only 历史按钮（IconHistory）→ ≡↔+。
- 手机项目抽屉里的“新对话”按钮（App 抽屉头的 edit 图标、Web `.new-chat` 行）和 Web 抽屉头的关闭钮：+ 和遮罩已承担，删掉。常驻侧栏 / 主聊天抽屉保留。
- 起标题“只在前 3 回合试”的一次性规则并入“首次 + 每约 10 条复查”的同一个 maybe()。
**成本**：无新接口；列表多一个字段 + 项目列表多一次“每段对话最后一条消息”的查询（≤100 行）；一列迁移；标题每 10 条一次小调用。

## 2026-10-15 v2.92 §P 名字与头像（称呼、助手名、头像、首次问候）
**全局决定（先写后做）**
1. **存哪**：只有一个主人，没有 users 表（登录用户名来自 .env 的 OWNER_USERNAME）。HANDOFF 写的 `users.display_name / users.avatar` 改为 `app_settings` 一行 key=`identity`（和 reply_language 同一模式，**不用迁移**），头像文件一份 `DATA/identity/avatar`。为三个字段建单行表只会多一个数据源。唯一规则入口 `backend/app/identity.py`。
2. **接口替换**：新 `GET/PATCH /api/profile`、`POST/DELETE /api/profile/avatar`、`GET /api/profile/avatar/<版本>`（?token=，地址随版本变，长缓存）、`POST /api/profile/greet`；**删掉 `GET /api/auth/me`**（及 smoke_auth_me、App `accountNameProvider`）——页头名字、顶栏头像都只读 profile 一处。头像按文件头认类型（App multipart 一律报 octet-stream），≤2 MB，客户端先缩到 512px。
3. **首次问候在聊天里问（不做表单引导页）**：客户端在主聊天空白且 `greet=true` 时调一次 `POST /api/profile/greet`，服务器建「初次见面」对话、落一条固定的助手开场（定稿文案，零模型成本），客户端打开它。用户回答后，**只在这段对话里**系统提示易变段附一句“用户回答了就调 set_names”，直到存过名字或对话超过 6 条（零 token 外溢）。用户在设置里先填过名字就不再问候。
4. **助手名进系统提示**：`settings.system_prompt` 去掉写死的“你是 Toyuis”，第一句由 `identity.persona` 生成（助手名 + 用户称呼），仍在稳定段最前——只在改名那一轮打掉一次提示缓存。新按需工具 `set_names`（和 set_reply_language 同处 agent/builtin/preferences.py），系统提示里“设置不是记忆”那句顺带提到它，用户以后说“叫我…/你就叫…”也走设置。
5. **界面**：头像 = 已有 Avatar 组件（App 本来就画首字母；网页把人形图标换成首字母），有上传的头像就盖一张图、到了才淡入（只动 opacity）。“我”页页头：头像 + 名字整块是一颗键 → 个人资料弹层（App `features/me/profile_sheet.dart`，网页 `ProfileSheet.tsx`）：大头像（相册/拍照/移除）+ 称呼 + 助手名 + 保存，只送改了的字段。头像颜色仍在偏好设置（它是没有图时的底色）。
**替换 / 删除**：GET /api/auth/me、smoke_auth_me.py、App accountNameProvider、网页 Identity 里自己请求 /api/auth/me 的代码、网页 Avatar 的人形图标、config 里写死的“你是 Toyuis”。
**成本**：无迁移；问候零模型调用；引导句只在问候对话的前 6 条里出现（约 120 字）；改名后一轮提示缓存失效一次。

## 2026-10-15 v2.93 §Q 项目页按 Hark 重做（两端）+ 手机弹层不再被挡
用户认可的规格：项目页全程留在一级外壳（顶栏“主页 / 聊天 / 项目”+ 头像不消失）；左上 + ↔ ≡ 一颗钮；项目列表是大字项目名 + 项目汇总状态胶囊、不活跃的变灰、不放输入框；项目内只看对话列表，文件 / 电脑 / 规则与档案收进 ⋯。另修手机网页弹层三处被挡。
**全局决定（先写后做）**
1. **项目在一级外壳下**：`/projects` 与 `/projects/:id` 都显示浮动顶栏；项目里的“规则与档案”“电脑”仍是子页面（自带标题栏，顶栏让位）——它们是项目的设置 / 工具页，不是导航层级。判定只有一条：`/projects/<id>` 这一层（App `shellBarShown()` 在 `shell/app_shell.dart`，Web `isShellRoot()` 在 `shell/TopBar.tsx`，同一条正则）。项目对话从 SubPage 改成和主聊天一样的 ShellPage + lead + header 行（ChatScaffold 只剩一种外框）。
2. **左上是同一颗钮**：项目列表 = +（新建项目）；进项目 = ≡（本项目对话列表）；列表开着 ≡ 再转成 +（本项目新对话，v2.91 行为保留）。
   - App：列表页和项目页的钮挂同一个 Hero tag（`projectLeadHero`），切页时钮不随页面滑动，飞行途中按**项目页路由动画**画 `MenuPlusGlyph(t)`（push：+→≡，pop / 预测式返回：≡→+，跟手）。图标拆成“按进度画”的 `MenuPlusGlyph` + 自己补间的 `MenuPlusIcon` 两层，morph 仍只动 transform。减弱动效：路由动画照常但图标按 0.5 取整直接到位。
   - Web：页面各自把钮传进顶栏左槽（ShellLead，不变），钮从“上一颗钮的形状”挂上、下一帧转到自己的形状，CSS 过渡完成 morph（形状记在 `features/chat/MenuPlus.tsx` 模块里一份）。减弱动效由 base.css 把过渡压到 1ms。
   - 双栏 / 宽屏：项目历史栏常驻，App 左上 = 收起 / 展开（同主聊天），Web 宽屏左上不放钮（同主聊天）。
3. **怎么回到项目列表**：顶栏下那一行（header 行）= 左 ‹（“返回项目列表”）+ 中间项目名（点开本对话用量，同主聊天标题）+ 右 ⋯（项目菜单），左右各一颗，标题居中。另外再点一次顶栏“项目”也回列表（已有：点当前 Tab = 回根）。不把返回塞进左上钮：它已经承担 ≡ / + 两件事，再加一件就猜不到了。对话标题仍由 v2.91 的药丸负责（header 行写项目名，不重复）。
4. **项目对话抽屉在 header 行下面滑出**：App 抽屉放进 ShellPage 里层的 Scaffold，左上钮和 header 行画在它上面，顶栏不再因项目抽屉淡出（不碰 ShellCover）；Web 抽屉 top 让出顶栏 + header 行、遮罩同样从那里开始。主聊天抽屉仍盖全屏、顶栏让位（不变）。
5. **项目汇总状态**（唯一规则 `backend/app/conversation_status.py`）：新纯函数 `summarize(按最近更新排序的状态)`——任一 waiting → waiting；否则任一 running → running；否则最近那段（排第一）done → done；否则 null（不画）。`for_projects(db, ids)` 取每个项目里与项目对话列表同口径的可见对话（`run_conversations.listed()`，每项目最近 100 段），复用 `for_list` 判定，不另起一套。`GET /api/projects`（列表与单个）每项加 `status`；不改表、无迁移。
6. **项目列表**：一行一个大字项目名（displaySmall 级别，前面小 emoji），行尾状态胶囊 + ⋯，长按 = 同一份菜单；不用卡片 / GlassCard 网格，不放输入框（删 LaunchComposer）；顶上只留一行小标签“N 个项目 · 最近 …”（顶栏“项目”已是页名，不再画大标题“项目”）。**灰化规则 `projectIsCurrent(index, project)`**：按最近活动排第一的项目、以及状态是“进行中 / 等你回复”的项目用正文色；其余（包括“已完成”的）项目名用三级色。理由：Hark 的列表是“现在在忙什么”一眼可见，做完的和很久没动的退到背景；只看“第一个”会把另一个正在跑的项目也压灰，所以 running / waiting 一律算当前。App `features/projects/projects_screen.dart`、Web `projectHomeRules.ts`，同一规则、各有测试 / 守门。
7. **项目内 = 对话列表**：项目首屏（ProjectHome，即“本项目新对话”的空白态）只列本项目全部对话（置顶在前，再按更新时间），行尾状态胶囊（没有状态写相对时间），点开续聊；底下输入框 = 在本项目开新对话。双栏时对话列表已常驻左侧，首屏只留一行提示，不重复列。文件、电脑、规则与档案、编辑、删除都在 ⋯（新增“电脑”一项）。
8. **弹层不被挡**：
   - Web `Sheet` 改为 portal 到 `document.body`：以前它渲染在页面树里，页面的 mask（顶部渐隐）和入场 transform 各自形成层叠上下文，z-index 50 也压不过外壳顶栏（20）和底部输入胶囊（16）——这就是“弹层压在顶栏下面”“输入框浮在弹层上”的根因。层级统一：输入胶囊 16 < 顶栏 20 < 抽屉 30 < 弹层 50 < 对话框 60。
   - 遮罩按 `visualViewport` 定位（`--vv-top` / `--vv-h` 写在遮罩上，没有 visualViewport 时 = 100dvh），键盘、手机浏览器工具栏出现时弹层底边跟着可见区域走；`.sheet-actions` 在弹层里 `position: sticky; bottom: 0`，底部留 `env(safe-area-inset-bottom)`，内容再长取消 / 创建也始终看得见。
   - App：弹层本来就开在根导航器（v2.78，已在顶栏和输入胶囊之上）。查出同类问题两处：`isScrollControlled` 的弹层没开 `useSafeArea`，长表单会顶进状态栏 / 顶栏位置；表单弹层的提交钮在滚动区里，键盘弹起时会被挤到看不见。改为 `useSafeArea: true`，表单把字段放进可滚区、提交钮钉在下面。
**实现中发现、按实际改的地方**
- **App 原来没有页面转场**：go_router 18 在本 App 的导航器上下文里判不出 MaterialApp，所有 `builder:` 路由都退回 `NoTransitionPage`（实测路由类型 `_CustomTransitionPageRoute`、时长 0）——子页面进出一直是瞬切，Hero 也就飞不起来。本轮不动全局手感（那是另一个决定，写进 HANDOFF 待定），只给 `/projects/:id` 一个 `CustomTransitionPage`：新页淡入 + 从下方 8px 浮上（`pageRiseTransition`，Motion.morph 280ms，同 ≡/+ 的曲线），项目列表用 `FadeUnderCover` 按 secondaryAnimation 淡出（两页都是透明底，不交叉淡化会叠字），左上钮的 Hero 飞行就骑在这条动画上。减弱动效：转场和 morph 都直接到位。
- 测试收尾时 `ChatView.dispose → SpeechController.stop` 会碰已释放的 Notifier（项目页现在常驻在一级分支里更容易触发），`stop()` 先看 `ref.mounted`。
**替换 / 删除**
- App：项目列表的卡片网格（`_Grid` / `_ProjectTile`）与 LaunchComposer、大标题“项目”；ProjectHome 的字标头、规则行、文件节、电脑节、起步建议，以及 `projectRecentFiles` / `projectFilesMax` / `projectRecentMax`（首屏不再截 3 条）；ChatScaffold 的 SubPage 分支（项目对话不再是子页面）与 `ProjectDetailScreen.suggestions`；`MenuPlusIcon` 内部画线逻辑并入 `MenuPlusGlyph`。
- Web：`project-grid` / `project-card` 卡片样式与 LaunchComposer；ProjectHome 的文件 / 电脑 / 建议节和 `projectRecentFiles` / `PROJECT_*_MAX`；ChatScreen 的 `with-bar` 玻璃标题栏分支（`leading` / `trailing` 合并为 header 行的 `back` / `trailing`）及 `.chat-bar` 样式；`Sheet` 不再在页面树内渲染。
**成本**：`GET /api/projects` 多三次查询（各项目可见对话 + for_list 的两次），单用户 ≤ 几百行；无迁移、无模型调用；客户端无新请求（项目页不再拉文件列表和电脑状态，反而少两个）。

## 2026-10-15 v2.94 主页三个 bug（HANDOFF 第五节 6a）
本轮不碰 VPS（不查线上库、不部署），不出 APK；项目“一段对话”的改向（HANDOFF 5b）留给 v2.95，不和本轮混。
**先查根因（查到的事实）**
1. **天气报告重复 3 次 —— 是数据重复，不是渲染重复。** 两端面板都只是 `BlockList(card.blocks)` / `<BlockRenderer blocks={p.blocks}>` 原样画，没有重复渲染。重复写进了库，有两条源头：
   - **面板内容 = 整轮回复的全部块**（`worker._deliver_panel` 收 `reply.blocks`）。agent 循环每次调工具前会 `break_text()`，所以一轮里每一步说过的话都是一个独立文字块。面板刷新提示（PANEL_STYLE）要求“数字用 show_stats”，模型的常见走法是：先写一遍天气 → 调 show_stats → 再写一遍；若“用完工具一句没说/说了要做没做”被 next_speaker 补一句“继续”，还会再写一遍——同一份天气报告进面板 2～3 次，每次刷新都重来。聊天里中间步骤的话是过程，面板里它就是重复。
   - **create_panel 没有查重**（`task_store.twin` 注释明写“面板不在这查”）：模型没先 `manage_home list`、或一轮里重试，就会再建一个同名/同指令的面板，主页上出现几张一样的天气面板。
   - “内置天气卡”：Toyuis **没有**内置天气卡（Hark 有，我们从没做过），主页上的天气只有面板这一条路径；早间简报是收件箱报告（prep-my-day 技能里“有天气就加一行”），不是第二套天气功能。所以没有“两套只留一套”可删——不新增内置天气卡（那才是叠加）。
2. **Composer 遮住最后一张面板**：两端现有机制本身是对的——App `FloatingFooter` 量胶囊实际高度写进 `MediaQuery.padding.bottom`，`PageBody` 加到列表底部留白；Web `Page footer` 用 ResizeObserver 量出 `--footer-h`，`.page.has-composer .page-inner` 底部留 `--footer-h + sp-5`（胶囊高度已含 `env(safe-area-inset-bottom)`）。本机按 1080×2340（手机）和 2560×1440（电脑）实际渲染 App 主页并滚到底，最后一颗“创建一个新面板”在胶囊上方完整露出。这条 bug 是 v2.78 主页重做前（旧的分节主页）报的。**本轮不重写机制**，只做两件：①把几何关系钉成测试（手机、电脑两种宽度滚到底，最后一张卡底边 ≤ 胶囊顶边），以后谁改坏会红；②删掉 Web CSS 里 `var(--footer-h, 88px)` 的写死兜底（`--footer-h` 由量高的组件必给，88px 是魔法数，兜底只会掩盖“忘了量”）。
3. **电脑端主页割裂 / 左半屏空**：根因是 v2.78 以前的 Web 宽屏两栏（`.home-grid` 主列 + 360px 右栏，主列卡少时左边一大块空），v2.78 已改成居中单列，但留下了**宽版页面这条残路**：`Page wide` / `.page-inner.wide` / `--content-wide: 1080px`，v2.93 删掉项目卡片网格后只剩项目列表在用——而 `.project-list` 只有 `max-width: 720px` 没居中，≥1100px 时列表贴在 1080 宽区域的左边，右边空一块，正是同一种“割裂”。App 宽屏实际渲染是居中 720 单列，没问题；但 App 建议卡配图在电脑宽度仍是 2:1（Web ≥720px 已压到 5:2），一张图占大半屏。
**全局决定**
- 面板只收“结果”：新规则 `panel_blocks(blocks)` 放在投递处（`worker.py`，面板投递唯一入口）：展示卡（show_stats / 表格 / 图…）保留、完全相同的只留最后一张；文字只留**最后一个**文字块（最后一步的成稿）。不改 agent 循环（聊天里过程话仍要显示），不改提示词去“求”模型别重复（规则比提示词可靠）。报告卡不动：报告保留对话、点开可追问，过程本来就该在。
- 面板查重并进 `task_store` 的同一处“同一件事”规则：`panel_twin(title, prompt)`——还在主页上（卡没被移除、任务启用）的面板里，标题（去空白/标点、不分大小写）相同或指令相同即算同一个；create_panel 遇到就不建，回告诉模型“已有面板 X（id），要改用 manage_home update”。`twin` 注释里“面板不在这查”一并改掉。只拦智能体工具，用户界面不走这条路。
- 宽版页面整条删：`Page` 的 `wide` 参数、`.page-inner.wide`、`--content-wide`；项目列表跟所有页一样居中 720。App 配图加 `Layout.offerImageRatioWide = 2.5`，宽度 ≥ `Layout.contentMax` 时用（= Web 的 720 断点）。
**替换 / 删除**：`twin` 里“面板不查重”的例外；面板投递里“整轮回复原样进卡”；Web `Page wide` / `.page-inner.wide` / `--content-wide`；Web 三处 `var(--footer-h, 88px)` 兜底魔法数。不新增内置天气卡。
**成本**：无迁移、无新接口、无模型调用；查重多一次查面板任务（单用户十几行）。
**没做 / 待验**：线上库里已经重复的面板与重复内容本轮没清（规定不碰 VPS）——下次部署后在服务器上 `manage_home list` 看一眼，重复面板手动移除一个即可，旧内容下次刷新就按新规则重写。

## 2026-10-15 v2.95 项目 = 一段对话（HANDOFF 5b）
用户 12:48 原话：“项目点进去之后为什么还可以开多个会话，一个项目不应该就一个对话吗，hark 就是这样的呀”。Hark 截图：项目页顶栏照旧“主页 / 聊天 / 项目”+ 头像，左上 ≡，顶栏下一枚药丸写项目名，下面直接是聊天和输入框。v2.93 的“项目内对话列表 / 抽屉 / 本项目新对话”方向错了，本版整条替换。不碰 VPS、不出 APK。
**全局决定（先写后做；用户可事后改）**
1. **项目 = 唯一一段普通对话**。唯一规则入口新模块 `backend/app/project_chat.py`：`of(db, pid)` 取、`ensure(db, project)` 取不到就建（标题 = 项目名，`title_source=fixed`——不再自动起标题，项目里药丸写项目名，总结标题没人看，省掉每 10 条一次的小调用）、`rename` 项目改名时跟着改。数据库约束：部分唯一索引 `uq_conversations_project_chat`（`project_id` 非空且 `task_id` 为空时 `project_id` 唯一，SQLite / Postgres 都支持）。
   - **运行对话不算**（v2.75）：定时脚本在项目工作区跑开的对话带 `task_id`，不受约束、不进项目页，从 Home 报告卡 / 运行记录打开。查清了挂项目的只有定时脚本（`script_tasks`；agent 任务和面板 `project_id` 恒为空）。**唯一要改的点**：用户在这种对话里回话时 `run_conversations.promote()` 会清 `task_id`，在项目里会撞约束——项目里的运行对话不再 promote（仍是运行对话，照样能聊、能从报告卡打开）；`drop()` 清理时跳过“用户回过话的”（>1 条用户消息），免得被裁掉。
   - 所有“在项目里开对话”的入口改走 `ensure`：建项目（`POST /api/projects`，crud 加 `after_create` 钩子；agent 的 projects create）、ws 新消息带 `project_id`、主页建议卡“去做”指向项目、跨项目转交（`target_conversation` 删掉，`new_conversation` 恒 false 但字段保留不破协议）。
   - 删项目照旧连带删对话；`DELETE /api/conversations/{项目对话}` 回 409（“项目对话随项目删除”），客户端也不再给项目对话“删除”入口。
2. **点项目直接进这段聊天**：App `/projects/:id`、Web `/projects/:pid` 就是聊天；客户端只认一条数据路——`GET /api/conversations?project_id=` 语义改为“这个项目的那段对话”（≤1 项，带 `status`；没有就当场建，幂等），项目范围的聊天控制器拿到就自动打开，不再有“没打开对话”的项目首屏。`?q=&project_id=`（项目内搜索）删掉——一段对话不需要“找对话”。
3. **药丸 / 标题的唯一来源**：顶栏下那一行（ChatScaffold header / Web `chat-caption`）是唯一的标题位。主聊天：写对话总结标题（不变）。项目：写**项目名药丸**（`emoji 名字 ▾`，玻璃胶囊，进页时 DropIn 一次），点它 = 项目菜单（文件 / 电脑 / 规则与档案 / 编辑 / 删除，同列表行 ⋯ 的 `showProjectMenu`）——⋯ 菜单保留、并到药丸上，不再另放 ‹ 和 ⋯。v2.91 的“滚动浮出对话标题”药丸（App `title_pill.dart` TitlePill、Web `TitlePill.tsx`）整件删掉：它写的是“这段对话在谈什么”，项目只有一段对话后就是项目名，常驻即可，没必要再按滚动显隐。
4. **左上钮**：项目列表 = +（新建项目）；进项目 = ≡，打开**项目切换抽屉**（所有项目，按最近活动，行尾项目状态胶囊，当前项目高亮），抽屉开着时钮转成 + = 新建项目。与主聊天“≡ 历史 / 新对话在里面”同构：抽屉 = 同层级的“切换”，+ = 新建同类。仍复用 MenuPlus（App `MenuPlusHero` 骑在项目页路由动画上，Web `MenuPlus`），抽屉仍从 header 行下面滑出（左上钮不被盖住才能 morph）。宽屏 / 双栏：切换栏常驻左侧，左上 = 收起 / 展开（同主聊天）。回项目列表：再点顶栏“项目”（已有：点当前 Tab = 回根）。
5. **项目状态 = 这段对话的状态**：`conversation_status.summarize / for_projects / PROJECT_SCOPE` 删掉（只为多对话汇总服务），`GET /api/projects` 的 `status` 直接是 `for_list([那段对话])`；`conversation_count` 换成 `conversation_id`（客户端点项目不必再查）。
6. **数据迁移 0066（可回退、幂等）**：同一项目多段普通对话 → 一段：保留**最早创建**那段的 id，其余对话的消息按原 `created_at` 原样挪进去（时间线自然交织）；其余引用这些对话 id 的行（`turn_journals / task_runs / feedback / home_cards / usage / routings / subagent_threads / video_transcripts / jobs`）一并改指保留那段，免得报告卡、反馈、账单点开 404。保留那段：标题改项目名、`title_source=fixed`、`title_at` 清空、滚动摘要 `summary / summary_upto` 清空（下一轮按新历史重生成）、`updated_at` 取各段最大、`pinned/model/reasoning` 用最近一段的。被合并的对话行删除。
   - **备份**：`project_chat_merge_convs`（每段被合并 / 被改的对话一行：原 id、项目、保留 id、角色 kept|merged、全部元数据 JSON）+ `project_chat_merge_refs`（表名、行 id、原对话 id：每条被改指的消息和引用行）。**downgrade**：按备份重建被合并的对话、把行改回原对话、恢复保留那段的元数据，删唯一索引和两张备份表。
   - **幂等**：只处理“还有 >1 段普通对话”的项目，备份按主键 `INSERT` 前先查；重复跑无变化（smoke 直接再调一次合并函数验证）。没有任何对话的项目不在迁移里建（打开或发消息时 `ensure`）。
   - 部署时 alembic 自动执行；回退 = `alembic downgrade 0065` 再部署 v2.94。
**替换 / 删除清单**
- 后端：`conversation_status.summarize / for_projects / PROJECT_SCOPE`；`project_relay.target_conversation` 与“对方没有就新开”分支；home_offers 里给项目 new 一段对话；ws 里给项目 new 一段对话（并入 ensure）；`GET /api/conversations` 的项目多对话列表 / 项目内搜索；`GET /api/projects` 的 `conversation_count`（projects 工具清单里的“N 个对话”一并去掉）。
- App：`project_home.dart`（ProjectHome / projectConversations）整件；ChatScaffold 的项目对话抽屉（HistoryPanel 项目模式）、“+ = 本项目新对话”、header 行 ‹ / ⋯；`HistoryPanel` 的 `projectId` 参数（只剩主聊天）；`title_pill.dart` 与其测试；项目里的对话搜索；ChatController 项目范围“新对话”。新增 `features/projects/project_switcher.dart`（抽屉 / 常驻栏共用）、项目药丸（在 project_switcher.dart 旁，`ProjectPill`）。
- Web：`ProjectHome.tsx`；ChatScreen 的 `empty / back / listTitle` 项目分支、项目对话抽屉 + 遮罩复用为项目切换抽屉（`ProjectSwitcher.tsx`）；`TitlePill.tsx` 与 chat.css 的 `.title-pill*`；`useConversations` 的项目搜索。
- 测试：删 TitlePill / ProjectHome / 项目对话抽屉相关旧测试与 smoke 段落（smoke_conversation_status 的项目汇总、smoke_project_activity 的计数、smoke_project_relay 的“新开一段”），补 smoke_project_chat（约束、ensure、迁移多段→一段 / 回退 / 幂等、运行对话不误伤）与 App / Web 新行为测试。
**成本**：一次迁移（单用户几十段对话，秒级）；`GET /api/projects` 查询从“每项目 100 段 + for_list”降到“每项目 1 段 + for_list”；项目对话不再自动起标题（每 10 条省一次 lite 调用）；客户端进项目少一次列表渲染。无新模型调用。

## 2026-10-15 v2.96 “我 → 连接的账号”一页（HANDOFF 5 · 2a 第三条；顺带核实第二条）
**现状（动手前查清）**：三页两套入口。“我”→「账户」收拢页（`/me/accounts`，MeHub.accounts，只有两行）→ ①「连接的账号」= 连接器页 `/me/connectors`（标题却叫“连接器”：OAuth 账户 + MCP 服务器 + 一行“API Key 与网站登录”跳走）；②「密钥与网站登录」= 保险箱页 `/me/vault`（标题“保险箱”：网站登录 / API Key / 环境变量）。同一个“去存 Key”有三条路（收拢页、连接器页末行、主页卡 `vault`），用户要点三层才看到全部，页名三个说法。
**第二条（没配置的提供方）核实结论：v2.90.2 已做到，不重复**。两端 `sortAccounts` 不画 `status=unconfigured`；连过但服务器后来删了配置的行不给“重新连接”；缺配置时账户区末尾只有一行“服务器还差一步：配置 X 授权”，点开 `oauth_setup_sheet` / `OAuthSetupSheet` 引导（回调地址、变量名、重启命令、docs/oauth-setup.md）；聊天连接卡 unconfigured 无按钮（`connectCardState`）。“普通用户不显示、管理员显示”：Toyuis 单用户（`auth.py` 只有一个主人 = 部署者），登录者即管理员，等价成立；将来多用户再加角色判断。本轮这部分只随页面合并原样搬进新页。
**决定**
1. **一页**：`/me/connectors`，标题「连接的账号」（与“我”页行名、HANDOFF 用词一致）。分区按“越省事越靠前”：账户（OAuth 一键授权 + 缺配置那一行）→ MCP 服务器 → 网站登录 → API Key → 环境变量；分区只在有内容时出现。
2. **一个添加入口**：页头 + → “添加什么？”（MCP 服务器 / 网站登录 / API Key / 环境变量，四类同一份文案表 `addKinds`）。删 MCP 分区自己的 +、保险箱页头 +。MCP 与密钥都空时只放**一张**起步卡（四个按钮），替换原来的 MCP 起步卡 + 保险箱起步卡两张。
3. **“我”页直达**：“我”的「账户」行改为「连接的账号」直接进这一页；删 `/me/accounts` 收拢页（MeHub 只剩“个人资料”）。少点一层。
4. **数据源不变、不新增接口**：三类数据本来就各有唯一后端（`/api/connectors`、`/api/connectors/mcp`、`/api/vault`），页面只是同时读三份；不做聚合接口（那会是第二份来源）。页头摘要合成一个函数 `connectorSummary(accounts, servers, secrets)`：“已连接 N 个账户 · N 个 MCP 服务器 · N 项加密保存 · N 个需要处理”，删 `vaultSummary`。
5. **卡片去处 `vault` 并入 `connectors`**：后端 `card_targets.PAGES` 删 `vault`；`task_wall` needs_login 与浏览器登录过期提醒改指 `connectors`；迁移 0067 把 `home_cards.target='vault'` 改成 `connectors`（单向数据清理，downgrade 不还原——旧服务端也认识 connectors）。两端 cardTargets 删 `vault` 行；“去连接器”文案改“去连接的账号”。老 APK 收到 connectors 照样能开。
6. 两端同构：App `vault_screen.dart` → `secret_rows.dart`（只剩存入表单与行，无页面）；Web `VaultScreen.tsx` → `SecretSheet.tsx`（表单弹层 + 行），页面只剩 ConnectorsScreen 一个。
**删除清单**：App `VaultScreen`、`/me/vault`、`/me/accounts` 路由、`MeHub.accounts`、`vaultSummary`、MCP 区 +、保险箱起步卡、连接器页“其他服务”分区；Web `VaultScreen`、`me/vault`、`me/accounts` 路由、MeHub `accounts`、`vaultSummary`、同上 UI；后端 card target `vault`；测试里保险箱页的用例改写到连接的账号页（不保留旧页测试）；截图脚本的 vault 一张。
**成本**：无新接口、无模型调用；一条只改数据的迁移（几行 UPDATE）；页面多读一份 `/api/vault`（原来要进第二页才读）。
**结果**：按上面落地。测试：flutter analyze 0、flutter test 674 过 8 跳过、npm run build 过、后端 smoke 202/202（不含 smoke_stepfun）。没做：浏览器 / 真机截图核对（本机无 Chromium）。

## 2026-10-15 v2.97 E1 收尾：ListRow / ListGroup / PageIntro 两端统一 + 附件弹层高度
**依据**：HANDOFF 第五节第 6 项“E1 收尾（ListRow/ListGroup/PageHeader 统一、附件弹层高度）”。`docs/home-redesign.md`（E1 原始定义）不在仓库里（HANDOFF 早已注明从没提交），本轮按代码现状归纳标准如下。
**现状（动手前查的）**
- App：分组有两个名字——`ui/glass.dart GlassGroup`（实现）和 `ui/kit.dart ListGroup`（只转发的别名，不支持 separator），页面混用（11 个文件用 GlassGroup、19 个用 ListGroup）；行叫 `RowTile`（kit.dart），但记忆行 / 笔记行 / 任务备忘行三处各自拼 `InkWell + Padding + Row`（行高、图标位、箭头位各不一样）；子页说明有 `PageIntro`（摘要 + 说明）和 `SubPageLine`（只有说明）两个组件。页头（玻璃标题栏）只有 `SubPage/GlassAppBar` 一个，已统一，不动。
- Web：页头 `PageHeader` 已统一（没有页面自写 header），不动；**没有行 / 分组组件**——全站 104 行手写 `className="row …"` / `"list …"`，“我的”页另有私有 `meRows.tsx`（MeRows）；子页说明有 `PageIntro` 和 3 处手写 `<p className="desc sub-line">`。
- 附件弹层（App 输入框“+”）：**现象**——手机上一开就是几乎全屏高（实测 1080×2340、状态栏 + 手势条：弹层 807/851 逻辑像素），四个来源图标挤在最上面、下面一大片空。**根因**——`GlassSheet` 给内容的是“最高到屏幕”的松约束（Flexible），附件弹层每个来源是 `Column` 且没写 `mainAxisSize.min`，Column 默认 max 就把整张弹层撑满；不是 sheets.dart 的问题（其他弹层内容都写了 min）。Web 的附件入口是 Menu 小弹出菜单，没有这个问题。
**标准（决定）**
1. **一个分组、一个行、一个说明**：App `ListGroup`（GlassGroup 实现搬进 kit.dart、改名，删 GlassGroup 与别名）/ `ListRow`（RowTile 改名）/ `PageIntro`（summary 变可选，并入 SubPageLine）；Web 新增同名 `ListGroup` / `ListRow`（kit.tsx，props 对齐 App：icon/title/sub/problem/value/trail/control/to/onClick/off/enter），`PageIntro` summary 可选并入 `.sub-line` 段落。页头两端已是唯一组件（App `SubPage`、Web `PageHeader`），只核实不改。
2. `ListRow` 只加三项能力去吃掉手写行：`titleWidget`（搜索高亮）、`titleMaxLines`（记忆正文 3 行）、`semanticLabel`（整行一个读屏节点）；Web 多一个 `control`（行尾开关 / 分段按钮 / 菜单原样放，不套次要色）。不为统一去改带进度条 / 多行错误说明的“富内容行”。
3. **不叠加**：私有实现删掉（App 三个手写行、GlassGroup、SubPageLine；Web meRows.tsx、手写 sub-line）；旧名在 App 架构测试里禁止再出现；Web check-arch 第 7 条：手写 row/list 只许在登记文件里、数只减不增。
4. 附件弹层：改根因（Column min），加回归测试（手机含状态栏 / 手势条，弹层 < 屏高 30%、标签下只剩内边距 + 安全区；已做变异验证：去掉 min 测试红）。
**删除清单**：App `GlassGroup`（glass.dart）、kit.dart 的 ListGroup 别名、`RowTile` 名、`SubPageLine`、memory_notes `_NoteRow` / memory_screen `_MemoryRow` / task_memory `_MemoRow` 的手写行体、8 处多余的 glass.dart import；Web `features/me/meRows.tsx`、3 处 `desc sub-line` 手写段落、`.note-row-icon` 与 `.note-row` 的 flex 规则（ListRow 自带）；测试：sub_page_test 里“ListGroup 只是 GlassGroup 别名”的断言改为唯一实现。
**迁移范围（本版）**：App 名字全统一、设置式列表行全走 ListRow；仍自己画行的 6 个文件登记在 `test/list_kit_test.dart`（抽屉里的对话 / 项目行、电脑页带进度条的状态行、运行记录多行错误说明、用量分享行——不是设置式列表行，硬并会改坏版式），只减不增；Web 迁了“我的”页 / 个人资料收拢页 / 我的电脑 Pages 行 / 关于 / 偏好设置 / 钱包 / 反馈 / Pages / 密钥行 / 记忆 / 记忆笔记 / 添加记忆弹层（手写 row/list 104 → 81 行）。**没迁**的 23 个文件登记在 check-arch RAW_ROWS（多为“行里再套按钮 + 开关”的分体行：任务、技能；电脑页状态行；连接器页；用量），留下一版。
**成本**：纯前端重构，无接口 / 数据库 / 模型调用变化；无新依赖。行为变化（有意、= App）：Web 记忆 / 笔记行点开类的行补上箭头；App 笔记行副标题由 text3 变成行组件统一的次要色。
**结果**：按上面落地。测试：flutter analyze 0、flutter test 678 过 8 跳过、npm run build 过（架构守卫 216 文件）、后端 smoke 202/202（不含 smoke_stepfun；smoke_stop 并行时偶发超时、单跑过）。没做：Web 剩 23 个文件的手写行、App 6 个富内容行、浏览器 / 真机截图。

## 2026-10-15 v2.98 E1 Web 收尾：RAW_ROWS 23 个文件迁到 ListGroup / ListRow
**依据**：HANDOFF 第五节第 6 项 E1 的 Web 剩余（v2.97 登记在 `frontend/scripts/check-arch.mjs` RAW_ROWS 的 23 个文件、81 处手写 `className="row/list"`）。先写决定再改代码。不碰 VPS、不编 APK、不做 E4 与“我的”页搜索。
**决定**
1. `ui/kit.tsx` 只补吃掉剩余手写行所需的最小能力（不新增组件）：`ListRow` 加 `href`（站外链接：新标签页 + noreferrer，默认不带箭头，= 原手写）、`disabled`（整行按钮禁用）、`role`（`group` 时正文 `aria-hidden`，读屏只念 label，= 原手写）、`iconClass`（行首图标位加类，如 `file-ext` 扩展名方块）；`ListGroup` 加 `label` / `role`（aria-label / role 原样透传）。行尾控件一律走既有 `control`（原样放，不套次要色）/ `trail`（次要色 .row-trail）。
2. **能迁的全迁**：一行 = 图标 + 标题/副标题 + 行尾值/控件，且整行是一个可点目标或静态的，全部改 ListRow；分组容器 `div.list` 全部改 ListGroup（包括里面的行暂时保留手写的文件）。
3. **真不适合、保留登记**（版式会坏或语义会错，数只减不增）：
   - 分体行（行里一个可点主体 + 行尾独立按钮 / 开关，按钮不能套按钮）：技能、定时任务、MCP 服务器、收件箱行（`report-row`，行尾时间 + 菜单）、电脑页服务 / 后台任务行（`computer-job`）。ListRow 的整行按钮放不进第二个可点控件。
   - 正文里带细条 / 多行说明的富内容行：电脑页状态行（`computer-status`）、内存 / 磁盘写入行（`computer-mem`）、磁盘配额行（`computer-quota`）、运行记录 / 助手备忘（`run-row`：顶对齐、运行状态点不是 row-icon、错误说明多行）、本月最花钱的对话（行下一条占比细条，flex-wrap 换行）。
   - 主页今天时间线行（行首是时间文字不是 28px 图标位）、回复语言行（副标题位是常驻的 aria-live 容器，ListRow 只在有副标题时才渲染那一格）、项目文件选择行（`role="checkbox"` + aria-checked + 行尾勾选框）。
4. **App 端 6 个登记文件评估：全部保留**。逐个看过：`history_panel`（抽屉对话行：状态点 + 长按 + 选中高亮）、`project_switcher`（项目行：emoji + 状态胶囊 + 当前高亮）、`computer_section`（状态行带内存细条）、`computer_details`（内存 / 磁盘行：标题与大小同一基线 + 细条）、`task_detail`（运行记录多行错误说明）、`usage_screen`（最花钱的对话行下细条）——都是富内容行，没有“内容简单”可直接并进 ListRow 的；硬并要给 ListRow 加细条 / 第二行内容槽，等于再造一个行组件。与 Web 保留的同类行一一对应。
**删除清单**：上述迁移文件里的手写 `row-icon / row-body / row-title / row-sub / row-trail` 行体；`features/chat/chat.css` 的 `.conv-files .row { animation… }` 及其 reduced-motion 规则（改由 ListRow 的 `enter` 错峰，同一 rise 动画、同一 --stagger）；check-arch RAW_ROWS 中迁空的文件条目，其余数字下调到实际值。
**有意的变化**：错峰入场原来写 `animationDelay: calc(var(--stagger) * i)` 的几处（登录设备、浏览器登录、主机规则、装过的工具、对话文件）统一走 `enter` / `--i`（原上限 8 的两处照传 `Math.min(i, 8)`；原来无上限的三处现在第 10 行起同时出现，肉眼无差别）；对话文件弹层的 `.conv-files` 类随之删掉（只剩被删的动画规则在用）。其余外观、读屏文字、交互不变。
**成本**：纯前端重构，无接口 / 数据库 / 模型调用变化。
**结果**：迁完并从 RAW_ROWS 删除 11 个文件（LoginSessions、SecurityScreen、ModelUsageList、OAuthSetupSheet、RouterUsageCard、UsageCard、ProjectFiles、useSaveReply、ConversationFilesSheet、BrowserSessionsSection、HostSection）；另外 9 个文件部分迁移、登记数下调（ComputerDetails 19→6、ComputerSection 6→4、ConnectorsScreen 7→1、SkillsScreen 2→1、TasksScreen 2→1、TaskDetailScreen 5→4、TaskMemory 2→1、TopConversations 3→2、ProjectFilePicker 2→1）；HomeScreen / InboxRow / ReplyLanguageRow 原样保留。手写 row/list 81 → 23 处、23 → 12 个文件；`ui/kit.tsx` 的 ListRow 补 href / disabled / role / iconClass，ListGroup 补 label / role。App 未改代码。测试：flutter analyze 0、flutter test 678 过 8 跳过、npm run build 过（架构守卫 216 文件）、后端 smoke 202/202（不含 smoke_stepfun，逐个串行跑）。没做：浏览器截图核对（本机无 Chromium）。

## 2026-10-15 v2.99 E4 ImageStack + 震动反馈 + “我的”页底部搜索
**依据**：HANDOFF 第五节第 6 项剩下两条（E4 ImageStack + 震动反馈；“我的”页底部搜索），第八节“Hark 发图片的排布（ImageStack）❌”“‘我’页…（底部搜索 ❌）”。`docs/home-redesign.md` 不在仓库，规格按 Hark 公开表现（images 块：同一回复的多张图叠成一摞，点开可翻；关键交互轻触反馈）与代码现状归纳。先写决定再改代码。不碰 VPS、不编 APK。
**现状（动手前查的）**
- 图片：后端只有 `show_images` 一条路（1–6 张，一次调用 = 一个 `ImagesBlock`）。App `ImagesBlockView`：单张 4:3，多张横排可滑的 232×176 小图条（`Layout.imageStrip/imageTileWidth`），点一张开 `showImageViewer`（玻璃对话框里只看这一张，不能翻）；Web `ImagesBlock`：同样横排 scroll-snap，点一张**跳新标签页**看原图，没有站内大图。两端不一致，也都不是“一摞”。
- 震动：App 已有 9 处 `HapticFeedback` 直接散落在 7 个文件（长按聚焦菜单、菜单选中、复制、评分、点气泡看时间、继续、接管、反馈）；没有统一入口，发送 / 下拉刷新 / 开关切换没有。Web 没有任何振动。
- 搜索：现有搜索都各管一个域——历史抽屉顶部（对话标题 + 内容，全局唯一的对话搜索）、记忆页、技能库、Pages 页的列表筛选。“我的”页没有搜索；设置散在 9 个子页里（外观在偏好设置、两步验证在安全…），找一项设置要猜在哪页。
**决定**
1. **ImageStack（两端同构，替换横排小图条与单张大图两种展示）**：一个 `ImagesBlock` = 一摞。单张：照旧 4:3 铺满（宽度上限同一 token），点开看大图。多张：最上面一张 4:3，后面最多露两张（向右下错开 + 轻微旋转、逐层变淡），右下角一个“N 张”小胶囊；第一次出现时后面几张从正下方“扇开”到位（只动 transform / opacity，减少动态时直接到位）。说明文字只显示最上面那张的。点开 = **全屏查看器**：左右滑翻页（App PageView + 每页可捏合缩放；Web 原生横向 scroll-snap，键盘 ← → / Esc），顶部“2 / 4”，底部说明 + 关闭 + 打开原图。Web 不再跳新标签页（“打开原图”按钮保留这条路）。
   - 全屏查看器的路由放 `ui/sheets.dart`（新 `showAppViewer`，弹层只在这一处）；摞和查看器内容放新文件 App `blocks/image_stack.dart`、Web `blocks/ImageStack.tsx`；尺寸 / 角度 / 时长只在 `theme/tokens.dart` / `tokens.css`，扇开 keyframes 在 `styles/base.css`。
   - 范围：一摞 = 一个图片块。同一回复里助手调了两次 show_images 仍是两摞（并成一摞要在消息层合并块，和“块 = 一次工具结果”的单一来源冲突，且提示词已要求一次给齐）；商品宫格 / 订单卡的图不变（那是挑选，不是看样子）。
2. **震动：App 一个入口 `ui/haptics.dart`（`Haptics.tap()` 轻选择 / `Haptics.press()` 长按确认），9 处散落调用全部改走它；新增只在三处：发送消息、下拉刷新触发（PullRefresh 的 onRefresh 起点，松手才触发）、开关切换（新 `AppSwitch`：kit.dart 唯一开关，6 个文件 7 处 `Switch` 改用它）。**翻页、滚动、普通按钮不震（克制）。尊重系统设置：Flutter 引擎 Android 端所有 `HapticFeedback` 类型都走 `View.performHapticFeedback`（不带 FLAG_IGNORE_GLOBAL_SETTING），系统关了“触摸反馈”就不震；`selectionClick`→CLOCK_TICK、`mediumImpact`→KEYBOARD_TAP。不用 `vibrate()`（→ LONG_PRESS，偏重、语义是长按）。架构测试守卫：`HapticFeedback` 只许出现在 `ui/haptics.dart`。
   - **Web 不做振动**：Web 是电脑端客户端（手机走 App），桌面浏览器无振动；`navigator.vibrate` 在 iOS Safari 不存在、在 Android Chrome 是马达长震而非系统轻触，也不受系统触摸反馈设置约束，与“轻、克制”相反。不留空入口。
3. **“我的”页底部搜索 = 搜设置与页面，唯一入口**：与历史抽屉的对话搜索不重复（域不同：一个找对话，一个找“某个设置在哪”），记忆 / 技能 / Pages 页内的筛选是各页自己的列表，也不重复，不合并。做法：两端各一份静态索引（App `features/me/me_index.dart`、Web `features/me/meIndex.ts`，同一份条目：标题、所在位置、关键词、路由），“我的”页底部一颗搜索胶囊（固定在底部，和主页输入胶囊同一位置感）；输入时页面主体换成命中结果（ListRow：标题 + 所在位置，点了直达），清空回到原页面；没命中给一行说明（对话请在历史里搜）。不新增接口、不查后端。
**删除清单**：App `ImagesBlockView` 的横排条与 `_Figure`、`showImageViewer`（玻璃对话框单张大图）、`Layout.imageStrip / imageTileWidth`；7 个文件里直接调用的 `HapticFeedback.*`（及其仅为此的 `services.dart` import）；Web `ImagesBlock` / `Figure` 与 `.blk-images / .blk-figure*` 样式、点图跳新标签页的行为。
**成本**：纯前端；无接口 / 数据库 / 模型调用变化；无新依赖。查看器只在点开时建，图用已缓存的同一 URL。
**参考来源（借鉴思路、按本项目 token / 组件自己实现，未引入依赖）**
- Flutter `HapticFeedback` API：https://api.flutter.dev/flutter/services/HapticFeedback-class.html ；引擎 Android 实现 `PlatformPlugin.vibrateHapticFeedback`：https://github.com/flutter/flutter/blob/main/engine/src/flutter/shell/platform/android/io/flutter/plugin/platform/PlatformPlugin.java （核实“尊重系统触摸反馈设置”与各类型对应的系统常量）。
- Apple HIG「Playing haptics」：https://developer.apple.com/design/human-interface-guidelines/playing-haptics （只给离散事件、同一动作同一触感、避免滥用、可关闭）。Material 3 haptics 页面已 404，未采用。
- 缩放与翻页冲突：photo_view 画廊在 scale state 非 initial 时锁 PageView（https://github.com/bluefireteam/photo_view/issues/105 、/issues/216）；flutter/flutter#68594 与 StackOverflow 64748389 的 TransformationController + 放大时禁翻页做法。本项目取同一思路：每页 `TransformationController`，放大 >1.01 倍时 PageView 换 `NeverScrollableScrollPhysics`，双击在原大 / 2.5 倍间切换（以点按处为中心）。**没引入 photo_view**：一个画廊用 InteractiveViewer + 40 行即可，多一个依赖不值。
**落地结果**
- [x] ImageStack 两端：App `blocks/image_stack.dart`（ImageStack / ImageGallery / _ZoomPage / _ViewerImage）、`ui/sheets.dart showAppViewer`；Web `blocks/ImageStack.tsx`（样式 blocks.css，查看器样式归 ui/ui.css 与弹层同处）。细节：后面几层不用 Opacity（会互相透），改为实图 + 页面底色薄纱（`Op.stackLayer` / `--stack-veil`）+ 1px 发丝边；图下垫 surface 实底（坏图 / 加载中时后层不透出）；每层固定 ±2°（不随层数放大，叠得整齐）；查看器里竖图横图都按原比例完整显示、坏图显示“这张图片打不开”而不是满屏灰块；页码只在多张时出现。App 用临时截图测试看过明暗两套（单张 / 6 张竖图在上 / 第一张打不开 + 查看器第 1、2 页），截图测试未提交。
- [x] 震动：`ui/haptics.dart` + `AppSwitch` + 守卫测试 `test/haptics_test.dart`。
- [ ] **“我的”页底部搜索：本版不做，留下一版**。判断已定（见上第 3 条：与历史抽屉对话搜索不同域、不重复；做成“我的”页唯一的设置搜索，静态索引两端各一份）。没做的原因：用户 17:21 强调“宁可少做一块，也不要粗糙交付”，这一块要两端各做底部浮动胶囊 + 索引 + 结果态 + 空态 + 明暗截图，本轮步数不够做到同样细致。
- 未验：Web 端没有浏览器可截图（本机无 Chromium），只靠构建 + 代码核对；Web 查看器不做捏合缩放（电脑端点“打开原图”看原尺寸；触屏浏览器可用系统双指缩放）。
- 测试：flutter analyze 0、flutter test 682 过 8 跳过、npm run build 过（架构守卫 217 文件）、后端 smoke 202/202（不含 smoke_stepfun；smoke_preview_ws 并行跑时端口占用失败一次，单跑过）。

## 2026-10-15 v3.0 “我的”页底部设置搜索（HANDOFF 第五节第 6 项最后一条）
**版本号说明**：`brand/sync.py` 规定功能轮 ≤ 99（构建号 = major×10000 + minor×100 + patch），2.99 之后没有 2.100，所以本版进位为 **3.0.0（tag v3.0，构建号 30000）**。这只是构建号规则导致的进位，**不代表破坏性改动**：协议、接口、数据库、MIN_CLIENT 均不变，旧 App 照常连新服务器。`scripts/check_version.sh v3.0` 按 `cut -d. -f1,2` 取 `v3.0`，脚本本身对 3.x 无需改动（本轮实跑确认）。
**依据**：v2.99 节第 3 条已定方案（与历史抽屉的对话搜索不同域、不重复；做成“我的”页唯一的设置搜索，两端各一份静态索引，底部浮动胶囊，输入即筛，点结果直达，能定位到具体设置项更好）。按第二节第 13、14 条，先查参考再动手。
**动手前核对（有没有已存在的设置搜索）**：全仓 grep `设置搜索 / SettingsSearch / meIndex / me_index`、所有 `/me/...` 路由的引用方（只有路由表、“我的”页、顶栏头像），聊天斜杠命令也没有跳设置页的——**没有任何设置搜索**，不存在要合并的第二套。现有搜索各管一域：历史抽屉（对话）、记忆页、技能库、Pages 页（各页自己的列表筛选），都不动。
**参考来源（只学公开表现与公开文章，按本项目 token / 组件自己实现，未引入依赖）**
- Apple「Find settings on iPhone」（iOS 27 版）：https://support.apple.com/guide/iphone/find-settings-iph079e1fe9d/ios ——设置页的搜索框在**屏幕底部**，结果出现在搜索框上方；输入即出结果，点一项直达。本项目底部胶囊与之一致。
- iOS 设置搜索结果带“所在路径”，让人下次自己也找得到（OS X Daily https://osxdaily.com/2015/09/22/search-settings-ios 、How-To Geek https://www.howtogeek.com/661407/how-to-quickly-search-within-settings-on-an-iphone-or-ipad/ ）→ 结果行副标题写“所在位置”。
- LINE 工程博客「How we added settings searching to the LINE app」：https://engineering.linecorp.com/en/blog/how-we-added-settings-searching-to-the-line-app ——点结果后进入对应菜单、**滚到该项并闪一下高亮**；同时提醒“单独维护一份搜索数据容易和设置页脱节”。本项目取前者做法；对后者的应对是：索引两端各一份但由测试互相对照（条目 id / 标题 / 位置 / 路由 / 定位 id / 关键词逐字相同），并检查每个定位 id 在两端页面里都真有落点、每个路由都在路由表里——改设置页忘了改索引，测试会红。
- Hark 表现：Hark 个人页是“一屏装下 + 底部胶囊”的版式（v2.81 已对齐），浮动胶囊与主页输入胶囊同一位置感、同一玻璃材质。
**决定**
1. **索引（单一形状，两端各一份）**：App `features/me/me_index.dart`、Web `features/me/meIndex.ts`。每条 = id、标题、所在位置（显示用）、所属分区（决定行首图标）、路由、可选定位 id、关键词（空格分隔，含同义词：深色 / 夜间 / 2FA / 退出其他设备…）。共 13 个页面 + 10 个具体设置项（外观、减少透明度、头像颜色、回复语言、两步验证、恢复码、登录设备、版本、浏览器登录、主机模式、磁盘——恢复码定位到两步验证那组）。用量页的“自动选模型 / 按模型”、连接的账号里的分区等只做页面级（关键词覆盖），不做定位：它们是数据展示区块，不是开关。
2. **匹配**：复用两端已有的 `searchTerms`（空格分词、引号成词、最多 6 个，与对话搜索同规则）；每个词都要命中“标题 + 位置 + 关键词”才算；排序：标题以词开头 > 标题包含 > 只命中位置 / 关键词，同档按索引顺序。纯本地、零接口。
3. **“我的”页**：底部一颗玻璃搜索胶囊（App 放进已有 `FloatingFooter`——它量胶囊实高交给 PageBody 留白，所以**不会挡住最后一项“退出登录”**；Web 放进 `Page` 的 `footer`，同一个 `--footer-h` 机制）。输入即筛：页头（名字 / 域名）保留，下面的用量卡与两组行换成“搜索结果 N”+ 一组结果行（ListRow：分区图标 + 标亮标题 + 所在位置），交叉淡化切换；无结果用 EmptyHint / Hint：“没有找到相关设置”+“换个说法试试；要找聊天内容，请在历史记录里搜索。”（不回显用户输入，长输入不会撑破版式）。清空（× / Esc / App 返回键先清空）回到原页面。回车 = 打开第一条。
4. **定位到具体设置项**：结果带定位 id 时路由加 `?focus=<id>`。App：路由表对这几页套一层 `SpotlightScope`（ui/kit.dart），目标处包 `Spotlight(id:)`——出现时 `Scrollable.ensureVisible` 滚到视口约 1/3 处并复用已有 `FlashHighlight`（ui/motion.dart，搜索命中消息就是它）闪一下；同一路由只闪一次；PageBody 在有待定位目标时把 cacheExtent 放大，长页（我的电脑）底部的区块也会被建出来。Web：`Page` 读 `focus`，用 MutationObserver 等目标出现（数据异步加载，最多等几秒），`scrollIntoView` 居中后闪一下；行用 `ListRow spot=`，区块用 `<Spot id>`。
5. **合并（替换不叠加）**：Web 聊天里“搜索命中闪一下”的 `.msg.flash` 私有样式与 ChatView 里那段手写重触发逻辑，并进 kit 的 `flashOnce()` + ui.css 通用 `.flash`（行内 inset 0、其他外扩 8px），两处共用一份；顺带补上减少动态时“直接出现、到点消失”（原来 1ms 动画等于看不见）。App `FlashHighlight` 加 `outset` 参数（行内 0，默认 8 不变），不新写高亮组件。`SearchField` 加 `floating`（玻璃胶囊里不再叠一层 tile 底），不新写输入框。
**删除清单**：Web `chat.css` 的 `.msg.flash` 两条规则、ChatView `reveal` 里的手写 classList 重触发；“我的”页 Web 手写的 `div.page.me` 外框（改用 `Page`，同一套底部留白）。
**成本**：纯前端；无接口 / 数据库 / 模型调用变化；无新依赖。索引约 25 条，每次按键线性过滤，可忽略。
**不做**：Web 手机浏览器软键盘下的胶囊跟随（Web 是电脑端客户端，手机走 App；聊天输入胶囊同样不处理，不单开先例）；拼音首字母匹配（索引条目少，靠关键词同义词覆盖）。
**测试与发布（2026-10-15 18:40）**：flutter analyze 0、flutter test 695 过 8 跳过（含 `me_search_test.dart`：两端索引逐字一致、定位 id 两端都有落点、路由在表内、搜索排序 / 无结果 / 清空恢复 / 回车打开首项、`?focus=` 滚动并闪、浮动胶囊不遮“退出登录”）、npm run build 过（架构守卫 218 文件、配色守卫 14 对 × 2 套）、后端 smoke 203/203（不含 smoke_stepfun；smoke_jobs 串行全量中偶发一次超时、单跑过，后端本版只改版本号）。未做：浏览器 / 真机截图（本机无 Chromium）。不部署、不出 APK。

## 2026-10-15 v3.0.1 部署脚本自动清理（HANDOFF 第二节第 17 条“能自动的写进脚本”）
**决定**：清理只放在产生垃圾的那个脚本里，不新增维护脚本。`deploy/build-apk.sh` 的 EXIT trap（成功或失败都走）在恢复容器后调 `apk_cleanup`：先把 APK 拷到 `/root/toyuis-<pubspec 版本>-arm64.apk` 并删旧的 `toyuis-*-arm64.apk`（没编出来就不动上一份），再删 `/opt/apkbuild/gradle` 下除 `wrapper` 外全部、`/root/.pub-cache`、`/opt/apkbuild/src`、`/root/app.tgz`、本脚本自己加的 `/swapfile2`（之前就存在的不动）。SDK / Flutter / JDK、部署代码包、`.env` 备份、`/swap.img` 一律不碰（第 17 条“绝不能删”）。`deploy/update.sh` 在已有 `docker image prune -f`（不带 -a）后加 `docker builder prune -f`。
**代价**：下次编 APK 要重新下 gradle / pub 依赖，多几分钟（用户已接受：“把不重要的删掉”）。
**测试**：新 `deploy/tests/test_build_apk_cleanup.sh`（临时目录模拟 /opt /root：APK 带版本号取出且只留一份、部署包保留、缓存清掉、gradle 只留 wrapper、SDK/Flutter/JDK 不动、构建失败也清缓存不删上一份 APK）；做过变异验证（去掉 `! -name wrapper` 即红）。`bash -n` 两个脚本过；test_install.sh 过。未在 VPS 实跑（按规则不部署、不编 APK）。

## 2026-10-15 v3.0.2 v3.0 截图验收发现的两个问题（本机装好 Chromium 后第一次真渲染网页）
**环境**：/tmp/pw（playwright + chromium + install-deps）装好，`frontend/scripts/shots.py` 能跑了。脚本里 v2.95 起已失效的步骤（点项目内对话列表 `.project-home`、项目对话抽屉“项目对话 / 新对话”）删掉改成“进项目即聊天、≡=切换项目”；补 `/api/auth/2fa`、`/api/auth/sessions` 假数据；新增 me-search / me-search-empty / me-focus 三张。
**发现并修**：
1. 定位目标是异步加载的区块（登录设备、电脑页各节）时，外壳先出现、高度 0 → 立即滚过去并对一条空边闪一下，之后内容才出来。两端都改为“目标有高度才定位”：Web `useSpotlight` 里 `getBoundingClientRect().height < 1` 视为未出现、继续等 MutationObserver（上限仍 5 秒）；App `Spotlight._reveal` 每 100 ms 看一次 `context.size`，最多 5 秒（`Timing.spotlightWait/spotlightPoll`，= 网页 SPOT_WAIT_MS），有高度才 claim + ensureVisible + 闪。新测试“数据晚到”，变异验证过（去掉等待即红）。
2. Web `<Spot>` 外壳让里面的 `.section` 变成第一个孩子 → `.section:first-child{margin-top:0}` 把分区间距清零（安全页“登录设备”紧贴上面的卡）。ui.css 加 `.spot > .section:first-child` 恢复 `--section-gap`、外壳在页首时仍为 0。App 分区间距在 SectionTitle 自身 padding 里，无此问题。
**看过没问题**：搜索结果 / 无结果 / 胶囊明暗、桌面宽度居中、定位后位置。**仍未看**：App 截图（需中文字体环境）、真机。
**另记（未改，属既有问题）**：手机宽度 400 下项目聊天输入框带“快速”芯片时，占位符“给 Toyuis 发消息”被截成“给 Toyuis 发消”。



## 2026-10-15 19:45 v3.1 视觉细腻度（用户 7 张 Hark/Toyuis 真机对比截图）
全局判断（宗旨 #1）：差距不在某个页面，而在全局 token —— 只改 token + 两处读取点，不加组件。实测同机像素：
- 字：Hark 气泡/分段字形高 ≈38px，我们 ≈46–48px（大 ~20%）→ Fs 全档降一档 xs12 sm14 md16 lg19 xl30 display32（web --fs-* 同步）。
- 色：Hark 暗色卡/回复气泡 #1E2029、输入胶囊 #1B1D25；我们 #0A0D16 近黑，在海军蓝底上是“黑块”→ dark surface #1E2029、surface2 #272A34、border #2E313C、accentSoft #2A2D38、glass E01B1D25、glassSheet F51E2029（web 同值，配色守门通过）。
- 边：Hark 深色浮层无描边；我们顶栏胶囊/圆钮/输入胶囊/头像一圈 8% 白 → 新增 Palette.chromeEdge（浅 = glassBorder，深 = 透明；solid = border），glassBorder 继续只做分隔线。web --chrome-edge 只用在 .glass / .avatar / 顶部搜索胶囊。
- 位：Hark 输入胶囊左右内收 ~38dp，我们 12 → Composer 外边距改 Layout.gutter(24)，与全 App 留白同线（不新加常量）。
- 选中段未读点：白点压在白胶囊上只剩 surface 色描边 → 像“°”；选中时改 onPillOn。
- 头像首字 w600→Weights.title、0.42→0.4。
未动（有意）：“已思考 N 秒”行（功能）、主页卡标题字体（v2.83 已定无衬线）、输入框 ⊕/快速/模式 芯片的布局（属交互改动，需单独全局评估）。


## 2026-10-15 20:30 v3.2 字体（用户：“不够细腻，特别是字体”）
全局判断：字形不统一是根因，不是字号。Flutter 在安卓按名字取不到系统 MiSans → 中文落到思源黑体，拉丁是 Inter，两套 x 高/笔画/字距不同；Hark（原生）中英同一套系统字。另外两处让字“散”：全局 tabularFigures（正文数字一格一格）、labelSmall 字距 0.5。
决定（替换不叠加）：唯一字族 = 打包的 MiSans（许可：免费商用可嵌入，须注明，不得改字形；子集不改字形），删 Inter（App+网页）；数字比例宽为默认，等宽只留在网页已有 tabular-nums 的类和 App 钟点列/计时/任务时间；删 labelTracking token 与全部引用。子集 8762 码位（GB2312 + 源码用字 + 标点/符号），ttf 1.7MB×3（APK +~5MB），woff2 0.93MB×3（网页首访一次、之后缓存，font-display: swap）。注明：两端「关于 → 字体 MiSans（小米）」。
- 正文行距 Fs.prose/--lh-prose 1.6→1.4（Hark 约 1.33）。

## 2026-10-15 22:00 v3.2.1 交接文档三处小尾巴（用户：“做啊”“不要停下来”）
- 历史搜索：原来面板 scope=None 只搜主聊天，项目那段根本搜不到（HANDOFF 写的“无 project_id”实为搜不到）。对标 Hark 顶部搜索“搜全部”：面板改 scope=ALL（= search_history 工具同一范围，不新增分支），项目那段的结果带 project_id/project_name；任务运行对话不带（照旧按 id 打开，v2.75 规则不变）。客户端：结果行加项目名（.conv-where / 摘录前缀），点开走唯一跳转入口（App openConversation、Web openElsewhere）+ focus 定位；项目行不给菜单（项目对话 DELETE 409，改名归项目）。openProjectChat 接受 focus。
- 占位符截断：Web 输入框档位钮在 ≤480px 只留图标（.chip-text 隐藏，aria-label 不变）；App 本来就窄，不动。
- shots.py 补 /api/connectors/mcp、/api/memory-notes、/api/version 假数据（跑完不再列缺失清单）。

## 2026-10-15 23:15 v3.3 项目列表 + “我的”搜索胶囊按 Hark 真机截图重做（用户 23:02/23:09 截图 1000035503、1000035505）
- 用户原话：“人家是全屏显示那个项目名称的…你搞个半个”；“搜索框你做那么长干嘛…人家小而美，没有占满屏宽”。
- 根因：项目行把 emoji + 名字 + 状态胶囊 + ⋯ 塞在一行，名字被挤成半截省略；页头还有一行“N 个项目 · 最近 …”。Hark：名字占满整行（可折行），状态胶囊另起一行，没有页头、emoji、⋯。
- 改法（两端同一版式，替换而非叠加）：App `_ProjectRow` = Column(名字 displaySmall 最多 3 行, 胶囊)；删 `_Header` 及摘要逻辑；菜单 = 长按（同项目内药丸那份 showProjectMenu）。Web 同：删 page-hero-label 摘要与 emoji，名字可折行（line-clamp 3），胶囊一行；⋯ 留在胶囊那一行右端（电脑没有长按），不占名字宽度。
- “我的”底部搜索胶囊：两侧在页面留白 24 之外再内收 Sp.x3（= 36，≈ Hark 屏宽 1/12）；App me_screen `_SearchBar`、Web `.me-search` 同值；me_search_test 断言左右内收。
- 删除/合并：项目列表页头摘要、列表 emoji、列表行 ⋯（App）。

## 2026-10-15 v3.3 页面不再每次骨架屏：统一 SWR（stale-while-revalidate）
- 用户原话（截图“用量与花费”每次进都是灰骨架）：“每次切到另一个页面去，就要刷新好久…主流软件要这样刷新吗？不只是APP，网页版也一样…学人家的做法”。
- 根因：App 里一批 `FutureProvider.autoDispose` / `AsyncNotifierProvider.autoDispose`（用量、某天明细、对话文件/上下文/用量、反馈、任务运行记录、两步验证、登录设备、偏好、电脑/主机/浏览器登录、分享状态、记忆摘要）离开页面就丢数据，回来从零取 → 骨架；首页 `cards.isLoading`、任务详情 `tasks.isLoading` 下拉刷新时也闪骨架。Web 每个页面各写 `useEffect + http.get`，路由切换卸载组件，回来又从 `loading=true` 开始。
- 参考（只学公开做法）：Vercel SWR（MIT）“先给缓存、后台重验、有数据时错误不打扰”、TanStack Query `staleTime` / `keepPreviousData`、Riverpod 3 文档 `AsyncValue` 的 `skipError` / `copyWithPrevious`。没有移植代码。
- 全局决定（替换，不叠加）：
  - **App 一个机制**：`core/swr.dart` = `SwrCache`（进程内、有上限 LRU，按“服务器 + 登录态”换新，退出登录即清空）+ `SwrNotifier<T>`（build：缓存有就**同步**返回 AsyncData 并在后台重验，没有才请求；后台失败保留旧值不打扰；`reload()` 给下拉刷新，失败抛给调用方；`emit()` 给增删改；数据没变不发新状态，避免无谓重建）+ `swrGet` / `swrGetFamily` 一行声明只读资源 + `AsyncValue.swr(...)` 统一“有数据就显示数据，没数据才骨架/出错”。`ResourceNotifier` 改为继承 `SwrNotifier`（原 cacheKey 磁盘缓存保留为 `diskKey`），各页面自己的 FutureProvider / 自写 reload 全部删掉改用它。
  - **磁盘缓存**：原有项目、首页卡片保留；用量报表、技能、任务、连接器、Pages、记忆、笔记加磁盘键（冷启动也秒开）；保险箱、钱包、两步验证、登录设备等安全相关**只放内存**。
  - **Web 一个机制**：`lib/swr.ts`（模块级缓存 + 订阅，按 URL；有上限；登出清空）+ `hooks/useSwr.ts`（`data` 立即给缓存，后台重验；`loading` 只在没有缓存时为真；有数据时错误静默）；`useResource` 改为基于它；各页面 `useEffect + http.get` 换成 `useSwr`。
  - 底部 Tab 本来就是 `StatefulShellRoute.indexedStack`（App 切 Tab 不重建，已核实）；子页面靠缓存秒开。
- 成本：内存缓存上限 64 条（JSON 原样，几十 KB 级）；每次进页面一次后台 GET（原来也是一次），没有新增请求；同步返回缓存 → 首帧就是内容，无骨架闪、无 FadeSwitcher 过渡，减少了重建与动画（流畅性只增不减）。
- 删除/合并：各页面自写的 FutureProvider / reload / 骨架判断（`isLoading`）、Web 各页面重复的 fetch + loading/error state。

## 2026-10-16 16:05 交接（额度用尽前）
- 分支 wip/v3.3（未合 main、未改 VERSION、未部署，线上仍 v3.2.1）。
- 已测：项目列表 Hark 式两行、“我的”搜索胶囊内收（27 项定向测试过，web tsc+check-arch 过）。
- 未测：App SWR（core/swr.dart + 多页面）、流光壁纸（sky.frag / ui/sky.dart / SkyTable / SkyClock / glass.dart）。/tmp/flutter 被清，未跑 analyze，可能编译不过。
- 未做：Web SWR + 流光；BackdropGroup、删 TopFade 整页遮罩、聊天流式只重建末条、Markdown 样式缓存、Web mask-image。
- 详细步骤与文件清单：HANDOFF.md 第〇节。

## 2026-10-16 v3.3 B1/B2 App 部分验证与收尾（SWR + 流光壁纸）
- 范围：只动 app/。让 10-16 交接时“写了没测”的 SWR 与流光壁纸编译通过、补测试；卡顿那批（BackdropGroup / TopFade / chat_view）不在本节。
- SkyClock（ui/motion.dart）收紧为**真正的单 Timer**：原来 30fps 帧计时器 + 每分钟重算天色两个 Timer.periodic → 合并为一个，帧回调里顺便按 Sky.recolor 检查钟点。
- reduce-motion（MediaQuery.disableAnimations）原来是“不订阅时钟”，副作用是天色也冻在启动那一刻 → 改为两档订阅：动画订阅者（≈30fps 漂移）与静止订阅者（只每分钟换天色，柔光停在原位）。同一个 Timer 只按最高档跑；没有订阅者 / 不在前台 / 测试环境（FLUTTER_TEST）时一个 Timer 都不起。效果不删：减少动态时壁纸照样随钟点变色，只是不流动。
- SkyLayer 自带 RepaintBoundary（原来靠 glass.dart 外面包一层，fade 顶条另用时容易漏）；删掉没人用的 child 参数（有 child 时它会跟着每帧重画）；删 isComplex（每帧都变的画面做光栅缓存无意义）；着色器异步加载完成后通知重画（原来静止时要等下一次变色才换成着色器）。
- SwrGet(orNull) 取不到时 parse(null) 会抛类型错 → orNull 时 null 直接给 null。
- 成本：Timer 数 2→1；减少动态时每分钟一次重画；无新依赖。
- 已知、留给下一节：壁纸 30fps 变化会让上面每个 BackdropFilter 每 33ms 重新取样模糊，这正是 BackdropGroup 那一项要解决的，本节不动。
- 结果（16:47）：flutter analyze 0；flutter test 719 过 / 8 跳过 / 0 失败（新增 swr_test 9 例、sky_test 13 例）。另修 SwrNotifier.emit 判“没变”的别名问题（改为比存入时的 JSON 签名）。测试侧：19 个文件补 MemoryCacheStore 覆盖（新磁盘键在 testWidgets 假时钟下等真实 IO 会挂死）。参考：Flutter 文档 FragmentProgram / RenderCustomPaint（非重绘边界，故 SkyLayer 自包 RepaintBoundary）、Riverpod 3 文档（invalidate 后 build 同步给缓存）。

## 2026-10-16 v3.3 Web：SWR + 流光壁纸 + 去整区遮罩（HANDOFF 第〇节 B1/B2/B3 的 Web 部分；App 只读对照 core/swr.dart、ui/sky.dart、tokens.dart SkyTable、motion.dart SkyClock）
**B1 SWR（替换，不叠加）**
- 一个机制：`src/lib/swr.ts` = 模块级缓存（Map 当 LRU，最多 64 条 = App SwrCache.max；键 = 请求路径；值 = 服务器原样 JSON）+ 每键订阅 + 同键并发请求合并 + 代号（`swrClear()` 后上一代的在途请求回来也不写缓存）。纯逻辑、零依赖，node:test 直接测。
- `src/hooks/useSwr.ts` = React 读法（useSyncExternalStore）：有缓存首帧就是旧数据，挂载时后台静默重取，变了才替换（JSON 相同不发新状态，= App SwrNotifier.emit）；`loading` 只在没缓存且没出错时为真；有数据时出错不打扰，没数据才给 `error`；`mutate()` 给增删改（写进缓存，所有用这把键的组件一起变）；`reload()` 永不抛（App reload 没数据时抛给调用方，Web 改为放进 `error`——调用方都是按钮/轮询，抛出去只会成未处理的 Promise）。
- `useResource` 改成 useSwr 之上的列表增删改（接口不变）；顺带修掉旧版每次 reload 都把 loading 置真 → 首页 5 秒轮询会闪骨架。
- 退出登录 / 登录过期（App.tsx onUnauthorized，MeScreen 退出也走它）→ `swrClear()`；Login 成功前也清一次（换服务器 / 换账号看不到上一个人的数据）。Web 无磁盘缓存（浏览器刷新即冷启动，和改前一样），安全相关数据本来就只在内存。
- 替换 17 处 `useEffect + http.get`（HANDOFF 第〇节 B1 列表），各自的 loading/error/live 标志一起删。check-arch 加第 8 条：`http.get` 只许在登记文件里（未迁的只减不增），页面读数据走 useSwr。
- 参考：Vercel SWR 文档（MIT）“stale-while-revalidate / dedupe / mutate”、React 文档 useSyncExternalStore；未移植代码。
**B2 流光壁纸**
- 色表唯一一份在 `tokens.css`：`--sky-<night|dawn|day|dusk>-<top|bottom|a|b|c>`，浅色在 :root、深色在 [data-theme=dark]，= App SkyTable.light/dark 逐值（check-contrast 查两端同值 + 正文对壁纸任意色 ≥4.5、深色次要字对底色 ≥4.5）。
- `src/lib/sky.ts`：关键帧 = App Sky.keyframes；按本地钟点在相邻两帧之间线性插值（= Color.lerp 逐通道），写到 <html> 的 `--sky-top/bottom/a/b/c`；每分钟一次（= Sky.recolor），页面隐藏时停、回来立刻重算；切浅/深色、减少透明度时（MutationObserver 看 data-theme）重算。`--sky-*` 用 @property 注册成 <color>，切主题时跟着 .theme-switching 一起渐变（只在那 400ms 内）。
- `base.css` `.sky`：固定全屏一层（z-index -1，不参与布局），底色 = 竖向渐变（色标按 Sky.ramp 取 5 个点），上面三团柔光 = 三个 radial-gradient 元素，高斯衰减用 9 个色标逼近 exp(-d²/r²)，不透明度 = Sky.blobMix；漂移 = 外层 translateX、内层 translateY 两条 alternate 动画（easeInOutSine ≈ 正弦，周期 = sky.frag 里的角频率），只动 transform；will-change 只给这 6 个漂移元素。减少动态：动画 none（静止，颜色仍按钟点变）；减少透明度：整层换实色 --bg、不画柔光（= App Backdrop solid）。
- 删除：`--backdrop-1/2/3`（浅、深、solid 三处）与 body 的 160° 渐变背景。
**B3 Web 卡顿：整区 mask-image → 顶部窄条**
- 根因：`.shell.has-bar .page` 与 `.thread` 的 mask-image 让整个滚动区成为离屏遮罩层，滚动 / 流式输出每帧都要整块重新合成。
- 改法（= App 把 TopFade 整页 ShaderMask 换成 SkyLayer(fade:)）：滚动区去掉遮罩，换成一条只有渐隐带高的 `.sky-fade`（ui/Sky.tsx `SkyFade`），里面是同一张壁纸的副本（按自身在视口里的位置反向偏移，与全屏壁纸逐像素对齐；漂移动画用 Web Animations 把 startTime 对齐到同一时间原点），用窄条自己的 mask 从“全是壁纸”渐变到“全透明”。壁纸以 α 盖在内容上 = 内容以 1-α 透到壁纸，视觉不变：`.page` 用原来的 6 个色标（反过来），`.thread` 用原来的两点。滚动区加 `isolation: isolate`，保持原来遮罩带来的层叠关系（内容里的浮层仍在渐隐条下面）。
- 成本：遮罩面积从整屏滚动区降到约 100px 一条；每条多 3 个柔光副本（被窄条裁掉，只栅格化可见的那一小块）。
**测试（2026-10-16）**：`npm run build` 过（架构守卫 222 文件、配色守门 14 对 × 2 套 + 壁纸 20 色 × 2 套且与 App 同值、tsc -b、vite build）；`npm test` 11/11（swr 7、sky 4）；系统 Chromium（apt）跑截图：用量页返回首帧 0 骨架、渐隐条与全屏壁纸逐像素差 ≤1/255、reduce-motion 下 0 个动画在跑、减少透明度下壁纸 = 实色 --bg、无页面报错。**发现**：浅色壁纸上次要字 --text-2 对比度 1.60–4.60（见 HANDOFF 第〇节 B2），两端同表，未改。

## 2026-10-16 v3.3 B2 流光壁纸：次要字对比度（App + Web 同一张色表）
- 问题：壁纸全天采样（每 15 分钟 × 底色 11 个高度 + 三团柔光峰值），浅色 text2 1.60–5.10、text3 1.02–3.23；深色 text2 3.97–7.56、text3 2.61–4.98。页头说明、分区标题直接压在壁纸上发灰。
- 决定（主代理定）：不删效果、不改字的层级（次要字不换成正文色）。改天色关键帧：浅色顶部 / 夜间几帧提亮，深色柔光压暗；保留“夜里暗蓝紫灰、白天亮蓝→暖米、柔和流动”。
- 做法：每个关键色在 OKLab 里只抬 / 压明度、尽量保留色相与彩度（超色域时按比例收彩度；浅色夜间彩度 ×0.75、黎明 / 黄昏 ×0.85，免得提亮后比白天还艳），二分到“该色亮度够”，再用与 sky_test 相同的采样（Sky.ramp + blobMix + 15 分钟插值）验证并留 ≥0.02 余量。脚本只在本地算，结果直接写进两端色表。
- 浅色只调天色不够体面：要让 #64605a 达 4.5、#857f77 达 3，壁纸每一处相对亮度都得 ≥0.757（≈L* 90），整张图几乎褪成白，白天的亮蓝、上下渐变都没了。所以按授权**两端同步微调 token**：text2 #64605a → #5c5852、text3 #857f77 → #7a746c（都只深一点，text2 / text3 之间的亮度比 1.53 → 1.54，层级不变；对 bg / surface / surface2 分别 6.42 / 7.06 / 6.16 与 4.20 / 4.62 / 4.03，只升不降）。这样壁纸亮度门槛降到 0.64，白天顶色还是看得出的天蓝 #add6fe。
- 深色只动天色：黎明 / 白天 / 黄昏的柔光略压暗（夜间不变），text2 / text3 token 不动。
- 守门：App test/sky_test.dart 加“次要字对壁纸”一组（浅深 × text2 ≥4.5、text3 ≥3.0，同一采样）；Web check-contrast.mjs 改为同一采样（关键帧插值 + ramp + blobMix），正文 / text-2 / text-3 三条阈值全查（替换掉原来“只查 20 个关键色 + 深色 text-2 只查 top/bottom”那条）；tests/sky.test.ts 加浅深两套同阈值单测。
- 成本：只改色值和测试，运行时零变化。
- 参考：WCAG 2.x 相对亮度 / 对比度公式（W3C Understanding SC 1.4.3）；OKLab（Björn Ottosson, 2020）做“保色相只改明度”。
- 结果（2026-10-16）：对壁纸最低对比度 浅色 text 12.37 / text2 4.63 / text3 3.03（原 4.84 / 1.60 / 1.02），深色 text 11.83 / text2 4.74 / text3 3.13（原 9.89 / 3.97 / 2.61）。`flutter test test/sky_test.dart` 17/17、`test/a11y_test.dart` 12/12；web `npm run build` 过（配色守门含壁纸全天采样）、`npm test` 13/13。改旧值必红（实测把 --text-2 改回 #64605a → 两端不同值 + 次要字/壁纸 4.09）。未做：真机 / 浏览器截图肉眼看新浅色壁纸。

## 2026-10-16 v3.3 B3 App：卡顿根因（BackdropGroup / 去整页 ShaderMask / 流式只重建最后一条 / Markdown 样式缓存）
- 范围：只动 app/（不碰 tokens.dart 色值、sky_test）。不删任何功能和效果。
- **毛玻璃分组**（官方 API：Flutter 3.47 `BackdropGroup` + `BackdropFilter.grouped`，源码 widgets/basic.dart；引擎 impeller/display_list/canvas.cc `SaveLayer` 的 backdrop_id 分支）：
  - 语义（读引擎源码确认）：同一个 BackdropKey 的滤镜，**第一个**画到时才“翻转”渲染目标取一次背景，滤镜全相同时整张背景只模糊一次，后面的成员直接从这张结果里取自己那块。所以：①成员彼此不能重叠；②第一个成员画下之后、后面成员底下又画的东西，后面成员看不到；③第一个成员若在淡入淡出（Opacity 离屏层）里，取到的是离屏层的背景，其他成员会跟着错。
  - 分三组：AppShell（顶栏分段 + 一级页面的左侧按钮 / header 药丸；收件箱横幅在组外，它要模糊顶栏）、ShellPage 内容（输入胶囊、回到最新、错误条、主页输入框的“收起”钮）、SubPage（玻璃标题栏 + 子页里的浮层）。另把云浏览器接管页的两颗玻璃钮编一组。“我的”页不分组：返回钮在滚动列表里、搜索胶囊在列表之后，返回钮先画会让搜索胶囊看不到它后面画的列表（规则②）。弹层 / 对话框 / 磨砂遮罩各自独立（在根路由或要模糊成员本身）。
  - 绘制顺序按规则②③排：ShellPage = 内容 → 顶部渐隐条 → 左侧按钮（稳定、不淡入，做“取背景”的那一个）→ header（药丸有进场淡入，排在后面只当读者）；输入胶囊永远第一个画（底条 Column 用 verticalDirection.up、输入行用 rtl 排版，布局不变、只换绘制先后；读屏 / 焦点顺序按几何排序不受影响）。
  - 例外处理（规则②③）：ShellPage 所在路由在转场（项目页淡入上浮）或主聊天历史抽屉露出时，左侧按钮 / header 临时改用页内自己的一组，顶栏变成 AppShell 组里唯一成员 = 照常单独模糊；抽屉是否露出由抽屉内容自己挂载 / 卸载上报（DrawerController 只在露出时才建内容），不改顶栏让位的时机。
  - 壁纸：SkyLayer 已自带 RepaintBoundary，SkyClock 每 33ms 只重录这一层；但它上面的毛玻璃每帧都必须重新模糊（背景在变），这是效果本身的成本，只能把“取背景”的次数降下来。分组后主聊天页每帧翻转 3 次 → 2 次（顶栏组 1 + 输入组 1），项目页 4 → 2，带回到最新 / 错误条时 5–6 → 2；代价是共享组按整张背景模糊一次（引擎自带降采样）而不是只模糊各自那一小块。
- **TopFade 整页 ShaderMask(dstIn) 删除** → ShellPage 顶部一条 `BackdropFade`（glass.dart，和 Backdrop 同一处判断：玻璃模式 = SkyLayer(fade: (clear, solid))，与全屏壁纸逐像素对齐；减少透明度 = 实色 bg 渐隐）。壁纸以 α 盖在内容上 = 内容以 1−α 透出壁纸，视觉不变；离屏层从整页降为 0。顺带：原来输入胶囊等毛玻璃在 ShaderMask 离屏层里，只能模糊“内容 + 透明”，现在模糊的是“壁纸 + 内容”（壁纸本身是柔和渐变，模糊前后几乎一样）。
- **聊天流式只重建最后一条**：ChatController 每个 delta 只换最后一条 Message（其余实例不变）。ChatView 按 消息 id 缓存行 widget，命中条件 = 同一个 Message 实例 + 同一组行状态（时间开关、重新生成 / 继续、引用行、可编辑、定位闪烁、跨天分隔、刚发出），命中就返回同一个 widget 实例，Flutter 直接跳过这一行的重建。
- **AppMarkdown**：MarkdownStyleSheet 按 ThemeData 实例（含浅 / 深、字体）+ 减少透明度缓存（Expando 挂在 ThemeData 上，主题换了自动失效），不再每次 build 新建 + 深比较。
- 删除：kit.dart `TopFade`（及 ramp / alphaAt）、shell_page_test 里对应断言；glass.dart / sub_page.dart 的独立 BackdropFilter 改 grouped。
- 验证：新 test/perf_frame_test.dart（flutter test 里没有真 GPU 光栅，量的是 每帧重建的元素数 / 消息行重建数 / 毛玻璃层数与“取背景”次数 / 离屏遮罩层数 / CPU 侧 build+layout+paint 耗时），改前改后同一份测试各跑一次。
- **实现补充**：组用 `BlurGroup`（glass.dart：BackdropGroup + 自己持有的 BackdropKey；不能直接写 `BackdropGroup(child:)`，它不给 key 时每次 build 新建一个，组里所有滤镜跟着重建；不叫 GlassGroup，那是 v2.97 删掉的旧名、架构测试禁用）。ShellPage 的“另成一组”还加了一条：本页路由上面压着别的路由（isCurrent = false，新页正推进来）时也另成一组。主聊天抽屉“露出”由 chat_scaffold 的 `_Shown` 在抽屉内容挂载 / 卸载后的下一帧上报给 `ShellPage(covered:)`。
- **测量（2026-10-16，flutter test 引擎，412×915，同一份 test/perf_frame_test.dart 先在改前代码的 worktree 跑、再在改后跑；没有真 GPU，光栅只能看层数）**：
  | 场景 | 指标 | 改前 | 改后 |
  |---|---|---|---|
  | 聊天流式（30 条历史，40 个 delta 帧） | 每帧重建元素数（中位） | 695 | 362 |
  | | 最后一条以外的消息行重建（40 帧合计） | 305 | **0** |
  | | CPU 侧 build+layout+paint 每帧（中位） | 31.5–33.9 ms | 21.0–23.0 ms |
  | | 毛玻璃层 / 取背景次数 | 3 / 3 | 3 / **2** |
  | | ShaderMask 离屏层 | 1（整页） | **0** |
  | 一级页面滚动（60 条，30 帧） | 每帧重建元素数（中位） | 440 | 100 |
  | | CPU 每帧（中位） | 15.5 ms | 6.5 ms |
  | | 取背景次数 / ShaderMask | 3 / 1 | 2 / 0 |
  | 主页 | 取背景次数 / ShaderMask | 3 / 1 | 2 / 0 |
  | 项目列表 | 取背景次数 / ShaderMask | 2 / 1 | 1 / 0 |
  - 剩下的 362：最后一条本身（Markdown 重新解析）+ 外层 ChatView / 底条的轻量包装（列表的 KeepAlive / KeyedSubtree 等），不再随对话长度增长。
  - 没测到的：真机 profile 模式光栅耗时（沙盒没有设备 / GPU）；Impeller 共享背景的实际省时只能按引擎源码推断（每组一次 FlipBackdrop + 一次整张降采样模糊）。真机验证方法：`flutter run --profile` + DevTools Performance，看聊天流式和主页静止时 raster 线程（壁纸 30fps 时每帧都要合成）。
  - 发现（未改，不在本块范围）：子页面（SubPage）自带一层 Backdrop，在外壳分支里打开时，外壳的那层壁纸仍在底下每 33ms 重画（被完全盖住）。可以让 SubPage 在外壳里不再画自己的壁纸、或外壳在子页时停掉壁纸，需要连同 FloatAway / 转场一起定。
- 结果：flutter analyze 0；全量 flutter test **729 过 / 8 跳过 / 0 失败**（新增 perf_frame_test 3 例；shell_page_test 改为 7 例：渐隐条位置 / 绘制顺序 / 不挡点击 / 减少透明度实色 / 分组与盖层 / 转场另成一组）。
- 参考：Flutter API 文档与源码 `BackdropGroup`、`BackdropFilter.grouped`（packages/flutter/lib/src/widgets/basic.dart，3.47.7）；Impeller `Canvas::SaveLayer` 的 backdrop_id / `FirstPassDispatcher::saveLayer`（engine/src/flutter/impeller/display_list/canvas.cc、dl_dispatcher.cc：同 id 计数、第一个取背景并缓存、滤镜全同则整张只模糊一次）；Flutter 官方视频 “BackdropFilter” 与 docs “Performance best practices”（saveLayer / ShaderMask 离屏代价）；flutter_markdown_plus 1.0.12 `MarkdownWidget.didUpdateWidget`（样式表 != 才重新解析）。

## 2026-10-16 v3.3 B4：被不透明子页盖住时外壳壁纸暂停（App + Web）
- 问题（B3 留下的发现）：App 外壳分支里打开 SubPage（项目档案 /projects/:id/brief、项目电脑 /projects/:id/computer）时，SubPage 自带一层 Backdrop 壁纸，把外壳底下那层 SkyLayer 完全盖住；但外壳那层的画笔 `repaint` 直接挂在共享的 `SkyClock.time` 上，只要还有任何一层在动（正是子页那层），它就每 33ms 重录一次。B1 的“TickerMode 关就不订阅”只管了 Timer 档位，没管画笔监听，所以被盖住的层照样重画。
- 决定（语义照 Flutter 自己的 `TransitionRoute.opaque`：“不透明路由的进场转场完成后，下面的路由不再构建”）：
  1. `SkyLayer` 不驱动（TickerMode 关）时**画笔不再监听 time / hour**（只留着色器加载完成那一下）；恢复驱动时强制重画一次，直接取共享时钟的当前 time / hour——暂停期间时钟照常走（子页那层在驱动它），所以恢复那一帧就是此刻的天色和柔光位置，和刚才子页上看到的完全一致，不跳色、不闪。
  2. `Backdrop(coverable: true)`（只有 AppShell 用）向下提供一个“盖住计数”；`SubPage` 在自己的路由 `ModalRoute.of(context)` 满足 `opaque && animation.status == completed` 且自己在台上（TickerMode 开：不在后台分支、没被上面的页面盖成 offstage）时报“盖住”，否则撤销。外壳壁纸外包 `TickerMode(enabled: 计数 == 0)`。
     - 转场中（push 进行中、pop / 返回手势一开始 status 就离开 completed）照常显示和动；pop 的第一帧之前就已恢复。
     - 切到别的 Tab：那个分支整体 TickerMode 关 → 子页撤销，外壳壁纸立刻恢复（新 Tab 的一级页面要用它）。
     - “我的”及其子页走根导航器，不是外壳的后代，找不到计数 → 不参与（外壳整条路由在 Overlay 里 offstage，本来就不画）。
  3. 顶栏 FloatAway 的判定（shellBarShown）一字不改，淡出时机不变；不删任何效果。
- 替换了什么：SkyLayer 画笔“永远挂 time”的写法删掉，改成按驱动档挂；没有新增第二套暂停机制（TickerMode 仍是唯一开关，计数只决定外壳那一个 TickerMode）。
- 成本：子页静止时少一整屏着色器重录（每 33ms 一次）+ 外壳 BlurGroup 里顶栏那块的重新取背景；新增一个 InheritedWidget + 每个 SubPage 一个路由状态监听，可忽略。
- Web：只有一层全局 `.sky`（main.tsx），子页面是透明的、透出的就是这层，**子页不会盖住壁纸，不存在这份浪费**。真正整屏不透明盖住壁纸的是“云浏览器接管页”（.takeover，--card 实色）和“看大图”（.image-viewer，--bg 实色）：进场动画结束后根上挂 `data-sky-covered`，`.sky`（含顶部渐隐条里的副本）`content-visibility: hidden` 跳过柔光渲染；关掉时在同一次提交里撤掉。选 content-visibility 而不是 animation-play-state：paused 会冻住动画本地时间并在恢复时改写 startTime，顶部渐隐条副本靠 startTime=0 与全屏层逐像素对齐（syncSky），会错位；content-visibility 跳过期间不推进本地时间但 startTime 不动，恢复时按文档时间线算出“此刻”的位置，和 App 的“恢复取当前时刻”一致。
- 参考：Flutter API `TransitionRoute.opaque`（“When an opaque route's entrance transition is complete, the routes behind the opaque route will not be built”）、`ModalRoute.of`、`TickerMode.valuesOf`、Overlay 对 offstage 条目包 `TickerMode(enabled: false)`（packages/flutter/lib/src/widgets/overlay.dart）；go_router 18.1 StatefulNavigationShell 非当前分支 `Offstage + TickerMode(enabled: isActive)`（lib/src/route.dart）；CSSWG #5611 决议 + MDN content-visibility（跳过的子树里 CSS 动画不推进、可见后恢复），WPT content-visibility-animation-becomes-visible.html。
- 结果（2026-10-16）：flutter analyze 0；全量 flutter test **732 过 / 8 跳过 / 0 失败**（新增 sky_test 2 例、shell_test 1 例）；web `npm run build` 过、`npm test` 14/14（新增 coverSky 计数 1 例）；后端 smoke **202/202**（不含 smoke_stepfun）。未做：浏览器实看浮层关闭那一帧（沙盒无 Chromium）、真机看返回无闪。

## 2026-10-16 v3.3 视觉验收（HANDOFF 第六节“每次 UI 交付都要附截图自评”；main 上改，未提交）
- 做法：两端截图脚本各加一段“明 / 暗 × 夜 2:00 / 黎明 6:00 / 白天 12:00 / 黄昏 18:30”，页面 = 主页、聊天、聊天流式中、项目列表、“我的”首屏 + 翻到底（设置搜索胶囊）、安全子页。
  - App：`test/screens/shots_test.dart` 新 testWidgets「v3.3 壁纸 × 时段截图」（`SHOTS=1 SHOTS_SKY=1 SHOTS_OUT=… [SHOTS_SKY_TIMES=day,…]`；测试里 SkyClock 冻结，直接设 `SkyClock.instance.hour`，`SkyShader.program` 手动加载真着色器，柔光也画）；原「设计 v2 截图」在 SHOTS_SKY=1 时跳过。假接口补 `/api/auth/2fa`、`/api/auth/sessions`。
  - Web：`scripts/shots.py <目录> sky`（`page.clock.set_fixed_time` 定钟点；WebSocket 收到 user.message 只回开头几段、不回 message.done = 流式中；`SHOTS_CHROMIUM=/usr/bin/chromium` 用系统浏览器，arm64 上 playwright 自带浏览器下载 403）。假数据项目补 status（与 App 截图同：进行中 / 等你回复 / 已完成）。
- 发现并修：**浅色白天壁纸下半屏发灰**（实测底部 #d0d9d8 / 网页 #d3d9d3，饱和度 0.11，灰绿）。原因：白天第三团柔光 blobC = #C0D4E2（冷蓝灰）落在底部（中心 y≈0.86、半径 0.46、混合 0.70），把暖米底色 #E6DCC2 盖掉；冷暖互补色相混 = 灰。决定：只改这一个色值为暖沙 #EBDBBF（两端同表：tokens.dart SkyTable.light.day.blobC、tokens.css --sky-day-c），不动画法、不删柔光；白天恢复“亮蓝 → 暖米”。改后底部 #e9ddc3 / 网页 #e6dcc3。对比度守门不变（浅色正文 12.37、次要字 4.63、最次要字 3.03）。
- 查过无问题：顶部渐隐条与整屏壁纸逐列逐像素相邻差 ≤1/255（无接缝）；毛玻璃（顶栏 / 输入胶囊 / 子页标题栏）无断层、错位；深色四个时段都是暗蓝紫，夜里最暗；正文 / 次要字两端都清楚；流式中两端都正常出字。
- 拿不准、没改（列给用户定）：见 HANDOFF 第〇节「v3.3 视觉验收」。

## 2026-10-16 后端偶发测试失败查根因（HANDOFF 第六节第 2 条；main 上改，未提交；只动 backend/）
- 决定（写代码前）：四个偶发都先复现、抓现场再改；不加大超时、不加重试。找到的根因三处在测试替身 / 测试等法，一处是产品代码（run.sh）真竞态，按根因修：
  1. **smoke_jobs §13（取消竞态，产品 bug）**：`start_job` 只是“叫沙盒脱离启动 run.sh”，返回时 run.sh 往往还没写出 pid；同一轮里马上 `cancel_job` → 沙盒 `_KILL` 读不到 pid 直接 `exit 0`（什么都没杀），任务照跑到底，卡片停在“运行中”。另一种：pid 写出了，但 `timeout` 还没来得及 `setpgid`，`kill -- -pid` 扑空。抓现场：失败那次 `CANCEL pidfile None`，替身 `wait(10)` 超时。修在 run.sh（backend/app/jobs.py `script()`）：`set -m` 让 bash 在 fork 后父子两边都 setpgid（`$!` 拿到时进程组就已存在）；pid 先写 pid.tmp 再 mv（读的一方不会读到半个）；写完 pid 再看一眼 `cancelled` 标记，有就自己整组杀。和 stop()“先写标记、再叫沙盒杀”构成两边各自“先写后读”：标记早于 pid → run.sh 自己杀；晚于 → 沙盒读得到 pid。替换：run.sh 原来的 `echo $! > pid`。成本：run.sh 多两行，零运行开销。
  2. **smoke_jobs 其他 pid/zombie 时序（测试等法）**：§5/§7 用 `sleep 0.3` 等 pid 文件、`sleep 0.2` 后 `killpg(pg, 0)` 判整组死没死；替身 job_alive 用 `kill(p, 0)`，对僵尸（已死、等父进程收尸）也返回“活着”。改为等条件：等 pid 文件出现；“组里没有非僵尸进程”才算死（读 /proc/<pid>/stat 的状态与 pgrp）。替身语义从“pid 还在进程表里”改为“进程还在跑”。
  3. **smoke_stop 5 秒等待超时 / smoke_reply_quote sqlite locked（测试替身没换全）**：这两个用 TestClient 的 WebSocket 跑轮次，每轮结束 ws.py 在后台起标题（conversation_title.schedule，create_task）；测试只换了 `loop.stream_turn`，起标题走真 `llm.complete` → 真去连 `http://x`（经沙盒代理，耗时不定）。ws 会话一退出，TestClient 的 portal 事件循环直接停掉，起标题任务正停在 SQLite 语句中间（抓现场：`maybe → db.get → _execute`），那条连接的读锁再也不放，下一段测试写库提交时要等 EXCLUSIVE，等满 SQLite 的 5 秒 busy timeout → smoke_stop 的 `wait_for(…, 5)` 先超时；smoke_reply_quote 用 `time.sleep(1.5)` 等标题写完，慢的时候没等到就去删消息 / alembic downgrade → locked。修：两个测试把 `llm.complete` 也换成假的（不出网），退出 ws 之前在同一个 portal 里 `conversation_title.drain()` 等后台标题收尾（删 `time.sleep(1.5)`）。产品代码没问题（服务端事件循环不会这样被掐掉；关机路径已有 drain）。
  4. **smoke_preview_ws 偶发（测试端口竞态）**：`free_port()` 绑 0 号端口拿到号就 close，再交给 uvicorn / websockets 去绑——并行跑时别的进程可能在中间抢走（之前记录过“端口占用失败”）；“端口上没人”那一项用的也是这种号，被别人占了就不再是“没人”。修：自己 bind 好 socket 直接交给服务（uvicorn `Server.run(sockets=[…])`、websockets `serve(sock=…)`），“没人”的端口用一个只 bind 不 listen 的 socket 占着（连上必被拒）。
- 参考：bash 手册 JOB CONTROL / `set -m`（异步命令各自成进程组；bash 源码 jobs.c make_child 在父子两边都 setpgid 以避免竞态）；GNU coreutils timeout.c（非 --foreground 时 setpgid(0,0)，信号转发给整组）；SQLite 文档 “File Locking And Concurrency In SQLite Version 3”（未结束的语句持有 SHARED，写方提交要等所有 SHARED 释放）与 busy_timeout；Starlette TestClient（websocket_connect 结束时 portal 退出、未等的后台任务被丢弃）；uvicorn `Server.run(sockets=)`、websockets `serve(sock=)` 文档。

## 2026-10-16 v3.3 视觉验收补：“我的”页顶部渐隐（App + Web；main 上改，未提交；只动 app/ frontend/）
- 问题（视觉验收第〇节“拿不准”第 3 条）：“我的”两端都没有顶部渐隐条，往下翻时内容直接切在屏幕顶边；App 上返回钮 / 名字会滚进状态栏底下和时间、电量叠在一起。原因：渐隐只挂在一级页面外框上（App ShellPage 的 BackdropFade、Web `.shell.has-bar` 的 SkyFade），“我的”没有顶栏，两边都没走到。
- 决定（替换不叠加，复用现有组件，不写新渐隐）：
  - App：me_screen.dart 用 `FloatingFooter(behind:)` 那一格放 ShellPage 同一个 `BackdropFade`（玻璃模式 = `SkyLayer(fade:)` 按屏幕坐标与整屏壁纸逐像素对齐；减少透明度 = 实色 bg 渐隐）。绘制顺序 = 壁纸 → 列表（含返回钮）→ 渐隐条 → 底部搜索胶囊：渐隐条只占屏幕顶部一截、和胶囊不重叠，胶囊仍是独立 BackdropFilter（“我的”不进 BlurGroup，原因见「v3.3 B3」规则②），取到的背景照旧是 壁纸 + 列表；返回钮也是独立模糊，先模糊自己身后、再被渐隐条盖，不受影响。没有新增离屏层（SkyLayer 自带 RepaintBoundary，是一层普通图层，不是 saveLayer / ShaderMask）。
  - 渐隐带：状态栏（MediaQuery.padding.top）以上全是壁纸 = 内容绝不进状态栏；再往下渐显 `Layout.topFadeRamp`（16，一级页面同一个 token），到页面静止时第一行（返回钮顶边）恰好全显，静止时页头一点不被盖（和一级页面“静止时第一行正好在全显处”同一规则）。为此“我的”PageBody 上留白 Sp.x2 → Layout.topFadeRamp（页头下移 8，返回钮顶边 = 状态栏 + 16，和 Web 的 状态栏 + 18 更接近）。先试过不动页头、渐隐带只有 8：截图上几乎还是一刀切，弃用。
  - Web：MeScreen 本来就用 `Page`，它已经挂了 `<SkyFade kind="page" />`，只是 `.shell:not(.has-bar) .sky-fade-page { display: none }` 把它藏了 → shell.css 给 `.page.me + .sky-fade-page` 放开并给“我的”的渐隐带：`--fade-a = env(safe-area-inset-top)`（刘海以上全是壁纸）、`--fade-b` = 页头返回钮静止时的顶边（.me .page-inner 上留白 + .me-head 上留白）。同一条遮罩曲线、同一个壁纸副本组件，没写新实现。
- 成本：App 多一个只有 ~70px 高的 SkyLayer 条（每 33ms 随壁纸重录这一条，和一级页面一样）；Web 多一条 SkyFade 副本合成（原来就在 DOM 里，只是 display:none）。
- 参考：同仓 v3.3 B3（BackdropFade / SkyFade 的语义与 BackdropGroup 规则）；Flutter `Stack` 绘制顺序 = children 顺序；MDN env(safe-area-inset-top)。

## 2026-10-16 v3.4 验证（发版前；HANDOFF 第二节第 10、18、20 条）
- 后端四个偶发：smoke_jobs / smoke_preview_ws / smoke_reply_quote / smoke_stop 各串行 20 次全过；四份并行各 10 次全过。
- run.sh 竞态在**真沙盒镜像**上复现与验证（用户 19:01 授权连 VPS）：assistant-sandbox:latest 临时容器，照 sandbox/runner.py 的启动（`setsid -f bash run.sh`）与取消（写 cancelled 标记 → 按 pid 整组 TERM）。三种时序各 15 次：①启动后立刻取消（pid 还没写）旧 0/15、新 15/15；②标记早于启动 旧 0/15、新 15/15；③启动 0.3 秒后取消 旧 15/15、新 15/15；新版无残留进程；正常任务退出码 3、日志正确。结论：旧版①②会让取消落空、任务跑到底，修复确为根因。
- smoke_stepfun：多个版本一直按“需真密钥”跳过，其实全是模拟（只设假 key）；跑起来发现断言过时（WS 事件自续传起多带 turn_id / seq，原来按整个 dict 比）。改为只比 type / text，纳入全量。教训：跳过的测试会悄悄烂掉，能跑的都要跑。
- 真模型 E2E：VPS 上用 app-backend 镜像临时容器跑本分支 `tests/live_stepfun.py`（密钥从服务器 .env 直接传进容器）：工具调用、带结果作答、记账、朗读→识别 4 项全过。
- 最终全量：flutter analyze 0；flutter test 735 过 / 9 跳过；npm run build、npm test 14/14；后端 smoke 203/203。
- 未做：真机 profile 光栅、真 GPU Chrome trace（沙盒与 VPS 都没有 GPU / 真机）。

## 2026-10-16 v3.5 Web ListRow 定“分体主体 / 正文附加槽”，收 RAW_ROWS（HANDOFF 第〇节“再往后”、第五节第 6 项 E1 剩余；先写决定再改）
**现状（动手前查的）**：check-arch RAW_ROWS 登记 12 个文件。其中分体行 6 处（技能、定时任务、MCP 服务器、收件箱、电脑页服务 / 后台任务）是同一个版式写了 4 遍：`div.row` 里一个整块按钮（`.skill-row` / `.task-row` / `.report-open` / `.computer-job-open`，四套几乎一样的 CSS）+ 行尾独立控件；其中前两个没有悬停底色、后两个有，自己就不一致。电脑页状态行 / 内存配额 / 磁盘配额 4 处是“标准行 + 正文下一条细条 + 一句警示”。App 早就是一套：kit.dart `ListRow(onTap:, trailing:)`，行尾开关 / 按钮在 InkWell 里但手势竞技场让控件自己赢，技能 / 任务 / 收件箱都用它。
**决定（替换不叠加，不新增组件）**
1. Web `ListRow`：可点的行（to / onClick）又给了 `control` 时，自动渲染成分体行 = `div.row.row-split` > 可点主体（`.row-main`：图标 + 正文 + 值 + trail/箭头）+ 行尾控件（主体之外，按钮不套按钮）。**不加新参数**：语义和 App `ListRow(onTap + trailing)` 一致。原来“可点行 + control”会把控件嵌进 button 里（非法嵌套），现在这条路径本身就修正了。aria-label 落在主体上。
2. Web `ListRow` 加 `extra`（正文附加槽）：放在副标题下面、仍在 `.row-body` 里（细条、警示句）。只这一个新参数。
3. CSS：`.skill-row` / `.task-row` / `.report-open` / `.computer-job-open` / `.computer-job` 及 `.report-row` 的内边距 / 悬停全部删掉，换成 `.row-split` / `.row-main` 一套（取原收件箱 / 电脑页那种：整行悬停底色、主体铺满可点）。有意的变化：技能、定时任务行也有了悬停底色（和其他可点行一致）；技能“已自定义”、MCP“带令牌”小字进了行尾 trail（间距 12→8px）。
4. 迁：技能、定时任务、MCP 服务器、收件箱、电脑页服务 / 后台任务（分体）；电脑页状态行 ×2、内存配额、磁盘配额（附加槽）。
5. 仍登记、不迁（版式不是“标准行 + 附加”）：内存 / 磁盘写入明细行（标题和大小同一基线的头行）、运行记录 / 助手备忘（顶对齐 + 状态点 + 多行错误）、最花钱的对话（细条跨整行换行）、今天时间线（行首是时间文字）、回复语言（常驻 aria-live）、文件选择（role=checkbox）。
6. App 不动：分体已经是 ListRow；App 6 个富内容行 v2.98 已逐个评估保留。
**成本**：纯前端重构，无接口变化；DOM 层级不变（原来也是 div > button + 控件）。验证：npm run build（check-arch 数只减不增）、npm test、截图对比（技能 / 定时任务 / 连接的账号 / 主页收件箱 / 电脑页，明暗 × 手机 / 桌面）、4× CPU 滚动帧。
**结果（实测）**：截图脚本加了电脑页（/#/projects/pr1/computer），main 基线与本分支各 138 张逐像素比。第一轮抓出回归：分体行默认右内边距沿用了收件箱的 sp-2，定时任务 / 技能 / 连接的账号行尾开关比原来往右贴了 8px → `.row-split` 默认改 sp-4（= App ListRow 水平 Sp.x4），只收件箱（⋯ 按钮自带点按留白）在 home.css 保留 sp-2。第二轮：技能 / 定时任务 / 连接的账号与 main 逐像素一致；电脑页服务 / 后台任务行尾按钮内收 8px（原 .computer-job 是 sp-2，现与其他行和 App 一致，有意）；主页收件箱区灰色小字 1 设备像素栅格差——DOM 量过两版每个盒子 top/height 到 0.1px 全同，属子像素取整，不改。DOM：主页 / 定时任务 / 技能 / 连接的账号 / 电脑 / 项目页按钮嵌按钮 0、分体主体都有可读名。4× CPU 无头 Chromium 手机视口来回滚动 240 帧：主页、定时任务、技能、电脑页新旧都 median 16.7ms、p95 16.8ms、>20ms 帧 0。tsc 0 错、架构守卫 222 文件、配色守门、npm test 14/14。

## 2026-10-16 v3.5 浅色夜间壁纸照 Hark 改“蓝 → 金”（HANDOFF 第二节第 21 条⑤，用户 19:41 补发 Hark 浅色截图；先写决定再改）
**现状**：浅色 night 时段 = 淡灰紫（top #c7d1f0 → bottom #d3d0dd，三团柔光也是灰紫），所以浅色晚上整屏发平。Hark 浅色 22:20 / 23:02 截图采样：顶 #3a6d99（钢蓝）→ #6093b6 → #9dbfce（浅青灰）→ #cad7cd → 底 #d8d4b3 / #e5c988（暖金米），晚上也不变暗、不变灰。
**约束**：配色守门要求壁纸任何一处 次要字 --text-2（#5c5852）≥ 4.5、--text-3 ≥ 3，等于壁纸每个采样点相对亮度 ≥ ≈0.62。Hark 顶部 #3a6d99 亮度 0.14（我们的次要字放上去只有 1.3:1，正文也只有 3.1），照搬会让区块标题 / 副标题在壁纸上看不清。
**决定**：取 Hark 的色相走向，亮度守在守门线以上（≈0.655），饱和度拉到这个亮度下能给的上限——只改浅色 night 一行 5 色，App SkyTable.light.night 同值：
top #b6d8f5（钢蓝，Hark 顶部色相）· bottom #e7d19f（暖金，Hark 22:20 底部色相）· a #bdd7ee（左上蓝）· b #c1d8e1（右中浅青灰，Hark 中段）· c #e3d3ac（底部米金）。
dawn / day / dusk、深色全套不动；插值关键帧不动（night ↔ dawn 过渡自然从蓝金过到现有黎明色）。
**成本**：只换常量，零运行时成本。验证：配色守门（全天采样）、App sky_test、截图浅色夜间（App + Web）。
**结果**：配色守门全天采样通过（浅色次要字最差仍 4.63、最次要字 3.03，最差点不在夜间）；npm test 14/14；App sky_test 19/19（沙盒跑 flutter test 要 NO_PROXY=127.0.0.1,localhost，否则测试监听的 websocket 走代理 404）。截图：Web `shots.py … sky` 浅色夜间 手机 / 桌面 × 主页 / 项目 / 聊天 / 我的；App app_shots_test 以 TZ=Etc/GMT-14（本地 02:00）出图，两端都是上钢蓝 → 中浅青灰 → 下暖金，和 Hark 22:20 / 23:02 走向一致，只是顶部浅（守门线）。

## 2026-10-16 v3.5 App 子页标题栏 → 悬浮玻璃胶囊（HANDOFF 第二节第 21 条①，照 Hark；先写决定再改）
**现状**：Web 子页 `.page-head` 早就是悬浮胶囊（离窗口上沿 topbar-top、左右 gutter、高 topbar-h、圆角 full、glass + chrome-edge 发丝边 + elev-float 投影 + 毛玻璃，sticky），滚上去的内容由 v3.4 的 SkyFade 渐隐带盖住。App `ui/sub_page.dart GlassAppBar` 还是贴边整条栏（状态栏 + 56 高、整宽毛玻璃、底部发丝线）。Hark 项目页标题也是导航下方一颗悬浮小胶囊，内容从胶囊四周露出来的地方被壁纸渐隐。
**决定（替换不叠加，只改 sub_page.dart，20 个 SubPage 调用方不动）**
1. `GlassAppBar` = 一颗悬浮胶囊：位置 / 尺寸照一级页顶栏（状态栏下 Layout.topBarTop、左右 Layout.gutter + 安全区、高 Layout.topBar），面 = 顶栏同一个 `GlassSurface(blur: true, radius: full)`（玻璃、chromeEdge、高光、floatShadow，减少透明度时实色）；里面还是 AppBar（primary: false、toolbarHeight = Layout.topBar，返回 / 标题 / actions 不变）。删掉整宽 BackdropFilter 和底部发丝线。
2. 让位：preferredSize = Layout.shellTop（= 一级页 inset，内容让位线两种页面同一条）。
3. 胶囊四周会露出滚上去的内容 → SubPage 在 body 上叠一条 `BackdropFade`（ShellPage 同参数：clear = 状态栏 + 胶囊中线，solid = 让位线 + topFadeRamp），不新建组件。
**成本**：毛玻璃面积从整宽 (状态栏+56)×屏宽 变成 52×(屏宽−48) 的胶囊，取背景仍是 BlurGroup 一次；新增一条和一级页同样的 SkyLayer 渐隐带（一级页已在用，帧测里 backdropLayers 不变）。验证：sub_page_test 改断言、全量 flutter test、App 截图（我的子页 / 项目聊天）、perf_frame_test。

## 2026-10-16 v3.5 浅色夜间第二版：调浓 + 次要字压深一档（用户 20:05“还行吧”、20:06“你想想吧，反正就是要有美感！”= 交给我定，以美感优先；HANDOFF 第二节第 22 条）
**问题**：第一版（fb3f9a6）色相对了但整体太淡：亮度被次要字 #5c5852 的 4.5 线卡在 ≥0.62，比 Hark（顶 0.14）淡得多；直接调浓的中段蓝 + 金在 sRGB 插值里混成橄榄灰，发脏。
**决定（两全，不放松守门）**
1. 浅色 --text-2 #5c5852 → #4a4640、--text-3 #7a746c → #605b54（两端同值）：壁纸可用亮度下限从 0.62 降到 ≈0.45。和正文 #111 的层级差从 2.66 变 2.02，截图看次要字仍明显次一级；在卡片上更清楚。
2. 浅色 night：top #8ebbe3（钢蓝，Hark 色相）· a #86bcea（左上更深的蓝团）· b #c6dfe8（右中一团发亮的浅青白——Hark 中段那片亮光，也负责把蓝金之间的橄榄灰冲掉）· c #efe4c4（底部正中奶油光）· bottom #dcc58a（暖金，四角）。
3. 流光（三团柔光漂移、按钟点插值）不动，只换常量。
**过程**：第二版先试 b #92bdd0 / c #e3c88a，和 Hark 并排看中段发灰绿 → 改成上面这组，中段变成发亮的浅青白、底部奶油光 + 金边，与 Hark 23:02 走向一致（Hark 顶部还更深，那是守门线以下，不取）。

## 2026-10-16 v3.5 “退出登录”整行条（两端）+ Web 项目列表去 ⋯（HANDOFF 第二节第 21 条②③）
**退出登录**：原两端都是居中小胶囊；Hark = 整行浅底圆角条、左图标 + 文字、无箭头、不进卡片组。
- 两端同一套：高 = 顶栏高（App Layout.topBar / Web --topbar-h，52）；底 = 次要胶囊按钮那层浅底（App tileFill / Web --tile）；圆角 full；左内边距 Sp.x4，图标落在上面列表行的图标线上；字 = 行标题字（App titleMedium / Web .row-title）。
- 不用 ListGroup + ListRow：那是白卡片组（Hark 明确不放卡片组里），且行高 64 + 组内边距让“我的”在 412×915 上多出 28px，超过一屏线（design_p3_test 918 > 915）；52 高的独立条正好守住。App 是 me_screen.dart `_LogoutBar`，Web 是 `.me-logout-bar`；按压反馈两端同为缩到 0.98（App 用 motion.dart Pressable——架构守卫不许 features 里手写 InkWell 行；Web :active）。App 仍先 confirmDanger，Web 原来就直接退（两端这点原本就不一致，没在这次改）。
- 顺手发现（没改）：App“我的”静止时，最底下的退出登录被底部“搜索设置”浮条盖住，要滚一下才露出来——design_p3_test 只量到屏幕底 915，没量到浮条上沿。旧胶囊同样如此，记进 HANDOFF 待办。
**Web 项目列表**：去掉行上 ⋯（它让状态行留了 32px 最小高、行 min-height 56）；菜单 = 右键 / 长按，弹原地聚焦菜单（ui/FocusMenu，和消息菜单同一套，= App 长按）。安卓 Chrome 长按、桌面右键、键盘菜单键 / Shift+F10 都发 contextmenu；iOS Safari 长按不发，用 500ms 触摸计时补，触发后吞掉随后那次点按；链接关掉系统长按预览和选字。同样 5 项操作项目内的项目名药丸里也有，功能没少。

## 2026-10-16 v3.5 子页标题照 Hark 子页（两端）

**依据**：用户 20:49 发 Hark 钱包 / 安全 / 系统偏好设置截图——子页没有标题栏、也没有胶囊：左边一颗独立圆玻璃返回钮（‹），标题居中裸字，说明文字和卡片直接接在下面。上一版（ef2bc21 前）照 Web 做成“整宽玻璃胶囊里放 返回 + 标题 + 动作”，不对。

**决定**
1. **替换不叠加**：两端删掉整宽胶囊（App `GlassAppBar` 里的 GlassSurface + AppBar；Web `.page-head` 的玻璃底、`.spacer`）。
2. 版式：[圆玻璃返回钮 = 一级页顶栏圆钮同尺寸] — 居中裸字标题（按整行居中，两侧再宽也不压字、放不下省略号）— [右侧动作收进一颗玻璃胶囊]（Hark 子页没有动作可参照，取顶栏同材质的胶囊，单个动作时接近圆钮）。位置 / 高度 = 一级页顶栏，让位线不变。
   - App：`NavigationToolbar`（centerMiddle）；返回钮规则照 AppBar：给了 leading 用它，否则 `impliesAppBarDismissal` 才出，点了 maybePop；标题 Semantics header。
   - Web：`grid 1fr auto 1fr`；返回钮 `.glass-btn.glass`；动作包 `.page-head-actions`。
3. 标题没有底了，滚上去的内容靠渐隐：App 本来就有 BackdropFade；Web 子页打开 `.sky-fade-page`（中线以上全是壁纸，到内容静止顶边全显），标题行 sticky z4 盖在渐隐条 z1 上。
4. 返回图标两端统一成 ‹（App `arrow_back_ios_new_rounded` = Web IconBack = Hark），“我的”页返回钮同换。
5. 测试：sub_page_test 改量“标题无玻璃底、整屏居中、动作胶囊贴右边距同高”，新增“能退的子页出圆钮、位置 = 顶栏圆钮、点了退回”；shell_test 的 `pageBack()`（只认 Material BackButton）改点“返回”。

**成本 / 帧**：App 每个子页取背景从 1 次（整宽胶囊）变成 ≤2 次（返回钮 + 动作胶囊，同一个 BackdropGroup 里合并取样）。Web 子页多一条渐隐条、玻璃面从 1 块变 ≤2 块小的；4× CPU 手机视口滚动（work/frames.py，每路由 400 帧，各跑 4 轮）：median 16ms、p95 18–20ms 新旧一样；>20ms 帧 子页（定时任务 + 记忆）合计 新 37 / 旧 15。拆因：关掉渐隐条 → 15（= 旧），关掉标题行毛玻璃 → 43（不是它）；isolation、will-change、把标题行挪出滚动区（= 顶栏结构）都不降。即多出来的就是渐隐条本身的成本，而同一轮里一级页主页 / 我的（本来就有这条，没改）>20ms 是每轮 4–11，子页现在每轮 2–12，落在同一水平。结论：标题没底就必须渐隐（否则滚上去的字和标题叠），这是全站已接受的同一种渐隐，保留；不另造一套。

## 2026-10-16 v3.5 底部浮条渐隐（两端，用户 21:35“会更好看就改”）
- 起因：App“我的”退出登录条静止时半截压在“搜索设置”浮条下，硬切。用户先同意不改，追问后说“会更好看就改”。只给“我的”页加会两端 / 各页不一致 → **统一做在 FloatingFooter 里**，所有底部浮条（主页 / 项目 LaunchComposer、聊天 Composer、“我的”搜索）一起有。
- 做法（替换不叠加，复用顶部渐隐的同一套）：
  - App：`Sky.fadeAlpha` / sky.frag 的 uFade 支持 solid < clear = 方向反过来（式子同一个，着色器改成显式 smoothstep 式，因为 GLSL smoothstep(edge0 > edge1) 无定义）；`SkyLayer(fadeLocal:)` 让条用本地 y（画时加条的屏幕位置）；`BackdropFade.bottom`；减少透明度时 `_SolidFadePainter` 色标按 y 升序排、两种方向通用。FloatingFooter 在内容和 behind（FrostScrim）之间放一条高 = 底条高 + `Layout.topFadeRamp`，solid = 条顶、clear = 底条上沿 + `Layout.bottomFadeClear`（= topBar / 2 ≈ 胶囊中线）。聊天列表底留白 `Sp.x2` → `Layout.topFadeRamp`（静止时最后一条不被淡，= 网页 .thread-inner 的 sp-4）。
  - Web：FloatingFooter 自己量高、在底条前渲染 `SkyFade kind="footer" height={h + 16}`；`.sky-fade.sky-fade-footer` 贴底 + 反向 mask（同 6 个色标）。SkyFade 的 ResizeObserver 加观察自身（底条长高时条的视口位置会变）。坑：`.sky-fade-footer` 单类名被 base.css `.sky-fade { top: 0 }` 压住，条跑到顶上 → 用双类名。
- 验证：flutter analyze 0、flutter test 736 过 / 9 跳过；Web tsc、npm test 14/14、架构守卫、build 过；截图 App（me / me-end / 聊天回到最新 / 主页暗色）+ Web 全套 phone/desktop × 明暗看过：卡片 / 退出登录 / 气泡滚到浮条处淡进壁纸，滑到底退出登录条完整露出。
- 帧耗时：App perf_frame_test 新旧交替各 2 轮，backdropLayers / shaderMaskLayers / fadeRebuilds 不变，每帧元素 +3（多一条），CPU 中位在噪声内（shell-scroll 新 13.2/11.1 vs 旧 10.6/9.5ms，me-scroll 4.9/3.0 vs 2.9/2.5，chat-stream 34.5/36.4 vs 36.8/33.7）。Web 4×CPU 手机视口新旧交替各 4 轮：median 16ms、p95 19–20ms 不变；>20ms 帧主页 47 vs 19、“我的” 36 vs 27（4 轮合计）——多一条动态壁纸副本 + mask 的成本，和 v3.5 子页渐隐条同类同量级。**未验证**：真机 Flutter profile、真 GPU 浏览器。

## 2026-10-16 v3.5.1 新建面板 = 主页“发起”态的新面板模式（两端，照 Hark；用户 22:48“你看看 hark 做的多好，你的好丑！”）
**依据**：Hark 点主页左上 + → 直接进整屏毛玻璃（顶部导航还在），底部是同一条输入胶囊、键盘弹出、左边收起钮；输入框上方一行淡色小字“创建一个新面板”；占位词在面板示例之间轮播；没有白底弹层、标题、“开始做”。
**决定（替换不叠加）**
1. 新建面板不再是一个弹层，而是主页 LaunchComposer 的一种“模式”（App `LaunchMode`，Web `LaunchMode` 同名同字段）：caption（上方小字）、hints（占位词轮播）、wrap（发出前把输入包成 newPanelPrompt）、extras（原来建议问题那一格换成本模式的胶囊）。+ 和栈底“创建一个新面板”宽胶囊都只做一件事：让输入胶囊进入新面板模式并聚焦；收起（收起钮 / 点遮罩 / 返回键 / Esc / 发出）= 回到普通主页、模式清掉。
2. 新面板模式的 extras（原弹层的全部功能，一个不少）：面板示例胶囊（点即交给新对话）、“每天早上的简报”（还没排时才出，点了 = 收起后打开预填的定时任务表单，同原来）、最近移除（30 天内，点 = 收起后放回，同原来；胶囊 = 恢复图标 + 名字 + 淡色移除时间）。材质 = 发起态现有的玻璃胶囊（App GlassChip 加可选 icon / detail，Web .launch-chips button），不再有白卡。
3. 占位词轮播 = 输入框的一部分（App Composer `hints` → motion.dart `CycleText`；Web Composer `hints` → 输入框上叠一层 aria-hidden 的文字），每 `Motion.hintCycle`（3.2 s）换一个：旧的上移淡出、新的从下淡入，只动 transform / opacity；减少动态 = 停在第一个不轮播；输入框有字时不显示。
4. **删除**：App new_panel.dart 里的 createPanel（showFormSheet 白底弹层 + 回调中转）；Web NewPanelSheet.tsx 整个文件、home.css 的 .panel-idea* / .removed-* 样式；对应测试改成测新模式。new_panel.dart 只留数据与 extras（newPanelPrompt / panelIdeas / briefIdeaLabel / NewPanelExtras / newPanelMode）。
**成本**：不新增常驻层。进入模式 = 原来聚焦时的那一层 FrostScrim（同一个模糊），胶囊比建议问题多一两行；轮播每 3.2 s 一次 240ms 的淡入上浮，只在聚焦且是新面板模式时有 Timer（失焦即停）。原来的弹层是一个路由 + 暗遮罩 + 一块毛玻璃弹层，现在少了路由和弹层。

**对照 Hark 原图收尾（2026-10-17，App）**：两张 Hark 截图（files/uploads/1000035709、1000035710）——小字居中、常规字重、比占位词小一档、离胶囊顶约 24；占位词前带一个图标（地图等），随句子一起换；胶囊左边没有“+ 添加附件”。照改：小字 labelMedium(12/500) → bodyMedium(14/400) text3、上下 Sp.x4（加 Composer 上边距 Sp.x2 ≈ 24）；`LaunchMode.hintIcons` → Composer `hintIcons` → CycleText `icons`（图标 Fs.lg、和字同色、同一个 key 一起换）；Composer `attach: false`（模式里不出添加附件，左边留 Sp.x4）。新测 test/new_panel_mode_test.dart（整个 App 搭起来）。**仍与 Hark 不同（有意 / 待定）**：①Hark 模式里只有小字、没有胶囊；我们保留示例 / 早间简报 / 最近移除胶囊（本节决定 2，原弹层功能不丢）；②Hark 左边圆钮是 ↺，我们是收起 ⌄（与普通发起态共用）；③~~Web 还没跟~~ 2026-10-17 已跟（见下）。

**Web 跟上（2026-10-17，同文案、同行为）**：删 `features/home/NewPanelSheet.tsx` 与 home.css `.panel-idea*` / `.removed-*`；新 `features/home/newPanel.tsx`（newPanelPrompt / panelIdeas / BRIEF_IDEA_LABEL / NEW_PANEL_CAPTION / 示例图标 IconSun·IconSwap·IconBag·IconDoc、简报 IconAlarm、最近移除 IconHistory / NewPanelExtras / newPanelMode）；`shell/LaunchComposer.tsx` 加 `LaunchMode`（同名同字段）+ `mode` / `onModeEnd`：设模式即在同一次点击里聚焦 textarea（useLayoutEffect，手机浏览器才弹键盘）、整页 frost-scrim；胶囊 onMouseDown preventDefault 不失焦；模式里不出“添加附件”、占位词带图标轮播、小字居中 14px 常规 text-3、离胶囊顶 24（sp-5）；发出 / 点示例 = wrap 成 newPanelPrompt；收起（收起钮 / 遮罩 / Esc / 失焦）= onModeEnd。`useAskInNewChat` 保留（PagesScreen 用）。`Composer.tsx` 加 hints / hintIcons / attach：textarea 外包 `.composer-field`，叠 aria-hidden 轮播层（textarea 用 aria-label 给读屏），有字时不渲染，换句 = 新节点 float-up；间隔 tokens.css `--hint-cycle: 3.2s`（= App Motion.hintCycle）；减少动态 = 不走表、停在第一句。HomeScreen 的 + 和栈底宽胶囊改成设模式（删 newPanel state 与弹层）。`.launch-chips` 错峰从 nth-child 三条改成读 `--i`（胶囊可多于 3 颗）。顺带：chat.css 一句注释里写了守卫关键字导致 check-arch 在 HEAD 上就不过，改成“背景模糊”字样。
**Web 验证**：tsc -b 过；npm test 14/14；npm run build（check-arch + 配色守门 + vite）过。scripts/shots.py 的 sheet-panel 截图改为点顶栏 + 后截 `*-new-panel.png`（手机 / 桌面 × 明 / 暗），已逐张看：整页磨砂、示例胶囊带图标 + 早间简报、“创建一个新面板”居中淡灰、离胶囊顶约 26px、胶囊左侧无回形针、占位词“☀ 明天的天气”带图标，与 Hark 1000035709 一致（差异同上 ①②）。**未验证**：假数据里没有已移除面板，“最近移除”胶囊没出图；轮播动起来的样子、真机键盘弹出只看了代码没录屏；Web 帧耗时未测（只多一个 3.2s 一次的 240ms float-up，无新增模糊层）。

## 2026-10-17 v3.5.1 App 弹层全屏（= Web 43366c7；HANDOFF 第二节 24：“别留那个半屏的”“丑爆了”）
**归属**：弹层只有 `ui/sheets.dart` 一个入口（架构守卫 test/sheet_test.dart），所以在这一层整体换掉，调用处只多传一个 `title:`（标题从内容里搬到顶上居中）。
**替换了什么（删）**：`GlassSheet`（glass.dart：顶部圆角玻璃卡 + 真模糊 + 把手）、`showModalBottomSheet` 两处、`showAppScrollSheet` 的 85% 封顶与 AnimatedSize、`Glass.grabber` token、app_theme 的 `bottomSheetTheme`；旧测试“玻璃框 / 把手 / 85% 封顶 / 附件弹层只有一排高”改成全屏的新断言。不留两套。
**新版式（`SheetPage`，sheets.dart）**
1. 路由：根导航器上的 `PageRouteBuilder(opaque, fullscreenDialog)`，只淡入（FadeTransition，减少动态 = 直接出现），不上移；淡入完成后 Navigator 不再绘制下面的路由（= Web `:root[data-sheet] .shell` 隐藏），fullscreenDialog 让下面的 Material 页不做退场动画。
2. 一页 = `Backdrop`（同一张流光壁纸，减少透明度 = 实色 bg）+ `GlassAppBar`（子页同款：左上圆钮 ‹ + 居中裸字标题；钮 tooltip “关闭”= Web aria-label）+ 内容区 + 可选钉底 footer。
3. `showAppSheet` / `showActionSheet`：内容整页滚（SingleChildScrollView），视口从标题行中线起；`showFormSheet`：字段整页滚，提交钮钉在屏幕底（footer，整行宽）；`showAppScrollSheet`：固定部分 + `SheetList` 占满剩下高度在里面滚。
4. 渐隐（全部复用 `BackdropFade` 的 SkyLayer 着色器，不新增组件）：上沿 clear = 标题行中线、solid = 标题行下沿 + Sp.x5（= Web .sky-fade-sheet 的 fade-a / fade-b）；下沿淡成壁纸（无按钮行时让出手势条，有按钮行时淡在按钮行上面）；`SheetList` 上沿一条 topFadeRamp（列表在固定说明下面滚，不切硬边）。`BackdropFade.bottom` 改名 `BackdropFade.local`（本地坐标，两个方向都用；FloatingFooter 同步改）。
5. 安全区 / 键盘由 SheetPage 统一给（内容区贴键盘），内容里的 SafeArea / viewInsets 留白自动归零，调用处不用改。
6. 平板 / 宽屏：弹层以前没有自适应断点（Material 底部弹层），这里也不加——全屏，内容按 `Layout.contentMax` 居中（= Web --content-w，和子页一致）。Web 桌面（≥861）仍是居中玻璃卡；App 平板要不要也做居中卡，留给用户 / Hark 截图定。
7. 居中确认框（showAppDialog / confirmDanger）不动。
**成本**：没有 BackdropFilter（返回钮 `GlassIconButton(blur: false)`——底下只有壁纸，模糊白花一次取背景），没有离屏层；一张 Backdrop + 2–3 条渐隐条（同一个着色器、各自是重绘边界）。旧半屏卡每次打开 1 次整卡模糊取样 + 页面在底下照常绘制，新版淡入后底下不绘制，判断不会更重；真机光栅耗时未测。
**调用处**：标题搬到 `title:`（分享对话、哪里不好、装过的工具、头像颜色、MCP 工具、OAuth 配置、个人资料、两步验证、恢复码、添加付款卡、存到哪里、任务记忆、本对话全部文件 / 用量、项目文件 / 引用文件、选择文字）；标题行带按钮的（打包下载、用量里的文件 / 分享钮、已选 N、上传、复制全部）按钮留在内容第一行右侧；完整日志 / 完整输出加顶上标题，任务信息块不动。
**测试**：sheet_test 新断言（铺满整屏、落在 Backdrop 上、无 BackdropFilter、下面页面不绘制、标题按整屏居中、提交钮离底 Sp.x5 且整行宽、只淡入不上移、返回钮 = 取消、长列表占满到屏幕底且最后一行停在下沿渐隐之上）；project_file_refs / script_task 用返回钮关弹层；job_block / adaptive 按“下面的页面 offstage”改；conversation_files 标题不在内容里。shell_test“历史抽屉点遮罩关”在 HEAD 上就已失败（FullDrawer 铺满后没有露出的遮罩），改成往左滑关。
**截图**：test/shots/app_shots_test.dart 新增 `sheets light/dark`（新面板表单 + 外观动作单），输出 sheet-{form,actions}-{light,dark}.png，四张都看过。

## 2026-10-17 v3.5.1 “我的” = 第四个分支（App；HANDOFF 第二节第 26 条，照 Hark 截图）
- 依据：用户 22:48–22:49“切到个人页的时候，主页聊天和项目都还在…点击他做了一个从左往右滑的特效，就相当于切过去了”“把那个返回键给删掉 个人页面那个”；Hark 截图：导航胶囊三项都不选中、右上头像为当前项、无返回钮、无左上按钮。
- 归属 / 替换：
  1. 路由：/me（连同全部二级子页）从“盖在外壳上的根路由”移进 StatefulShellRoute 第四个分支；`shellRoots` 加 '/me'，`shellBarShown` 因此在“我的”显示顶栏、在 /me/… 子页照旧淡出（子页 SubPage 样式和返回钮不动）。
  2. 外框：MeScreen 换成和其他一级页同一个 ShellPage——**删** MeScreen 自带的 Backdrop、`me-fade` 渐隐条、页头返回钮 / “回到主页”×，不留两套；页头上留白仍是 topFadeRamp（静止时在全显线上）。
  3. 顶栏：不新增组件。SegmentedNav 变 Stateful 只为记住滑块上次位置：index 不在分段里时滑块原位淡出（AnimatedOpacity），回来时原位淡入再滑走；头像外加一道 pillOn 色环（= 选中滑块颜色）淡入，读屏 selected。
  4. 切换动效：`StatefulShellRoute(navigatorContainerBuilder: ShellBranches)` 替换 `.indexedStack`。ShellBranches = go_router 自带容器的同一结构（每分支 Offstage + TickerMode 常驻），多一个 360ms easeOutCubic 控制器：只有一端是“我的”时，进场页从 ±1 屏宽滑到 0、离场页从 0 滑到 ∓1（FractionalTranslation，只动 transform）；滑完离场页下台；三个分段之间、减少动态、滑到一半又切走都直接到位。参考：go_router 官方示例 example/lib/others/custom_stateful_shell_route.dart（BSD-3，自定义 navigatorContainerBuilder 做分支切换动画）的思路，代码按本项目 token 自写、未移植。
  5. 返回键：“我的”PopScope 不可弹，搜着先清空，否则 `StatefulNavigationShell.maybeOf(context).goBranch(0)`（主页导航栈原样恢复）。
  6. 其他入口：头像 = goBranch(3)（已在“我的”再点 = 回到“我的”栈底，和分段一致）；主页卡片 / 面板 / 聊天块里的 `context.push('/me/…')` 实测 go_router 18 跨分支 push 照旧叠在当前页上、返回回原处，保留不改（action_card 只更新注释）。
- 成本 / 帧（perf_frame_test，同机先后跑）：“我的”滚动 每帧重建元素 2→0、重画 8→4、CPU 中位 1.31→1.14ms；backdropLayers 1→2、取背景 1→2 次（多的是常驻顶栏那一组，和主页 / 项目同为 ≤2，新加断言守住）；shaderMask 0、渐隐条滚动重建 0。横滑期间两页同时在台上、各自 transform，不触发布局。
- 版面代价（未解决，记 HANDOFF）：顶栏常驻后内容多让出 72px，412×915 上“关于”与“退出登录”要滚一小段才露出（原 design_p3_test“退出登录不用滚就看得到”改为“第一组 + 第二组前两行露在搜索胶囊上方”）。不删行、不改行高就收不回；要不要把行高 64 / 用量卡 98 往 Hark 的 61 / 83 收另议。
- 未验证：真机横滑手感与 GPU 帧；Web 未改（不在这次范围）。

## 2026-10-17 v3.5.1 “我的” = 第四个标签（Web；照 App 3c00b9f，HANDOFF 第二节第 26 条）
- 归属 / 替换（和 App 一一对应，不新增组件）：
  1. 顶栏：`TopBar.tsx isShellRoot` 加 '/me'（= App `shellRoots` 加 '/me'），“我的”显示顶栏、/me/… 子页照旧没有顶栏（子页 `.page-head` 和返回钮不动）。分段导航在“我的”时三项都不选中：滑块 `.segments-thumb` 停在上一次的位置（模块级记住，子页回来顶栏重新挂载也不跳）原位淡出（opacity），回到分段时原位淡入再滑走；头像外圈淡入一道 `--pill-on`（= 滑块色）2px 环（`.avatar-tab::after`，opacity 过渡），头像按钮 `aria-current="page"`。
  2. 外框：MeScreen 改用一级页同一套 `.shell.has-bar` 结构（--inset-top 让出顶栏、`.sky-fade-page` 同一条渐隐）。**删**：页头返回钮 / “回到主页”×、`.me .page-inner` 自己的上留白、shell.css 里“我的”专用渐隐带、`.me-top` 死样式。页头上留白回到一级页的 sp-4（静止时在全显线上）。
  3. 切换动效：AppShell 里 `ShellViews`（= App `ShellBranches`）：路由仍是一个 Outlet；只有一端是“我的”、另一端是带顶栏的一级页时，把离场页的元素（`useOutlet()`，连同当时的 location，用 `UNSAFE_LocationContext` 冻住，滑出途中不按新地址重算）多留 360ms：进场层从 ±100% 滑到 0、离场层从 0 滑到 ∓100%（`--dur-slow` / `--ease` = App Motion.slow / ease），滑完离场层卸载。只动 transform；主页 / 聊天 / 项目之间、子页进出、reduce-motion、滑到一半又切走都直接切。层的 key 只在横滑时变，其余导航（如项目 A → 项目 B）组件照旧复用不重挂。
  4. 渐隐条壁纸副本跟着层一起平移会和真壁纸错开 → 滑动期间副本里的 `.sky` 反向同曲线平移（`.sky-fade > .sky` 同一个 keyframes 取负），和全屏壁纸逐像素重合；SkyFade 的定位改用布局位置（offsetLeft/Top 链），不受进场层初始 transform 影响（原 getBoundingClientRect 会把 +100% 记进去，滑完错一屏）。
  5. 其他入口：头像 `nav("/me")`；首页卡片 / 聊天块里直接 `Link to="/me/…"` 进子页，照旧。
- 和 App 的差别（已知、不改）：Web 一级页左上按钮是 portal 进顶栏的（ShellLead），横滑时不随页面滑，跟着页面挂载 / 卸载出现消失；App 是 ShellPage 画的、随页滑。
- 顺手修：`features/chat/chat.css` 注释里写了 backdrop-filter 字样，架构守卫拦住 `npm run build`（HEAD 已坏），改成“背景模糊”。
- 验证：`tsc -b`、`npm test` 14/14、`npm run build`（架构守卫 222 文件 + 配色守门）过。Playwright 走查（work/me_slide_check.py，手机视口）：主页点头像 → 中途 2 层（离场 / 进场各自的渐隐条一左一右）、结束 1 层，`--sky-x` 都是 0；“我的”分段 0 个选中、滑块 `.off`、头像环亮、`aria-current=page`、无返回钮；进 /me/tasks 无顶栏、不滑；返回 /me 滑块仍 off；点“聊天”反向滑；聊天 → 项目直接切；reduce-motion 全程 1 层直接切；控制台 0 错误。`shots.py` 全量 140 张，看了 phone-light/dark-me、desktop-light-me、偏好子页：版式与 Hark 个人页一致（导航胶囊悬浮、三项不选中、头像为当前项、无左上钮、页头直接接内容）。
- 帧耗时（4× CPU、手机视口，同机新旧 dist 交替各 3 轮，机器空闲时）：“我的”滚动 median 16 / p95 19–20 新旧相同，>20ms 帧 旧 14/14/16 = 44、新 7/14/6 = 27（多了常驻顶栏一块玻璃，没变差）。横滑期间（work/slide_frames.py：主页 ↔ 我的 各 4 次、点击后 500ms 的 rAF 间隔，含新页挂载）：>20ms 帧 旧（直接切）41 / 50、新 56 / 60，max 两边都是挂载那一帧 165–222ms；即每次切换多 1–2 个慢帧（两页同时合成），挂载本身的长帧新旧一样。**未验证**：真 GPU / 真机手感。

## 2026-10-17 v3.5.1 卡片 = 半透明灰白“假玻璃”（两端同 token；HANDOFF 第二节第 27 条）
- 依据：用户要求卡片“不要纯白”，参考 Hark：带壁纸透色的半透明冷灰 / 暖灰玻璃。
- 取样（Hark 截图，卡内像素 vs 紧邻卡外壁纸，多行拟合 卡 = α·C + (1−α)·壁纸，逐通道最小二乘）：
  - 浅色“我的”列表卡 1000035715：α ≈ 0.67（R/G/B 0.67/0.67/0.66），C ≈ #FFFFFF（256.9/256.2/258.0 → 纯白）；例：壁纸 (61,106,142) 处卡 (193,209,222)，(230,227,195) 处卡 (247,246,236)——同一张卡蓝天上冷灰、暖底上暖灰，就是透色来的。
  - 浅色主页卡 1000035707：α ≈ 0.73–0.85、C ≈ (242,239,234)（含卡内小块，噪声大，取“我的”那组为准）。
  - 深色主页卡 1000035677：α ≈ 0.56（0.56/0.59/0.54），C ≈ #181818；深色“我的”列表卡 1000035675：α ≈ 0.70、C ≈ 近黑 (2,2,3)。
  - Hark 卡后面有真模糊，我们不加（用户定：只用半透明色，不新增 BackdropFilter / backdrop-filter）。
- 决定（单一来源：App `Palette.card` = 网页 `--card`，两端逐字节同值，check-contrast.mjs 查含透明度）：
  - 浅色 `Color(0xA8F8F9FA)` = `rgba(248, 249, 250, 0.66)`：Hark 白 67%，白里压一点冷灰（“偏灰”），透明度取 0.66。
  - 深色 `Color(0x9E16171C)` = `rgba(22, 23, 28, 0.62)`：Hark 两处 0.56 / 0.70 的中间，色取 #181818 偏一点冷（和炭灰 surface #1E2029 同族）。
  - 减少透明度：卡片回到实色 `surface`（App `cardFill` / GlassSurface 的 solid 分支；网页 `:root[data-solid] { --card: var(--surface) }`）。
- 归属 / 替换（不叠加）：
  - App：卡片本来就只有两个入口——`GlassSurface` 不模糊分支（GlassCard / ListGroup / 长按菜单 / 登录表单）和 `context.cardFill`（AppCard / BlockFrame / 项目表单选中块）。两处的 `p.surface` 换成 `p.card`，页面一行不用改。主页面板卡、今天卡、“我的”列表组与用量卡、聊天里的块、子页卡全部跟着变。
  - Web：`--card` 原是 `var(--surface)` 的别名，改成上面的 rgba；`.stack-card` / `.list` / `.card` / `.blk` / `.task-head` / 聊天回复卡 / `.focus-menu` 都已经读 `--card`。另：聊天空态建议卡 `.suggestion` 原用浮层的 `--glass`，改读 `--card`（它是卡不是浮层）；浏览器全屏接管页 `.takeover` 原借用 `--card` 当整屏底，改 `var(--surface)`（整屏不能透，保持原样）。
  - 跟着调：浅色 danger #C43D3D → #B23434、warning #9A5B00 → #915500。卡变半透明后，夜间钢蓝天透上来，卡上的出错 / 警示小字最差只有 3.96 / 4.17，压深一档到 4.71 / 4.61（两端同值）。
- 守门（替换原“字对实色 surface”只查一个色）：App test/sky_test.dart 的壁纸对比度组加“卡（card 叠在壁纸上）”一档，网页 check-contrast.mjs 同一采样（全天每 15 分钟 × 底色 11 高度 × 三团柔光峰值，再叠 card）：浅色 正文 14.53 / 次要字 7.21 / 最次要字 5.18 / 警示 4.61 / 出错 4.71；深色 15.66 / 6.28 / 4.14 / 6.92 / 4.80。原“字/卡”实色配对保留（减少透明度时仍是实色卡）。
- 成本：只换填充色，不加图层、不加模糊。perf_frame_test 结构计数（backdropLayers / flips / shaderMask / 每帧重建 / 重画）新旧完全一样；CPU 中位同机先后跑 新/旧 chat-stream 22.1/23.0、shell-scroll 7.5/8.5、me-scroll 1.5/2.2、home 3.1/3.8、projects 2.9/3.3 ms（噪声内）。Web 只改变量值，无新合成层。
- 截图：App /workspace/work/card-shots/app（home / me 明暗等 14 张），Web /workspace/work/card-shots/web（shots.py 全量 138 张）；和 Hark 1000035715 / 1000035707 / 1000035675 / 1000035677 并排看：浅色卡在蓝天处冷灰白、暖金底处暖灰白，深色卡是比壁纸暗一档的透明炭灰。**未验证**：真机 GPU、真浏览器。

## 2026-10-18 v3.5.1 浮层玻璃透出壁纸（两端同 token；HANDOFF 第二节第 27 条）
- 依据：用户反馈卡片改了之后，“我的”底部搜索框、顶部导航胶囊、主页输入胶囊、圆钮这些浮层仍近乎纯白（原 `glass` 浅 85% 白 / 深 #1B1D25 88%），不好看；Hark 的浮层明显透出壁纸。
- 取样（Hark 截图，浮层内像素 vs 紧邻浮层外上下两侧壁纸的均值，拟合 浮层 = α·C + (1−α)·壁纸；浮层下面是真模糊，壁纸平滑，按未模糊的邻近壁纸算）：
  - 浅色（C 取纯白，逐通道 α）：“我的”1000035715 顶部导航胶囊 壁纸 (58,110,154) → 胶囊 (148,179,203)，α ≈ 0.46/0.48/0.49；右段 (46,95,136) → (142,171,192)，α ≈ 0.46/0.48/0.47。“我的”底部搜索框 暖底 (231,223,185) → (239,235,211)，α ≈ 0.33/0.38/0.37；(213,203,163) → (227,223,198) α ≈ 0.33/0.39/0.38。主页 1000035707 顶部胶囊 (57,106,145) → (157,183,203) α ≈ 0.51/0.52/0.53；左上圆钮 (60,111,152) → (156,185,205) α ≈ 0.49/0.51/0.51；底部输入胶囊 (212,198,153) → (237,231,213) α ≈ 0.58/0.58/0.59。→ 浅色浮层 ≈ 白 37–58%，主要几处在 0.47–0.58。
  - 深色（壁纸上下有落差，C、α 一起解）：主页 1000035677 顶部胶囊 壁纸 (18,23,45) → (24,25,35)，底部输入胶囊 壁纸 (50,53,74) → (31,32,40)：α ≈ 0.78/0.77/0.83、C ≈ (26,26,33)；“我的”1000035675 胶囊 (25,26,36) / 搜索框 (35,36,47)：α ≈ 0.69/0.67/0.62、C ≈ (28,28,31)。→ 深色浮层 ≈ (27,27,32) 62–83%，均值 ≈ 0.72。
- 决定（单一来源：App `Palette.glass` = 网页 `--glass`，两端逐字节同值，check-contrast.mjs 查含透明度）：
  - 浅色 `Color(0x80FFFFFF)` = `rgba(255, 255, 255, 0.5)`：Hark 浅色浮层主要几处 0.47–0.58 的中间。
  - 深色 `Color(0xC21B1C21)` = `rgba(27, 28, 33, 0.76)`：色取拟合的 (27,27,32) 略偏冷；透明度没取均值 0.72，取 0.76（仍在 Hark 0.62–0.83 内），因为 0.72 在“浮层叠卡上墨色一半”那档次要字只有 4.41、最次要字 2.91，0.76 刚好守住（见下）。
  - 减少透明度：照旧回实色（App GlassSurface solid 分支 = surface；网页 `:root[data-solid] { --glass: var(--surface) }`）。
- 归属 / 替换（不叠加、不新增模糊层）：
  - App：`p.glass` 只有一个读处——GlassSurface 的 blur 分支（顶栏胶囊、圆钮 GlassIconButton、输入胶囊、“我的”搜索框、子页圆钮 / 动作胶囊、聊天回到最新 / 标题胶囊、项目切换、浏览器接管条、收件箱条），下面本来就有 BackdropFilter，只改 token 值。
  - Web：`.glass`（带 backdrop-filter）、`.page-head-actions`、`.me-search .search-field.glass` 读 `--glass`，只改值。顺手对齐 App：三处不模糊却读 `--glass` 的（`.wide-pill`“创建一个新面板”、`.glass-chip` 思考跳点、`.panel-idea` 新面板起点胶囊）改读 `--card` / `--card-edge`——App 对应的 WidePill / 思考胶囊 / GlassChip 本来就是不模糊的 GlassSurface = `Palette.card`；不改的话它们会变成 50% 白、比卡还透，且没有模糊。
  - `glassSheet` / `--glass-sheet` 检查过：仍在用（App GlassSheet / GlassDialog = showAppSheet / showAppScrollSheet / showAppDialog / confirmDanger 共 61 处调用；网页 `.sheet`、`.dialog`、`.menu-pop`、`.glass.raised`、附件角标），弹层全屏化只改了项目切换 / 聊天历史那类抽屉，表单弹层、对话框、菜单还在，不删。
  - 未改：几处用 `var(--glass)` 当“挖空环”色的（`.swatch.on`、`.hue-hole`、未读点 / 角标的 2px 边、骨架屏渐变、`.pill.primary:hover` 混色）跟着变淡，看过截图不突兀，不单独处理。
- 守门（两端同一模型）：浮层上的字（导航字 text2、占位符 text3、图标 / 输入字 text）按浮层下面最差的三种算——直接是壁纸、卡叠壁纸、卡叠壁纸再被墨色 ink（浅黑 / 深白：主按钮、字）盖住一半（σ24 模糊后一颗 48px 高实心按钮中线 ≈ 一半）；全天每 15 分钟 × 底色 11 高度 × 三团柔光。App test/sky_test.dart 加“浮层·壁纸 / 浮层·卡 / 浮层·卡上墨色一半”三档，网页 check-contrast.mjs 第 5 条（并查 --glass = App glass）。结果（最差）：浅色 正文 9.96 / 次要字 4.94 / 最次要字 3.55；深色 11.69 / 4.69 / 3.09。临时把深色改回 0.6 守门即报错（次要字 3.50、最次要字 2.31），确认生效。
- 验证：flutter analyze 0；flutter test 全量 768 过 / 9 跳过；Web tsc -b、npm test 14/14、npm run build（架构守卫 222 文件 + 配色守门）过。
- 成本：只换填充色，不加图层、不加模糊；perf 结构计数不变（未单独重跑帧耗时）。
- 截图：App /workspace/work/glass-shots/app（14 张），拼图 /workspace/work/glass-shots/app-montage.png（主页 / 我的 × 明暗），和 Hark 并排 /workspace/work/glass-shots/app-vs-hark.png；Web /workspace/work/glass-shots/web（shots.py 全量 138 张）。浅色导航胶囊在蓝天上是透出来的浅蓝灰、“我的”搜索框在暖底上是奶油色；深色浮层是比卡略亮一档的透明炭灰。我们的浅色壁纸本身比 Hark 淡（夜间顶 #8ebbe3 vs Hark #3a6d99），同样 50% 白看起来比 Hark 的 (149,180,205) 浅，这是壁纸差异不是玻璃。**未验证**：真机 GPU 模糊下的观感。

## 2026-10-18 v3.5.1 电脑页 / 用量页精简（两端；HANDOFF 第二节第 28 条，用户 00:24 / 00:27“太长了”“卡顿”“优化，再优化”）
- 决定：子页首屏约一屏讲完概况，长列表露前 3 + “全部 ›”进子页，同一信息只出现一次；轮询只重建数值变了的行，滚动不重建。替换：电脑页原来所有分节平铺一页 → 一屏概览 + 明细子页（App computer_screen / computer_section，Web 同构 a0bcfdc）；用量页多张卡 → 一张概览卡 + 前 3（App dbaeb72，Web 31621d3）。不删信息，明细都还在子页里。
- 测量（App perf_frame_test，412×915，test/support/computer_usage_fixture.dart 同一份假数据，改前 → 改后）：电脑页 maxScroll 3522 → 94；滚动时每帧重建 max 189 → 15；一次轮询重建 677 → 59；opacity 层 33 → 12。
- 配套（d8c08d6 / d8a2d73）：
  - PullRefresh 只在滚动位置在顶部时收滚动通知，中段滚动不再每帧走下拉刷新逻辑。
  - `SettleOpacity`（app/lib/ui/motion.dart）：淡入到 1 后不留 OpacityLayer；懒构建后补出来的行直接终态，不再逐个淡入。
  - 采集进程过滤：sandbox/runner.py `parse_ps` 滤掉采集命令自己的进程，后台任务列表不再出现采集本身（backend/tests/smoke_computer_extras.py 加断言）。
- 验证：flutter test 全量 787 过 / 11 跳过；Web 全过。**未验证**：真机滚动手感与光栅耗时。

## 2026-10-18 v3.5.1 五色流光（两端；HANDOFF 第二节第 28 条“流光照 Hark”）
- 决定：流光改成肉眼明显流动的多色柔光：白天在蓝 / 淡紫 / 蜜桃珊瑚 / 薄荷 / 暖金五色之间按时间轮转，5 团高斯柔光叠出层次。替换：原三团柔光 + CSS 渐变 → App 单片元着色器（app/shaders/sky.frag、ui/sky.dart），Web WebGL（frontend/src/lib/skyGl.ts，删 base.css 里原渐变动画），两端同一核心算法、同一色表（App tokens.dart = Web tokens.css / sky.ts）。减少动态只随时间换色不流动、减少透明度纯色，照旧。对比度守门（sky_test.dart / check-contrast.mjs）按新壁纸采样重跑并通过。
- 测量：Web 无头 Chromium 4× CPU，>20ms 帧 /#/ 334 → 约 150，/#/me 约 318 → 40（WebGL 替掉 CSS 渐变后反而更省）；App 沙盒软件光栅每帧 28 → 37ms（软件光栅跑片元着色器的成本，不代表真机 GPU）。
- **未验证**：真机 GPU 上流光的光栅耗时、真 GPU Chrome trace。

## 2026-10-18 v3.5.2 真机卡顿（App，魅族 20；HANDOFF 第二节第 30 条）+ 项目 = 目录（两端，第二节第 29 条）
- 背景：用户真机（魅族 20，骁龙 8 Gen 2，120/144Hz）反馈 App 滑动卡，同机 Hark 不卡 → 是我们软件的问题。诊断全文 /workspace/work/jank-diagnosis.md。
- 诊断：
  1. 没请求高刷新率：Flutter 只跟系统给的 vsync，Flyme 等系统对没声明的第三方 App 默认给 60Hz → 被锁 60Hz。
  2. Impeller 没有 raster cache、Android 上无局部重绘：RepaintBoundary 只省 UI 线程，滑动时每个 vsync 整棵 display list 重放，整屏壁纸片元着色器（sky.frag）每帧重跑，不是每 33ms 一次。
  3. 外壳壁纸在子页下白画：SkyCover 只停时钟，被不透明子页完全盖住时照样每帧整屏跑着色器。
- 修复：
  - 高刷新率（331b395）：MainActivity.kt 在同分辨率模式里挑刷新率最高的设 window preferredDisplayModeId（API 23+，onCreate / onResume 各一次，失败保持系统默认）。
  - 壁纸 1/4 离屏贴图（d0ad7f5）：SkyFrames 每个时钟步在物理像素 1/4×1/4 离屏跑一次 sky.frag（Picture.toImageSync），整屏与渐隐条用新 shaders/sky_blit.frag 双线性放大 + 屏幕像素抖动；时钟没走就复用同一张图；滑动时暂停 SkyClock。贴图着色器加载失败回退整屏直画。
  - 盖住不画（331b395）：SkipWhenCovered（app_shell.dart）在 SkyCoverScope 计数 > 0 时整个外壳壁纸子树不 paint（不重建、不改布局）。
  - PulseDot 改 33ms Timer 步进（不再每 vsync 一帧）；隐藏性能浮层（core/perf_overlay.dart，关于页进入）供真机看 UI / Raster。
  - 项目 = 目录（83869bf App / dcde221 Web）：删项目切换胶囊，目录 + 左上 ☰ 回目录。
- 测量：沙盒软件光栅每帧 39–44ms → 约 12ms（perf_frame_test / sky_frames_test）。
- **未验证**：真机是否真跑到 120/144Hz、真机 GPU 光栅耗时与滑动手感——按第二节 30 条必须真机确认。

## 2026-10-18 v3.5.3 性能自检
- 3.5.2 用户截图“我的”页 Raster avg 15.8 / max 17.1ms、UI 0.4ms（光栅是瓶颈），故加 A–H 分层性能自检（关于页开性能浮层后“性能自检 ›”）在真机逐层测光栅；等用户真机结果再定修哪层。

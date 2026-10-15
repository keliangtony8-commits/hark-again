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

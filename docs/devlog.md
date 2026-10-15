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

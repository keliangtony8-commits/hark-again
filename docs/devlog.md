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

# Toyuis 交接文档（2026-10-14，v2.90.1）

> 写给接手的 AI / 开发者。先通读本文件，再读 `docs/devlog.md` 末尾、`docs/home-redesign.md`、`CHANGELOG.md`。

## 一、项目是什么
- 用户是预算有限的学生，自建个人 AI 助手 **Toyuis**（产品名，记住），目标：对齐 Hark / Muse / Dots / Cue 这类消费级助手的**公开**功能与体验。
- 架构：FastAPI 后端 + 自写 agent 循环 + LiteLLM + Postgres/pgvector + Playwright 浏览器/沙盒 worker；Flutter App（Android 优先，主客户端）；React Web（电脑端）。
- 仓库：GitHub `keliangtony8-commits/hark-again`（私有），本目录即仓库根。
- 模型：StepFun（fast=step-3.7-flash，smart=step-5-preview，lite=step-3.5-flash），全部模型调用只走 `backend/app/llm.py`。
- 核心优先级：**助手操作服务器的能力**（沙盒 shell/代码、持久工作区、后台任务、真实浏览器任务、装包、文件回传聊天；超时、4GB VPS 限制、崩溃恢复）。

## 二、宗旨（永远第一位，覆盖一切）
用户原话：“顾全大局…不要乱加上去，叠叠叠…这是宗旨，永远第一位”“纵观大局 执政者”“后面还要维护的，不能乱堆”。
1. **任何新功能/改动先看全局**：UX 全流程、所有页面、App/Web/后端一致、模块与数据流、API、数据库、提示词与助手行为、VPS 资源、成本、测试、文档。先决定它真正归属哪里、**替换掉什么**，再写代码。
2. **替换，不叠加**：新路径上线就删旧路径（旧代码 + 旧测试一起删），不留两套；单一数据源、单一组件、单一入口模块（一条规则只在一个文件里）。加 UI 就要删掉一个冗余的东西。
3. **不是用户说要什么就堆什么**：用户提需求，你要判断它在整体里合不合理，用最合理的方式融入。
4. **可维护性**：长期能维护；删死代码；不要“屎山”。
5. **写代码前先在 `docs/devlog.md` 写全局决定**（为什么放这、替换了什么、成本）。
6. **每个版本 CHANGELOG 必须有“删除/合并”一行**。
7. 动效：要有且要流畅、不卡；**只动画 transform / opacity**；支持 reduce-motion；性能与成本优先。
8. 设计：高级、优雅、沉稳，像 Hark（UI 规则见下）。文案专业书面，不口语化（例外：替用户写的示例提问）。
9. 学习参考：先找 1–2 个开源（MIT/Apache）实现学习再动手，移植时保留许可证头并注明 “Ported from <repo>/<path> (<license>)”，在 `NOTICE` 记一行。主要参考 deepseek-harness、openai/codex、gemini-cli。**绝不使用泄露的 Claude Code 源码**。不泄露/不打听 Hark 内部实现，只学公开表现。
10. **实践是检验真理的唯一标准**：每次改动后跑真实测试（含真模型 E2E），bug 优先于新功能。
11. 用中文回复用户；优先低成本方案，费 token 的功能要先说明。

## 三、工程规矩（看代码 / 改代码时）
- Flutter：颜色/时长只在 `app/lib/theme/tokens.dart`，动效只在 `app/lib/ui/motion.dart`；弹层只在 `ui/sheets.dart`，子页面 `ui/sub_page.dart`；**不要 `dart format lib`**；测试用 `package:assistant/...` 导入。
- Web：只用 `tokens.css` 变量，keyframes 只在 `styles/base.css`；`npm run build`（含 check-arch）必须过。
- 后端：改表必须 Alembic 迁移（当前到 0064）；SQLite 下 ctx.db 写入要在下次模型调用前 commit；runner._run_turn 先读完 conv 属性再 build_history。
- 协议变更同步 `docs/protocol.md`。
- 版本：唯一版本源 `VERSION` → `python3 brand/sync.py` 同步 App/Web/后端 → 测试 → 写 CHANGELOG → commit → `bash scripts/check_version.sh vX.Y` → tag → push。产品名只来自 `brand.json`。
- 提交前：`flutter analyze` 0 问题、全量 `flutter test`、`npm run build`、后端全部 smoke；`git diff --cached | grep -iE 'api[_-]?key|secret|token='` 必须为空；不 force-push。
- 真实 E2E：`work/e2e-harness/`（在旧沙盒里；新环境需按 devlog 重建）。

## 四、版本现状
- 已发布：v2.85–v2.90，本次 v2.90.1（用户气泡改灰）。
- v2.89：浏览器实时推流（CDP screencast，单条 WS，取代截图轮询）。
- v2.90：运行中连发“按件回复”（`backend/app/message_intake.py` 单入口；补充并入 / 附和不回 / 问进度一句话 / 新问题并行一路；`messages.answered_by` 账本，迁移 0064；回复离原话远才画引用线）。
- VPS：GreenCloud 2C/3.8G Debian 12，IP 172.93.163.240，域名 toyuis.itsllm.com。**2026-10-14 21:08 已部署 v2.90.1**（`/api/version` = 2.90.1，7 个容器全部 Up，迁移 0064）。磁盘 87%（35G 用 29G），下次构建前先 `docker builder prune`。部署方式见 `deploy/`（git archive → 上传 → `deploy/update.sh`）。

## 五、用户提过但还没完成的要求（按优先级）
> 完整原话与决定见 `docs/home-redesign.md`（A–P 各节）和 `docs/devlog.md`；凡标注“剩/待/未做”的都算未完成，接手后先逐节核对一遍。
1. ~~重新部署 VPS~~ 已完成 v2.90.1。剩：真机打开网页确认标题是 Toyuis、实时画面和连发回复在服务器上能用；之后**每批改动都要重新部署**（用户原话：“你要把这版推上去啊，更新到服务器上去”）。
2. **用户气泡截图验收**（v2.90.1 只改了颜色 token，未截图）：App 浅/深 + 网页，与 Hark 截图 1000035386 并排对比；a11y 对比度 ≥4.5 补测试。编辑中/引用条/长按聚焦也要跟随新颜色（home-redesign §L）。
2a. **连接器“点一下就能授权”**（用户 15:27 原话：“连接器没用，根本就连不上…人家是点一下就能够直接授个权”；更早：“连接 GitHub、Gmail…全面与你对标”“为什么现在连接不了 GitHub 还有 Gmail，显示还没有做”）。**v2.90.2 已做“按钮诚实化 + 引导页 + docs/oauth-setup.md”（未部署）；剩：在 GitHub / Google 后台注册应用、填 VPS `.env`、重启、真机走通授权。** 原因：OAuth 代码在 `backend/app/connectors/oauth.py`，但 VPS `.env` 的 GOOGLE_/GITHUB_CLIENT_ID/SECRET 是空的，点了必失败。要做：
   - 在 VPS 注册 GitHub OAuth App、Google OAuth（测试模式，把用户自己加为测试用户），回调地址 `https://toyuis.itsllm.com/...`（看 oauth.py），填进 `.env` 后重启，真机走通 GitHub、Gmail 一键授权。
   - 没配置的提供方，按钮不能“看起来能点、点了失败”：只显示已配置的；全没配时普通用户不显示，管理员显示“服务器还差一步：配置 Google 授权”并进引导页。
   - “我 → 连接的账号”统一：OAuth、MCP、API Key、网站登录在同一页分区（连接器 + 保险箱合并，home-redesign B/§连接器）。
3. **连发分组准确率重评**（用户 20:48）：现在的 70% 是拿 Hark“空闲时逐条回”的历史当答案，不是真准确率。按 §C 定稿规则重新标注 57 组（`work/e2e-harness/intake_cases.jsonl`），重跑 `eval_intake.py`，只修真误判，报告真实准确率与修了哪些类。
4. **v2.91 §N 项目页**（home-redesign §N）：项目对话左钮“≡”↔“+”（三条线旋转成十字 ~280ms）；项目列表带状态胶囊（进行中/等你回复/已完成）；进场浮出项目名药丸（下滑 8px+淡入，轻微回弹 ≤4%）；**往上滑看历史 >24px 也浮出**，下滑/停 1.5 秒/回到底部收起；App 用 ValueNotifier+RepaintBoundary 不整页 setState，Web 用 passive scroll+rAF；药丸显示**总结标题**（唯一来源 conversation_title，名词短语 ≤14 字、无标点口语，话题变了每约 10 条重总结），列表/药丸共用；`first_title` 只作生成前占位。要“细腻，不粗糙”。
5. **v2.92 §P 名字与头像**：首次进对话由助手**在聊天里**问称呼和是否给助手取名（不做表单引导页）；不取名默认叫 Toyuis；`users.display_name`、`users.avatar`、`app_settings.assistant_name`；头像可上传，无图=纯色圆+首字母（复用 Avatar）；“我”页点名字/头像可改；助手名进系统提示词。**语气**：正式、不开玩笑，但初次打招呼可亲切。定稿开场：“你好，我是 Toyuis，很高兴为你服务。请问我该如何称呼你？如果你愿意，也可以为我取一个名字；不取的话，我就继续叫 Toyuis。”
6. home-redesign 剩余：E1 收尾（ListRow/ListGroup/PageHeader 统一、附件弹层高度）、E4 ImageStack + 震动反馈、主页内置天气卡去重（天气面板同一报告重复 3 次的 bug）、连接器按钮诚实化 + OAuth 指南、“我的”页底部搜索、电脑端主页排版割裂/左半屏空（`work/vps/README.md` 顶部 bug）、Composer 遮住最后一张面板。
7. 后台任务/定时任务的运行对话不要出现在主对话列表（用户叫“子对话”，嫌乱）——确认 v2.75 修复在 VPS 上生效。
8. Web 截图重拍、banner“稍后再看”。
9. SearXNG 集成测试（需 VPS）；关闭 VPS SSH 密码登录。
10. CORE：`docs/core-gaps.md` #9（一次读多文件）。BRAIN：继续对照 Hark 公开表现找差距（先写对比再做）。

## 六、可以继续优化的地方（我的判断）
- 并发收消息：并行一路目前整条到达、不推流、不弹审批；进度回答只读步骤，推理模型思考中只能说“正在想”。
- smoke_jobs §13 约 1/4 偶发失败（测试替身 pid/zombie 时序）；smoke_jobs / smoke_reply_quote 在高负载下偶发 sqlite locked。
- 本地浏览器渲染测试因 venv playwright 版本不匹配而坏（仅环境问题）。
- 每次 UI 交付都要附 App 明/暗 + Web 截图并与 Hark 并排自评——这一步之前常被跳过，要坚持。

## 八、用户 10-13～10-14 全部要求逐条核对（接手时以此为清单）
状态：✅ 已做并提交 ｜ ⚠️ 做了但未验收/未上线 ｜ ❌ 未做 ｜ ❓ 未核实，接手先查
| 用户原话（摘要） | 状态 | 在哪 |
|---|---|---|
| 核心功能对标 Codex / DeepSeek / Gemini 三个 agent，学优点、能用就用，以 Hark/Muse/Cue/Dots 的消费者价值判断 | ⚠️ 持续项 | core-research.md、core-gaps.md（#9 未做） |
| 没 VPS 先用你的云电脑测试，多测试，实践是检验真理的唯一标准 | ✅ 规则 | work/e2e-harness（每轮真 E2E） |
| 点开任何功能就白屏（http 下） | ✅ | lib/uuid.ts、clipboard.ts |
| 连接不了 GitHub、Gmail；点一下登录再确认授权 | ⚠️ v2.90.2 按钮诚实化 + 配置引导已提交；OAuth 应用未注册、未部署 | 见第五节 2a、docs/oauth-setup.md |
| 删了的对话又蹦出来；子对话（定时任务运行对话）不要放主列表 | ⚠️ v2.75 修了，需在服务器上确认 | devlog v2.75 |
| CPU 60%～100%、内存占用高，要优化 | ❓ | 服务器上 `docker stats` 核实；APK 构建已改为限流脚本 |
| 电脑端主页割裂、左边空一大块；天气报告重复 3 次；输入框遮住面板 | ❓ 部分 | work/vps/README.md 顶部；home-redesign 第 8 项 |
| 主页对比 Hark“又乱” → 整体重设计 | ⚠️ 进行中 | home-redesign A–E，E1/E4 收尾未完 |
| 历史抽屉被顶栏压住“还叠在一起” | ✅ v2.78 | |
| 步骤耗时都显示 0.0 秒、步骤默认展开很乱 | ✅ v2.79 | |
| 电脑端回复滚动 bug（往上看会被拉回底部） | ✅ v2.79 | |
| 服务器状态是不是真实的 | ✅ v2.85（写清是沙盒容器 + 整台服务器一行） | |
| “我”页太长不好看，学 Hark 个人页 | ✅ v2.81（底部搜索 ❌） | |
| 加号附件弹层很丑 | ⚠️ 高度按内容未做 | home-redesign E1 |
| Hark 发图片的排布（ImageStack） | ❌ | home-redesign E4 |
| 每句话单独回复并关联引用 | ✅ v2.87 + v2.90 | |
| 用新图标 | ✅ v2.80 | |
| 字体丑、整体不优雅，学 Hark、找 skill/开源学 | ✅ v2.83 字体；⚠️ 整体质感持续打磨 | hark-elegant-ui 规则 |
| 接管页点不到、画面小 | ✅ v2.82 | |
| 点哪条气泡显示哪条的时间 | ✅ v2.84 | |
| 长按聚焦菜单 + “回复”这条 | ✅ v2.87 | |
| 软件名 Toyuis、做好版本管理、名字上面还写 assistant | ✅ v2.86 | |
| 用户气泡不要白色，Hark 偏灰 | ⚠️ v2.90.1 改了颜色，未截图验收 | 第五节 2 |
| 网页“选档”（模型选择）UI 太拉、越改越丑 | ⚠️ v2.87 改过，未让用户确认 | devlog 18:40/18:56 |
| 网页显示动不动就断、不流畅，学 Muse/Dots/browser 类项目 | ✅ v2.89 实时推流 | |
| 截图 1000035389“排版怎么回事”、1000035390“这么割裂” | ❓ | 看 files/uploads 原图核对 |
| 回复里有工具调用符号、排版随意；文案口语化不专业 | ✅ v2.88 | |
| 发送时气泡往上弹一下 | ✅ v2.88 | |
| 动效既要有又要流畅 | ✅ 规则（只动 transform/opacity） | |
| 项目页左上角 ≡、对话条目带状态、进场/上滑浮出总结标题、细腻有小动效 | ❌ | §N（v2.91） |
| 运行中能继续发，意思相近合并回复，要有判断 | ✅ v2.90；⚠️ 准确率重评未做 | 第五节 3 |
| 名字头像自定义，首次正式而亲切地问，不取名叫 Toyuis | ❌ | §P（v2.92） |
| 做交接文档，把没做的都写清楚 | ✅ 本文件 | |

## 七、和用户相处要注意
- 他会一边看你做一边连发消息：同一件事合并回复，进度问题快速短答，别逐条啰嗦。
- 说过的要求要记住并真正做完；做不到要直说，不要说“改了”而实际没改（气泡颜色就是被漏掉的例子）。
- 他说“停”才停；不要每轮问“继续吗”。

## 九、接手记录二（2026-10-14 晚，Windows 工作站）

### 先看这条：这个仓库可能同时有别的会话在推
- 我在 `9aef516` 克隆，做完一轮准备 push 时发现 main 已经多了 `0595497`（v2.90.2 连接器按钮诚实化 + docs/oauth-setup.md + docs/devlog.md）和 `18cc00f`。
- **开工前先 `git fetch origin && git log --oneline origin/main -5`**；动手做第五节任何一条前，先确认 main 上没人已经做了。
- 我那一轮把连接器这块做重了（自己写了 `visibleAccounts/oauthCallbackUrl` + 自己的引导弹层 + `docs/connectors-oauth.md`），比对后**整块丢掉**，采用 main 上的实现：它由后端 `GET /api/connectors` 每项给 `setup`（去哪注册、回调地址、env 变量名），App/Web 只画，单一数据源更好。我的备份分支：`my-clone-work`。
- 只留下与连接器无关、main 上确实缺的修补（见本节末“留下的”）。

### 这台 Windows 工作站怎么跑起来（不要再从零摸索）
- **Flutter 3.47.7 / Dart 3.13.5**：`C:\Users\zhish\flutter\flutter\bin`（SDK zip 从 `https://storage.flutter-io.cn/flutter_infra_release/releases/stable/windows/` 下，1.8G，断线要 `curl -C -` 续传）。命令前设 `PUB_HOSTED_URL=https://pub.flutter-io.cn`、`FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`，`flutter pub get` 才通；`pypi.org`、`storage.googleapis.com` 直连超时，pip 用 `https://mirrors.aliyun.com/pypi/simple/`。
- **后端**：`cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt --index-url <aliyun>`，另外要 `uv pip install aiosqlite`（requirements 里没有，smoke 全用 SQLite）。跑单个 smoke：`.venv\Scripts\python.exe tests\smoke_x.py`。
- **网页截图**：playwright 装在 `backend/.venv` 里，本机不必下 chromium——设 `SHOTS_CHANNEL=chrome` 用系统 Chrome（`frontend/scripts/shots.py` 已支持）。`python scripts/shots.py <输出目录>`。
- **不要 `dart format`、不要用 PowerShell 直接 `git commit -m "中文"`**（PS 5.1 会把中文搞坏）：把提交信息写进临时文件再 `git commit -F`。

### Windows 上踩过的两个坑（已修，别再改回去）
1. **CRLF 会毁掉部署包**：这台机器 `core.autocrlf=true`，`git archive` 打出来的 `*.sh` 是 CRLF，传到服务器就是 `set: pipefail: invalid option name`、`$'\r': command not found`。已加 `.gitattributes`（`*.sh` / `Dockerfile` / `compose*.yml` 钉 LF）；生成部署包时仍要 `git -c core.autocrlf=false archive ...`。
2. **大小写同名文件**：`projectHome.ts` 与组件 `ProjectHome.tsx` 只差大小写，Windows/macOS 上 `tsc -b` 直接 TS1149。纯规则文件已改名 `projectHomeRules.ts`，别再改回来。

### 后端 smoke 在 Windows 上的真实基线（2026-10-14 实测）
- 200 个 smoke：**Windows 上 143 通过 / 57 失败**；把控制台改成 UTF-8（`PYTHONUTF8=1`）后 15 个恢复，其余 42 个是平台差异，不是 bug：
  `os.statvfs`（Linux-only）、符号链接权限（WinError 1314）、路径分隔符断言（`notes\plan.md` vs `notes/plan.md`）、GBK 编码打印、依赖 Docker 沙盒/作业容器的 `smoke_job_*`/`smoke_sandbox_*`/`smoke_services`、需要真 key 的 `smoke_stepfun`/`smoke_vision`。
- 结论：**别用 Windows 上的全量 smoke 判定回归**；改后端时挑相关 smoke 跑，整量回归放到 Linux（VPS 或沙盒）上做。

### 仓库里仍然缺的东西
- 只有 `docs/protocol.md`、`docs/devlog.md`、`docs/oauth-setup.md` 三个文档；`docs/home-redesign.md`、`docs/blueprint.md`、`docs/core-research.md`、`docs/core-gaps.md`、`work/`（含 e2e-harness）**从未提交过**，所以 §L/§N/§P 的确切规格只能靠第五节和 §八 的描述复原（我已用 `git log --all` 确认全历史里都没有）。
- 推断的 VPS 事实（只读 ssh 核实，别名 `hark`，172.93.163.240）：代码在 `/opt/assistant/app`，`.env` 第 64–68 行的 `GOOGLE_/GITHUB_CLIENT_ID/SECRET` 是空的（连接器连不上的根因），磁盘 29G/35G（88%），build cache 5.4G / 可回收 3.9G——**下次构建前先 `docker builder prune`**。

### 我这一轮留下的（相对 main）
- `.gitattributes` + `scripts/check_version.sh`（补丁版 tag 用全版本号，vX.Y 与 vX.Y.Z 都收）。
- `brand/sync.py` 一并同步 `frontend/package-lock.json`（main 上 lock 还停在 2.90.1，`--check` 之前根本不管它）。
- `frontend/scripts/check-arch.mjs` 的 Windows 路径修好（以前在本机直接 ENOENT，架构守卫等于没跑）。
- `app/test/design_test.dart` 字重/悬浮钮守卫的路径分隔符修好（Windows 上必红）。
- `frontend/scripts/shots.py` 支持 `SHOTS_CHANNEL`；`.gitignore` 忽略 `*.tsbuildinfo` 并把它移出版本库。

### 第五节 8「Web 截图重拍」现在走到哪了（2026-10-14 晚）
`frontend/scripts/shots.py` 之所以一直拍不全，不是浏览器问题，是**假接口缺数据**：页面请求了没假数据的接口 → 拿到 `[]` → 前端读 `undefined.length` → 整屏白掉，脚本就卡在那一步。已修：
- 补 `/api/preferences`（缺了它「我的 → 偏好设置」「用量」「项目里对话」三张图是同一张白屏）、`/api/projects/pr1/computer`（缺了它项目首屏白屏）。
  → 这三张图现在分别是 142KB / 170KB / 205KB，内容各不相同（以前完全一样）。
- 「存到项目文件」已经收进回复的 ⋯ 菜单，定位器改成先开「这条回复的操作」再点菜单项「存成文件」。
- 脚本跑完（或跑挂）会打印「请求了但没有假数据」的清单，照单补 `FIXTURES` 即可。
- 现在仍卡在：点开项目对话后找 `.msg.assistant.last` 里那个 ⋯（类名或结构又变了，需要 dump 一次 DOM 确认）。**下一个人从这里接着修**，修完就能一次拍出明/暗 × 桌面/手机的整套图。



# Toyuis 交接文档（2026-10-15，v3.0.0）

> **给每个接手的 agent**：先读第二节宗旨（1–17 条）。用户在对话里说出的任何纲领性要求，当轮用明确、不会被误解的话（不必照抄原话）带日期补进第二节，这是硬规矩（见第 16 条）。


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
12. **不主动部署、不主动编 APK**（用户 2026-10-15 13:03）：版本照常提交/tag/push，部署和 APK 等用户开口（“更新服务器”/要 APK）。
13. **UI 一定要细腻整洁，要用心**（用户 2026-10-15 原话：“ui一定要细腻整洁，所以要用心”）：间距 / 圆角 / 阴影 / 层叠偏移只用现有 token；明暗两套都要看；动效克制顺滑（只 transform / opacity + reduce-motion）；空态与边界情况（1 张、很多张、竖图 / 横图、加载失败、无结果）都要有体面的样子。**宁可少做一块，也不要粗糙交付。**

14. **不会就找办法，不硬猜**（用户 2026-10-15 17:28：“自己不会的话可以去找可以参考或者相关skills，反正有办法”）：拿不准的交互/实现，先找相关技能，再查官方文档、成熟开源实现、设计规范（Material / Apple HIG / Hark 表现），借鉴后按本项目 token 与组件自己实现，参考来源记进 devlog。
15. **连续推进，不停下等验收**（用户 2026-10-15：“我又不着急去检验，我可以等你做好好几个版本之后再去校验”“继续，别停下来”）：做完一版就沿本文件第五节做下一项，不等确认；每完成一块立刻更新本文件（做了什么/没做什么），中途中断也要反映真实进度；额度用在优化项目上，不做无必要的重复工作。
16. **用户的纲领性要求一律写进本节**（用户 2026-10-15 定）：用户常换不同的 agent 接手，接手者只认本文件。用户说出的原则、偏好、做事方式，当轮写进第二节，写日期。**用自己的话写清楚意思，不必照抄原话**：口语原话容易被误读，要写成谁都不会理解错的明确规则，必要时写“做什么 / 不做什么 / 拿不准怎么办”，并给具体例子。这条对每一个接手的 agent 都适用，要原样传下去。

17. **没用的就删，有用的别删**（用户 2026-10-15 定；起因：VPS 35G 硬盘一天用到 77%，清理后 49%）。判断标准只有一条：**还用不用得上**。
   - **必须删**（能再生成且确定用不上）：编 APK 后的 gradle 缓存（`/opt/apkbuild/gradle` 下除 `wrapper` 外全部）、`/root/.pub-cache`、`/opt/apkbuild/src`；Docker 悬空镜像（`docker image prune -f`，**不带 -a**）和构建缓存（`docker builder prune -f`）；`/root` 下旧版本代码包和旧日志（只留最近一版）；用完的临时 swap、临时脚本输出、测试临时文件。
   - **绝不能删**（删了要重装、会坏、或丢数据）：安卓 SDK、Flutter、JDK（`/opt/apkbuild/sdk|flutter|jdk`）；正在运行或 compose 引用的镜像（含 `assistant-sandbox`，即使当前没容器在跑）；数据库和数据卷（`/opt/assistant/data`、Docker volumes）；`/root/backups`；最近一版代码包（如 `v293.tgz`、`app-v2911-backup.tgz` 这类最近备份）和最近两份 `.env` 备份；部署脚本本身；`/swap.img`（常驻 swap）。
   - **拿不准就不删**，先查它被谁用（grep compose/脚本/代码），还拿不准就问用户；删前删后都 `df -h`，删后确认容器全部 Up、`/api/version` 正常。
   - **能自动的写进脚本**：`deploy/build-apk.sh` 结尾清上面“必须删”里的 APK 缓存；更新脚本结尾 `docker image prune -f` + `docker builder prune -f`（v3.0 之后下一版落地）。本地沙盒同理：测试日志、临时截图用完就删。

## 三、工程规矩（看代码 / 改代码时）
- **【部署 / APK 规则，用户 2026-10-15 13:03】不要每个版本都部署 VPS、编 APK。连续做多个版本只提交 + tag + push；只有用户说“更新服务器”才部署，APK 只在用户要时才编。**
- Flutter：颜色/时长只在 `app/lib/theme/tokens.dart`，动效只在 `app/lib/ui/motion.dart`；弹层只在 `ui/sheets.dart`，子页面 `ui/sub_page.dart`；列表行 / 分组 / 子页说明只用 `ui/kit.dart` 的 `ListRow` / `ListGroup` / `PageIntro`（网页同名在 `ui/kit.tsx`，v2.97，两端守卫：`test/list_kit_test.dart`、check-arch 第 7 条）；**不要 `dart format lib`**；测试用 `package:assistant/...` 导入。
- Web：只用 `tokens.css` 变量，keyframes 只在 `styles/base.css`；`npm run build`（含 check-arch）必须过。
- 后端：改表必须 Alembic 迁移（当前到 0067）；SQLite 下 ctx.db 写入要在下次模型调用前 commit；runner._run_turn 先读完 conv 属性再 build_history。
- 协议变更同步 `docs/protocol.md`。
- 版本：唯一版本源 `VERSION` → `python3 brand/sync.py` 同步 App/Web/后端 → 测试 → 写 CHANGELOG → commit → `bash scripts/check_version.sh vX.Y` → tag → push。产品名只来自 `brand.json`。
- 提交前：`flutter analyze` 0 问题、全量 `flutter test`、`npm run build`、后端全部 smoke；`git diff --cached | grep -iE 'api[_-]?key|secret|token='` 必须为空；不 force-push。
- 真实 E2E：`work/e2e-harness/`（在旧沙盒里；新环境需按 devlog 重建）。

## 四、版本现状
- 已发布：v2.85–v2.92（v2.90.1 用户气泡改灰；v2.90.3 已部署过一次，见下）。
- v2.89：浏览器实时推流（CDP screencast，单条 WS，取代截图轮询）。
- v2.90：运行中连发“按件回复”（`backend/app/message_intake.py` 单入口；补充并入 / 附和不回 / 问进度一句话 / 新问题并行一路；`messages.answered_by` 账本，迁移 0064；回复离原话远才画引用线）。
- 已发布到 git：**v3.0（tag v3.0，2026-10-15，“我的”页底部设置搜索两端 + `?focus=` 定位闪一下；版本号因构建号规则从 2.99 进位，无破坏性改动；纯前端）**、**v2.99（tag v2.99，2026-10-15，E4 ImageStack 两端 + App 震动统一入口 / AppSwitch；“我的”页底部搜索未做，见第五节第 6 项；纯前端）**、**v2.98（tag v2.98，2026-10-15，E1 Web 收尾：RAW_ROWS 81→23 处、23→12 个文件迁到 ListGroup / ListRow，App 6 个富内容行评估后保留，见第五节第 6 项；纯前端）**、**v2.97（tag v2.97，2026-10-15，E1 收尾：ListRow / ListGroup / PageIntro 两端统一 + App 附件弹层高度修复，见第五节第 6 项；无后端 / 迁移变化）**、**v2.96（tag v2.96，2026-10-15，“我 → 连接的账号”一页：连接器 + 保险箱合并，见 5·2a；含迁移 0067，只改旧卡去处 vault→connectors）**、v2.91、v2.91.1、v2.92、v2.93（tag v2.93，2026-10-15）、**v2.94（tag v2.94，主页三个 bug，见 6a）**、**v2.95（tag v2.95，2026-10-15，项目 = 一段对话，见 5b；含迁移 0066，部署时自动合并旧多对话项目、可回退）**。v2.94/v2.95/v2.96/v2.97/v2.98/v2.99/v3.0 均未部署、未出 APK（按新规则等用户说）。**2026-10-15 11:41 已部署 v2.93.0**（`/api/version`=2.93.0，容器全部 Up，.env 备份 /root/env.bak.v293，磁盘 88%，下次先 prune）；**2026-10-15 12:54 已在 VPS 用 `deploy/build-apk.sh` 编好 v2.93.0 APK**（arm64，22.2 MB，约 7 分钟，构建后容器已恢复）。
- VPS：GreenCloud 2C/3.8G Debian 12，IP 172.93.163.240，域名 toyuis.itsllm.com。部署方式见 `deploy/`（git archive → 上传 → `deploy/update.sh`）。
  - **2026-10-15 约 11:05 已部署 v2.92.0**（`/api/version` = 2.92.0，容器全部 Up）。旧版备份 `/root/app-v2911-backup.tgz`，.env 备份 `/root/env.bak.v292`；`docker builder prune` 后磁盘 80%。
  - 真模型（StepFun）验证通过：主聊天说“以后叫我小测，你就叫阿星”→ 调用 set_names（步骤“保存称呼”），profile 变为 小测 / 阿星；验证后已删测试对话和 identity 行，greet 恢复为 true（保留用户自己的首次问候体验）。
  - 未验：首次问候对话（greet 流程本身）在真机上的表现；回复里出现“一直陪着你”偏口语，提示词可再收紧。v2.92 安装包（APK）尚未构建（用户说不急）。
  - **2026-10-15 18:10 VPS 清理**：删 gradle 缓存（/opt/apkbuild/gradle 只留 wrapper）、/opt/apkbuild/src、/root/.pub-cache、/root 下旧版本包和旧日志、Docker 悬空镜像与构建缓存，关掉并删除 /swapfile2（4G，未使用；保留 /swap.img 1.5G）；硬盘 26G→17G（49%），容器全部 Up，线上仍 2.93.0。下次编 APK 会重新下载 gradle/pub 依赖（慢几分钟）；内存不够时临时加 swap，编完删掉。用户 10-15 原话：‘把不重要的删掉，这样太浪费了’——以后编完 APK 就清缓存。
  - 坑：部署时用 `pgrep -f 'deploy/update.sh'` 轮询会匹配到轮询命令自身（永远“还在跑”），改用 pid 文件或 `pgrep -x`/排除自身。

## 五、用户提过但还没完成的要求（按优先级）
> 完整原话与决定见 `docs/home-redesign.md`（A–P 各节）和 `docs/devlog.md`；凡标注“剩/待/未做”的都算未完成，接手后先逐节核对一遍。
1. ~~重新部署 VPS~~ 已完成 v2.90.1。剩：真机打开网页确认标题是 Toyuis、实时画面和连发回复在服务器上能用；~~之后每批改动都要重新部署~~ **已被 2026-10-15 13:03 新规则取代：只有用户说“更新服务器”才部署，APK 也只在用户要时才编**（见第三节顶部）。
2. ~~**用户气泡截图验收**（v2.90.1 只改了颜色 token，未截图）：App 浅/深 + 网页，与 Hark 截图 1000035386 并排对比；a11y 对比度 ≥4.5 补测试。编辑中/引用条/长按聚焦也要跟随新颜色（home-redesign §L）。~~ 2026-10-15 做完：气泡 13.80:1（浅）/14.84:1（深），App 6 个新测试 + 网页构建期守门；顺带修了浅色警示色 3.62→4.93。**剩用户自己拿 Hark 截图并排看一眼**（图在 `shots-2.90.2/`）。
2a. **连接器“点一下就能授权”**（用户 15:27 原话：“连接器没用，根本就连不上…人家是点一下就能够直接授个权”；更早：“连接 GitHub、Gmail…全面与你对标”“为什么现在连接不了 GitHub 还有 Gmail，显示还没有做”）。**v2.90.2 已做“按钮诚实化 + 引导页 + docs/oauth-setup.md”，v2.96 已做“连接的账号”一页（均未部署）；剩：在 GitHub / Google 后台注册应用、填 VPS `.env`、重启、真机走通授权。** 原因：OAuth 代码在 `backend/app/connectors/oauth.py`，但 VPS `.env` 的 GOOGLE_/GITHUB_CLIENT_ID/SECRET 是空的，点了必失败。要做：
   - 在 VPS 注册 GitHub OAuth App、Google OAuth（测试模式，把用户自己加为测试用户），回调地址 `https://toyuis.itsllm.com/...`（看 oauth.py），填进 `.env` 后重启，真机走通 GitHub、Gmail 一键授权。
   - 没配置的提供方，按钮不能“看起来能点、点了失败”：只显示已配置的；全没配时普通用户不显示，管理员显示“服务器还差一步：配置 Google 授权”并进引导页。
   - “我 → 连接的账号”统一：OAuth、MCP、API Key、网站登录在同一页分区（连接器 + 保险箱合并，home-redesign B/§连接器）。
   - **v2.96 进度（2026-10-15，按块如实更新）**：第二条核实 v2.90.2 已做到（单用户 = 登录者即管理员），不重复；第三条本轮做，决定见 docs/devlog.md「2026-10-15 v2.96」。
     - [x] devlog：现状、决定、删除清单、成本
     - [x] 后端：card target vault 并入 connectors（card_targets / task_wall / 浏览器登录过期提醒 / env 工具文案）+ 迁移 0067（home_cards.target vault→connectors）；protocol.md 同步；smoke_offer_target / task_wall / browser_login_expiry / project_chat（加 0067 用例）已过
     - [x] App：连接的账号一页（`connectors_screen.dart`；`vault_screen.dart` → `secret_rows.dart` 只剩表单与行），页头 + 唯一添加入口（`addKinds` 四类）、MCP+密钥都空时一张起步卡；删 `/me/vault`、`/me/accounts`、`MeHub.accounts`、`vaultSummary`、“其他服务”行、MCP 区 +；“我”页行直达；cardTargets 删 vault
     - [x] Web：同构（`ConnectorsScreen.tsx`；`VaultScreen.tsx` → `SecretSheet.tsx` 弹层 + 行，去掉弹层里的种类切换——种类在 + 菜单里选，= App）；删 `me/vault`、`me/accounts` 路由、MeHub accounts、cardTargets vault；shots.py 去掉 vault 一张。`npm run build` 过。**未在浏览器实点 / 未截图**（本机无 Chromium）
     - [x] 测试：flutter analyze 0、flutter test 674 过（8 跳过；connector_library_test 保险箱页 4 例改写成连接的账号页 5 例，含“+ 唯一入口四类”）、npm run build 过（架构守卫 217 文件）、后端 smoke 202/202（不含 smoke_stepfun；smoke_jobs 并行时偶发失败、单跑过；smoke_request_env 随 env 工具文案改了断言）
     - [x] 发布 v2.96：VERSION 2.96.0、CHANGELOG、check_version、commit + tag v2.96 + push（不部署、不出 APK）
     - [ ] 未做：浏览器 / 真机实点与截图（App 明暗 + Web 手机宽度）；部署后核对 0067 把旧“打开保险箱”卡改成了“去连接的账号”
3. ~~**连发分组准确率重评**（用户 20:48）~~ 2026-10-15 做完，但**不是原地重标**：`work/e2e-harness/intake_cases.jsonl`、`eval_intake.py`、`docs/home-redesign.md`（§C 定义所在）**从没提交进 git**，只在旧沙盒里，旧的那个 70% 不可复现。改成把评测搬进仓库当唯一真源：
   - 标注集 `backend/tests/intake_cases.jsonl`（**57 组 / 74 条**，每组带 `why` 说明标注依据，可复核）；评测器 `backend/tests/smoke_intake_eval.py`（`python tests/smoke_intake_eval.py -v`；`EVAL_JUDGE=1` 加跑真模型判官层）。
   - 量出来的真实数字（v2.90.4）：**规则层误判 0**、62.2% 的条数靠规则直接定、37.8% 交给便宜模型；57 组里 30 组纯靠规则、27 组要问一次 ≈200 token 的便宜模型（`SUMMARY_MODEL=lite`）；判官答对即 100%。
   - 修掉的真实误判（全是“另一件事被当成补充/进度”这一类）：问句形状的“要多少钱”“用哪个好”“要不要加个总结”（软前缀 要/用 + 问句 → 交给判官）、指向别的对象的“另外那个项目进度怎么样”（→ 交给判官）、带附件又问别的（→ 交给判官）。
   - 没动的取向：拿不准仍按补充（宁少勿多）；判官失败/超时仍按补充。
   - 判官层的真模型分数见下面「接手记录二」里的实测一节。
4. ~~**v2.91 §N 项目页**~~ **2.91.0 已提交（未部署）**，决定见 docs/devlog.md 2026-10-15；剩：部署后真机看 App 明/暗动效手感。原规格（home-redesign §N）：项目对话左钮“≡”↔“+”（三条线旋转成十字 ~280ms）；项目列表带状态胶囊（进行中/等你回复/已完成）；进场浮出项目名药丸（下滑 8px+淡入，轻微回弹 ≤4%）；**往上滑看历史 >24px 也浮出**，下滑/停 1.5 秒/回到底部收起；App 用 ValueNotifier+RepaintBoundary 不整页 setState，Web 用 passive scroll+rAF；药丸显示**总结标题**（唯一来源 conversation_title，名词短语 ≤14 字、无标点口语，话题变了每约 10 条重总结），列表/药丸共用；`first_title` 只作生成前占位。要“细腻，不粗糙”。
5a. **v2.93 §Q 项目页按 Hark 重做 + 手机弹层修遮挡（代码已提交 tag v2.93）**。⚠️ 项目内对话列表 / 抽屉 / +↔≡ 第三态 / 项目汇总状态已被 v2.95（5b）取代；弹层修遮挡与顶栏常驻仍有效。规格与决定见 docs/devlog.md「2026-10-15 v2.93 §Q」。
   - [x] devlog 全局决定 + 替换/删除 + 成本
   - [x] 后端：`conversation_status.summarize/for_projects`，`GET /api/projects` 每项加 `status`（无迁移）；smoke_conversation_status 加项目汇总一节，已过
   - [x] App（代码 + 测试，analyze 0、全量 flutter test 通过）：`shellBarShown`、`MenuPlusGlyph/MenuPlusHero`（Hero 骑在项目页路由动画上）、项目页 `CustomTransitionPage`（淡入 + 浮上 8px，Motion.morph）+ 列表 `FadeUnderCover`、ChatScaffold 只剩 ShellPage 一种外框、项目列表大字 + `projectIsCurrent` 灰化 + 汇总胶囊、ProjectHome 只列对话、⋯ 加“电脑”、sheets.dart `useSafeArea` + 表单提交钮钉底；顺手修 `SpeechController.stop` 在容器已释放时报错。
     - **发现（未改，留给用户定）**：go_router 在本 App 里判不出 MaterialApp，所有路由都用了**无转场页**（子页面进出是瞬切）。本轮只给项目页单独加了转场；要不要全局恢复页面转场是另一件事。
   - [x] Web（`npm run build` 通过）：TopBar `isShellRoot` + 滑块按前缀、ProjectScreen 进外壳 + 标题行（‹ / 项目名 / ⋯）、项目抽屉从标题行下滑出、列表大字 + `projectIsCurrent` + 汇总胶囊、ProjectHome 对话列表、MenuPlus 记上一颗形状做 morph、Sheet portal + visualViewport + sticky 按钮行（删掉两处多余的外层 createPortal）
   - [ ] Web 截图核对（手机宽度：列表 / 项目 / 抽屉 / 新建项目弹层 / 新面板弹层）
   - [x] 测试（最终代码上）：flutter analyze 0、flutter test 671 过（8 跳过）、npm run build 过、后端 smoke 201/201（不含需真密钥的 smoke_stepfun）；protocol/CHANGELOG/VERSION 2.93.0、tag v2.93、push
   - [x] 部署 VPS（2026-10-15 11:41）
   - [x] 出 APK：2026-10-15 12:54 VPS 上 `deploy/build-apk.sh` 编好 v2.93.0（arm64，22.2 MB，约 7 分钟，构建后容器已恢复）
   - [ ] 真机看 App 项目页 +↔≡ 切换手感、明/暗；手机浏览器验弹层三处不再被挡
   - [ ] App 截图回归里 emoji 无字体显示为空白（仅测试环境）
5b. ✅（v2.95.0 已做并提交，未部署）**项目 = 一段对话**（用户 2026-10-15 12:48 原话大意：“Hark 里一个项目就是一段对话，不能在项目里开多个会话”；附 Hark 截图（在 Hark 项目工作区 `files/uploads/1000035393.png`，不在仓库里）：点进项目直接就是聊天，顶栏下方药丸显示项目名，左上 ≡，底部输入框）。**v2.93 的“项目内对话列表 / 抽屉 / 新建本项目对话”方向错了。**
   - 要被替换的 v2.93/v2.91 部分：ProjectHome 对话列表（App `features/projects/project_home.dart` 相关、Web `ProjectHome.tsx`）；项目对话抽屉（App ShellPage 内层 Scaffold 抽屉、Web 项目抽屉 + 遮罩）；“+ = 本项目新对话”与 ≡↔+ 的第三态；header 行 ‹ / 项目名 / ⋯ 是否保留待定；双栏项目历史栏；`conversation_status.for_projects/summarize` 的多对话汇总（单对话后项目状态 = 那段对话的状态，summarize 可删）；`GET /api/conversations?project_id=` 的项目内列表用法。
   - 待定设计要点（先在 devlog 写决定再动手）：①项目 = 唯一对话（建项目即建这段对话，项目 id ↔ 对话 id 一一对应，需迁移或约束）；②点项目直接进聊天，药丸显示项目名（v2.91 药丸当前显示对话总结标题，要改成项目名）；③**现有多对话项目的数据怎么并成一段**（按时间合并消息进最早那段？还是保留最近一段、其余归档进主聊天？需用户定，迁移不可逆要先备份）；④左上 ≡ 改作什么（Hark 截图里 ≡ 在项目里——候选：回项目列表 / 项目菜单（文件、电脑、规则）；需定）；⑤后端 / 协议（docs/protocol.md）/ 状态胶囊随之简化，删掉多对话专用代码与测试。
   - **v2.95 进度（2026-10-15，按块如实更新）**：
     - [x] 设计决定：写进 docs/devlog.md「2026-10-15 v2.95 项目 = 一段对话」（项目=唯一普通对话 + 部分唯一索引；药丸=项目名并兼项目菜单；≡=项目切换抽屉、开着变 + = 新建项目；状态=那段对话的状态；迁移按 created_at 合并、备份表 + downgrade、幂等）
     - [x] 数据迁移 0066（用户已授权不必再确认：可回退）：多段按 created_at 合进最早那段，引用行改指，备份表 + downgrade，幂等，部分唯一索引；smoke_project_chat 覆盖合并/回退/再升级/幂等，已过
     - [x] 后端：project_chat.py 唯一入口；建项目/发消息/建议卡/转交都用项目那段；/api/projects 改 conversation_id，删 summarize/for_projects；项目对话单删 409。待全量 smoke 复核（smoke_project_brief/file_refs 需改）
     - [x] App：project_switcher.dart（切换抽屉 + 项目名药丸），删 title_pill/project_home 与 pill 时长 token；离线无缓存时草稿保留
     - [x] Web：ProjectSwitcher.tsx，删 ProjectHome/TitlePill；跳进项目统一 openProjectChat；项目里 /new 提示新建项目；protocol.md 已同步。未在浏览器实点
     - [x] 测试：smoke 202/202（不含 smoke_stepfun）、flutter analyze 0、flutter test 673 过 8 跳过、npm run build 过；截图测试需真中文字体重跑
     - [x] 发布 v2.95（commit + tag + push；不部署、不出 APK）
    - 遗留：部署后核对迁移结果；主聊天搜索命中项目对话时结果无 project_id（旧行为）；tokens.css `--pill-drop` 为对齐 App 保留
6a. **v2.94 主页三个 bug（第 6 项里拆出来，本轮做）**——进度如实记录：
   - [x] devlog 写全局决定 / 替换删除 / 成本（docs/devlog.md「2026-10-15 v2.94 主页三个 bug」，含三条根因调查结论）
   - [x] ① 天气面板重复：**根因是数据重复，不是渲染**。(a) 面板内容收的是整轮回复全部块，每一步说过的话各是一块（先写一遍→show_stats→再写一遍/被“继续”再补）→ 新 `worker.panel_blocks()`：文字只留最后一块、相同展示卡只留一张；(b) create_panel 不查重 → `task_store.panel_twin()`（同标题去标点 / 同指令即同一个，不建第二张，回告用 manage_home update）。Toyuis 没有“内置天气卡”（从没做过），天气只有面板一条路，无可删；不新增。smoke_manage_home 加查重 + panel_blocks 用例，相关 7 个 smoke 已过。**没做**：线上库已存在的重复面板没清（不碰 VPS）——部署后 `manage_home list` 看一眼，手动移除多余的；旧内容下次刷新按新规则重写。
   - [x] ② Composer 遮住最后一张面板：查明两端现有机制是对的（App FloatingFooter 量胶囊实际高度→MediaQuery.padding.bottom→PageBody；Web Page footer ResizeObserver→`--footer-h`，胶囊高已含安全区），本机 1080×2340 / 2560×1440 实渲 App 主页滚到底不遮；该 bug 是 v2.78 主页重做前报的。做了：新 `app/test/home_footer_test.dart`（手机含手势条、电脑宽屏各滚到底，最后一张卡底边 ≤ 胶囊顶边；已做变异验证——把留白改坏两条都红）；删 Web 三处 `var(--footer-h, 88px)` 写死兜底，check-arch 加第 6 条禁兜底。**没做**：Web 没能实际截图（本机 arm64 下不到 Chromium），只靠构建 + 代码核对；真机/手机浏览器未看。
   - [x] ③ 电脑端割裂 / 左半屏空：原根因是 v2.78 前 Web 宽屏两栏（v2.78 已改居中单列）；残留的宽版残路 `Page wide`/`.page-inner.wide`/`--content-wide`（只剩项目列表在用，≥1100px 时 720 宽列表贴在 1080 区域左边、右边空一块）**整条删掉**，所有页同一 720 居中。App 宽屏实渲是居中单列，无割裂；顺手统一 App 建议卡配图：窗口 ≥ `Layout.contentMax` 用 5:2（`Layout.offerImageRatioWide`，= Web ≥720px），手机仍 2:1（offer_media_test 加用例）。**没做**：宽屏顶栏左 + / 右头像贴屏幕两角、不跟内容列对齐——是否改要连同聊天双栏一起定，留作后续；Web 宽屏未实际截图。
   - [x] 测试 + 发布 v2.94：flutter analyze 0、flutter test 674 过（8 跳过）、npm run build 过（架构守卫 218 文件）、后端 smoke 201/201（不含需真密钥的 smoke_stepfun）；VERSION 2.94.0、CHANGELOG、tag v2.94、push。不部署 VPS、不出 APK（按 13:03 新规则，等用户开口）
5. ✅（v2.92.0 已做，存 app_settings 的 identity 一行而非 users 表——只有一个主人；详见 devlog 2026-10-15 v2.92）**v2.92 §P 名字与头像**：首次进对话由助手**在聊天里**问称呼和是否给助手取名（不做表单引导页）；不取名默认叫 Toyuis；`users.display_name`、`users.avatar`、`app_settings.assistant_name`；头像可上传，无图=纯色圆+首字母（复用 Avatar）；“我”页点名字/头像可改；助手名进系统提示词。**语气**：正式、不开玩笑，但初次打招呼可亲切。定稿开场：“你好，我是 Toyuis，很高兴为你服务。请问我该如何称呼你？如果你愿意，也可以为我取一个名字；不取的话，我就继续叫 Toyuis。”
6. home-redesign 剩余：E1 收尾（ListRow/ListGroup/PageHeader 统一、附件弹层高度）、E4 ImageStack + 震动反馈、连接器按钮诚实化 + OAuth 指南、“我的”页底部搜索。（天气重复 / 电脑端割裂 / Composer 遮挡三项已拆到 6a，v2.94 做完。）
   - **v2.97 E1 收尾进度（2026-10-15，按块如实记录）**：标准与删除清单见 docs/devlog.md「2026-10-15 v2.97 E1 收尾」（home-redesign.md 不在仓库，按代码现状归纳）。
     - [x] devlog：现状、标准、删除清单、成本、附件弹层根因
     - [x] App：`ListGroup`（GlassGroup 搬进 kit 改名，删 GlassGroup + 别名）/ `ListRow`（RowTile 改名，加 titleWidget/titleMaxLines/semanticLabel）/ `PageIntro`（并入 SubPageLine）；记忆 / 笔记 / 任务备忘三处手写行改用 ListRow；附件弹层高度修根因（来源 Column 缺 mainAxisSize.min 把弹层撑到全屏）
     - [x] Web：kit.tsx 新增 `ListGroup` / `ListRow`、`PageIntro` summary 可选；删 meRows.tsx 与 3 处手写 sub-line；迁了我的 / 个人资料 / 电脑 Pages 行 / 关于 / 偏好 / 钱包 / 反馈 / Pages / 密钥行 / 记忆 / 记忆笔记（手写 row/list 104 → 81 行）；check-arch 第 7 条只减不增
     - [x] 测试：flutter analyze 0、flutter test 678 过（8 跳过；新增 list_kit_test 3 例含旧名 / 手写行守卫，project_file_refs_test 加附件弹层高度 1 例并做过变异验证）、npm run build 过（架构守卫 216 文件，含第 7 条）、后端 smoke 202/202（不含 smoke_stepfun；smoke_stop 与 npm build 同时跑时 5 秒等待超时一次，单跑过；后端本版未改）
     - [x] 发布 v2.97：VERSION 2.97.0、CHANGELOG、check_version、commit + tag v2.97 + push（不部署、不出 APK）
     - [x] v2.98 devlog 先写决定与删除清单（「2026-10-15 v2.98 E1 Web 收尾」），再改代码
     - [x] v2.98 Web：kit.tsx ListRow 补 href / disabled / role / iconClass、ListGroup 补 label / role；11 个文件迁完并从 RAW_ROWS 删除（登录设备、安全、按模型用量、OAuth 引导、自动选模型、用量错误行、项目文件、存成文件、对话文件、浏览器登录、主机模式），电脑详情 / 电脑状态 / 连接器 / 技能 / 任务 / 运行记录 / 备忘 / 最花钱对话 / 文件选择部分迁移；所有手写 `div.list` 改 ListGroup；删 `.conv-files` 动画规则。手写 row/list 81 → 23 处、23 → 12 个文件
     - [ ] Web 仍登记 12 个文件 23 处（check-arch RAW_ROWS 每条注明原因）：分体行（技能 / 任务开关、MCP 移除、收件箱菜单、电脑服务 / 任务取消）、带细条的富内容行（电脑状态 / 内存 / 磁盘写入 / 配额、最花钱对话）、运行记录与备忘、今天时间线、回复语言（常驻 aria-live）、文件选择（role=checkbox）——要收得先给 ListRow 定“分体主体”与“正文附加槽”的版式，非本轮范围
     - [x] v2.98 App 6 个登记文件逐个评估：全部是富内容行（抽屉对话 / 项目行、电脑状态 / 内存磁盘行、运行记录、用量分享行），无简单行可并，保留登记，理由写进 devlog；App 未改代码
     - [x] v2.98 测试 + 发布：flutter analyze 0、flutter test 678 过 8 跳过、npm run build 过（架构守卫 216 文件）、后端 smoke 202/202（不含 smoke_stepfun，串行）；VERSION 2.98.0、CHANGELOG、check_version、commit + tag v2.98 + push（不部署、不出 APK）
     - [ ] 浏览器 / 真机截图核对（本机无 Chromium；App 明暗、Web 手机宽度）
     - [ ] v2.98 不做：E4 ImageStack + 震动、“我的”页底部搜索、连接器 OAuth（见 2a）
   - **v2.99 进度（2026-10-15，按块如实记录）**：决定、删除清单、参考来源见 docs/devlog.md「2026-10-15 v2.99」（home-redesign.md 不在仓库，按 Hark 公开表现 + 代码现状归纳）。
     - [x] devlog：现状、决定（ImageStack / 震动 / “我的”页搜索是否与现有搜索重复）、删除清单、成本、参考来源
     - [x] E4 ImageStack（两端同构，替换横排小图条 + 单张大图）：一个图片块 = 一摞（最上面 4:3 + 后面最多两层右下错开 ±2° + 底色薄纱 + 发丝边 + “N 张”），首次扇开（只 transform，reduce-motion 直接到位）；点开全屏查看器（`ui/sheets.dart showAppViewer`）左右滑翻页，App 每页捏合 / 双击缩放、放大时锁翻页（借鉴 photo_view），竖图横图完整显示，坏图有提示。App `blocks/image_stack.dart`，Web `blocks/ImageStack.tsx`（← → / Esc），token 两端对齐
     - [x] 震动：`ui/haptics.dart` 唯一入口（tap / press），9 处散落调用并入；新增只在发送、下拉刷新触发、开关切换（新 `AppSwitch`，7 处 Switch 并入）；`test/haptics_test.dart` 守卫。Web 不做振动（理由见 devlog）
     - [ ] “我的”页底部搜索：已判断与历史抽屉的对话搜索不重复（找设置 vs 找对话），方案定为“我的”页唯一的设置搜索 + 两端静态索引 + 底部浮动胶囊；按第二节第 13 条“宁可少做一块”留下一版
     - [x] 测试：flutter analyze 0、flutter test 682 过 8 跳过（新增 haptics_test 3 例、content_blocks 图片一摞 2 例含双击放大锁翻页）、npm run build 过（架构守卫 217 文件）、后端 smoke 202/202（不含 smoke_stepfun；smoke_preview_ws 并行时端口冲突一次，单跑过；后端本版只改版本号）
     - [x] 发布 v2.99：VERSION 2.99.0、CHANGELOG、check_version、commit + tag v2.99 + push（不部署、不出 APK）
     - [ ] App 明暗只在临时截图测试里看过（未提交）；Web 未在浏览器实点 / 截图（本机无 Chromium）；真机手感（扇开、翻页、震动强弱）未验
   - **v3.0 “我的”页底部设置搜索进度（2026-10-15，按块如实记录）**：决定、删除清单、参考来源见 docs/devlog.md「2026-10-15 v3.0」。**版本号 2.99 之后因 brand/sync.py 构建号规则（功能轮 ≤ 99）进位到 3.0.0，不代表破坏性改动**（协议 / 接口 / 数据库 / MIN_CLIENT 不变）。
     - [x] 核对：全仓没有已存在的设置搜索，无需合并；devlog 先写决定、参考（Apple 设置搜索在底部、LINE 滚到该项并闪一下）、删除清单
     - [x] App：`features/me/me_index.dart` 索引 + 匹配；“我的”页底部玻璃搜索胶囊（FloatingFooter）+ 结果 / 无结果态；`SpotlightScope` / `Spotlight` 定位并闪一下（复用 FlashHighlight）
     - [x] Web：`features/me/meIndex.ts`；MeScreen 改用 `Page footer`；`?focus=` 定位（Page 内统一处理）；`.msg.flash` 并入通用 `flashOnce` / `.flash`
     - [x] 测试 + 发布 v3.0（2026-10-15 18:40）：flutter analyze 0、flutter test 695 过 8 跳过、npm run build 过（架构守卫 218 文件）、后端 smoke 203/203（不含 smoke_stepfun；smoke_jobs 全量串行偶发超时、单跑过）；wip-v3.0 合入 main，tag v3.0，push。不部署、不出 APK
     - [ ] 未做：浏览器 / 真机截图核对（App 明暗、Web）；真机手感（定位滚动 + 闪一下）
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
| 连接不了 GitHub、Gmail；点一下登录再确认授权 | ⚠️ v2.90.2 按钮诚实化 + 配置引导已提交；v2.96 连接器 + 保险箱合成“连接的账号”一页（已提交，未部署、未真机看）；OAuth 应用未注册、未部署 | 见第五节 2a、docs/oauth-setup.md |
| 删了的对话又蹦出来；子对话（定时任务运行对话）不要放主列表 | ⚠️ v2.75 修了，需在服务器上确认 | devlog v2.75 |
| CPU 60%～100%、内存占用高，要优化 | ❓ | 服务器上 `docker stats` 核实；APK 构建已改为限流脚本 |
| 一个项目就是一段对话，项目内不能开多个会话（10-15 12:48） | ⚠️ v2.95 已做并提交（点项目即聊天、≡ 项目切换、旧多段迁移合并可回退），未部署、未真机看 | 第五节 5b，devlog v2.95 |
| 电脑端主页割裂、左边空一大块；天气报告重复 3 次；输入框遮住面板 | ⚠️ v2.94 已修并提交（面板只收结果 + 面板查重；删宽版残路；输入框留白加回归测试），未部署、线上已有的重复面板未清、未真机看 | 第五节 6a，devlog v2.94 |
| 主页对比 Hark“又乱” → 整体重设计 | ⚠️ 进行中 | home-redesign A–E；E1 收尾 v2.97 做了大半、v2.98 收完能收的 Web 行（两端 ListRow/ListGroup/PageIntro 统一；网页剩 12 个文件 23 处富内容 / 分体行登记保留，App 6 个富内容行保留，见第五节第 6 项）；E4 ImageStack + 震动 v2.99 已做 |
| 历史抽屉被顶栏压住“还叠在一起” | ✅ v2.78 | |
| 步骤耗时都显示 0.0 秒、步骤默认展开很乱 | ✅ v2.79 | |
| 电脑端回复滚动 bug（往上看会被拉回底部） | ✅ v2.79 | |
| 服务器状态是不是真实的 | ✅ v2.85（写清是沙盒容器 + 整台服务器一行） | |
| “我”页太长不好看，学 Hark 个人页 | ✅ v2.81（底部搜索 ❌，v2.99 已定方案未做） | 第五节第 6 项 |
| 加号附件弹层很丑 | ⚠️ v2.97 修了高度（根因：来源 Column 缺 mainAxisSize.min 把弹层撑满全屏，已加回归测试），未部署、未真机看 | 第五节第 6 项，devlog v2.97 |
| Hark 发图片的排布（ImageStack） | ⚠️ v2.99 两端已做并提交（一摞 + 全屏翻页 + 缩放），未部署、未真机 / 浏览器看 | 第五节第 6 项，devlog v2.99 |
| 每句话单独回复并关联引用 | ✅ v2.87 + v2.90 | |
| 用新图标 | ✅ v2.80 | |
| 字体丑、整体不优雅，学 Hark、找 skill/开源学 | ✅ v2.83 字体；⚠️ 整体质感持续打磨 | hark-elegant-ui 规则 |
| 接管页点不到、画面小 | ✅ v2.82 | |
| 点哪条气泡显示哪条的时间 | ✅ v2.84 | |
| 长按聚焦菜单 + “回复”这条 | ✅ v2.87 | |
| 软件名 Toyuis、做好版本管理、名字上面还写 assistant | ✅ v2.86 | |
| 用户气泡不要白色，Hark 偏灰 | ✅ v2.90.1 改灰，2026-10-15 截图 + 对比度验收（气泡 13.8:1 / 深色 14.8:1） | 第五节 2 |
| 网页“选档”（模型选择）UI 太拉、越改越丑 | ⚠️ v2.87 改过，未让用户确认 | devlog 18:40/18:56 |
| 网页显示动不动就断、不流畅，学 Muse/Dots/browser 类项目 | ✅ v2.89 实时推流 | |
| 截图 1000035389“排版怎么回事”、1000035390“这么割裂” | ❓ | 看 files/uploads 原图核对 |
| 回复里有工具调用符号、排版随意；文案口语化不专业 | ✅ v2.88 | |
| 发送时气泡往上弹一下 | ✅ v2.88 | |
| 动效既要有又要流畅 | ✅ 规则（只动 transform/opacity） | |
| 项目页左上角 ≡、对话条目带状态、进场/上滑浮出总结标题、细腻有小动效 | ⚠️ v2.91 已部署（随 v2.92）；v2.93 按 Hark 重做（顶栏常驻、+↔≡、大字项目名+汇总状态、项目内只列对话）已部署、未真机看 | §N / §Q，devlog 2026-10-15 |
| 手机网页弹层被顶栏/输入框/浏览器工具栏挡住，App 弹层也查 | ⚠️ v2.93 已修（Sheet portal + visualViewport + 按钮行常驻；App useSafeArea + 提交钮钉底），已部署，未真机验 | §Q |
| 运行中能继续发，意思相近合并回复，要有判断 | ✅ v2.90；⚠️ 准确率重评未做 | 第五节 3 |
| 名字头像自定义，首次正式而亲切地问，不取名叫 Toyuis | ✅ v2.92.0 已部署，真模型 set_names 已验；首次问候真机未看 | §P（v2.92） |
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

### App 截图回归（test/screens/shots_test.dart）也修好了（2026-10-15）
同样卡在「存到项目文件」：v2.90 起它在回复的操作菜单里，不是 tooltip 了。已改成长按那条回复 →（项多时先点「更多」）→ 点 `saveReplyLabel`（「存成文件」）；选择弹层标题现在是「存到哪里」（不是「存到哪个项目」）。
- Windows 上跑：`SHOTS=1`、`SHOTS_FONTS=<目录>`、`SHOTS_OUT=<目录>`、`TZ=Asia/Shanghai`、`FLUTTER_ROOT=<flutter sdk>`，`flutter test test/screens/shots_test.dart` → **一次 62 张（明/暗 × 30 屏）**。
- 这台机器没有 Noto 字体（`fonts.google.com` 在国內也下不动）：临时用 `C:\Windows\Fonts\simhei.ttf` 当 `NotoSansSC.ttf`、`seguiemj.ttf` 当 `NotoEmoji.ttf` 顶一下。**颜色是 token 出的，绝对准；字形会跟正式截图有差异**，所以这组图用来看颜色/排版，不要当 design-refs 提交。

### 第五节 2「用户气泡验收 + a11y ≥4.5」这一轮做完了（2026-10-15）
- 量出来的数（`test/a11y_test.dart` 现在会守着；网页 `scripts/check-contrast.mjs` 同一批配对，`npm run build` 里跑）：
  气泡字 onUserBubble/userBubble 浅色 **13.80:1**、深色 **14.84:1**（Hark 灰那版 v2.90.1 完全达标，不是「差不多」）。
- **顺手抓到一个真问题**：浅色 `warning` = `#B86E00` 到处当小字用（`bodySmall`/`labelSmall`），对底色只有 **3.62:1**、对白卡 3.99:1——不到 AA。已压深到 `#9A5B00`（对底色 4.93、白卡 5.43），App `tokens.dart` 与网页 `tokens.css` 同步改。
- 新增守门：App 侧 6 个测试（对比度表 + 气泡/回复卡画出来也达标 + 编辑条/引用条/长按聚焦跟随同一套色），网页侧 `check-contrast.mjs`（14 对 × 2 套主题 **且校验两端同值**，改了一边忘另一边会红）。
- 截图：App 62 张（`%TEMP%\shots-app`）、网页 126 张；对照图放在 `shots-2.90.2/`（`app-chat/` 看气泡，`warning-aa/` 看警示色改前改后）。
- **已发 v2.90.3 并部署到 VPS**：`/api/version` = 2.90.3（build 29003），线上 CSS 里 `9a5b00` 出现 1 次、`b86e00` 0 次（颜色确实上线了），7 个容器都在跑。tag `v2.90.3` = `615b656`。

### 网页守卫不能读 App 的文件（第一次部署就栽在这）
`frontend/scripts/check-contrast.mjs` 一开始写成必须读 `../app/lib/theme/tokens.dart` 做两端同值校验 → 镜像构建
失败 `ENOENT '/app/lib/theme/tokens.dart'`：**网页镜像的构建上下文就是 `frontend/`，里面根本没有 `app/`**。
现在改成：对比度那半永远查（只要 tokens.css）；两端同值那半读得到才查（完整仓库/本地跑 build），读不到打印一行说明。
以后往 `npm run build` 里加脚本，先想清楚「镜像里有没有这个文件」。

### 第五节 2 之外的下一步（按第五节顺序）
- 第五节 3「录入准确率重估」、4「§N 项目页 v2.91」、5「§P 名字头像 v2.92」、6「首页重设计 E1/E4/天气去重」、7「子对话不进主列表（VPS 验）」、9「SearXNG 实测 + 关掉 VPS 密码登录」、10「CORE #9 多文件读」。
- 第五节 2a 只有你能做：GitHub / Google 后台注册 OAuth 应用 → 填 VPS `.env` → 重启 → 真机走一遍授权。

### 这台机器上别做的事（我踩了）
- **不要用 PowerShell 的 `Get-Content`/`Set-Content` 改 Dart/CSS 源文件**：默认编码会把中文注释整片写成乱码（我这轮把 `tokens.dart` 弄坏过一次，`git restore` 才救回来）。要改就用编辑工具，或 `git apply`。
- 别用 `git archive` 默认行尾打部署包（见上面 CRLF 那条）。

### 第五节 8「Web 截图重拍」已经修好（2026-10-15 凌晨）
`frontend/scripts/shots.py` 之前根本跑不完：卡在项目对话那一步。原因是**假接口缺数据 + 定位器跟着 UI 漂了**，不是浏览器问题。现在整条流程能跑到底：`SHOTS_CHANNEL=chrome <backend 的 venv python> scripts/shots.py <输出目录>` → **一次出 126 张（桌面/手机 × 明/暗 × 30 多屏），退出码 0**。修的东西：
- 补假接口：`/api/preferences`（缺了它「我的 → 偏好设置」「用量」「项目里对话」三张图是同一张白屏）、`/api/projects/pr1/computer`（缺了它项目首屏白屏，形状照 `lib/computer.ts` 的 `ComputerStatus`）。
- 「存到项目文件」早已收进回复的 ⋯ 菜单：定位器改成先点「这条回复的操作」再点菜单项「存成文件」；而且**必须挑那条有 markdown 的回复**（假数据里的 `data-msg-id="m2"`），最后一条 assistant 常常是订单卡，没有这一项。
- 那个 ⋯ 平时 `opacity: 0`（`.msg:hover` / `:focus-within` / 触屏设备才显形，`chat.css` 里写了 `@media (hover: none)`），所以脚本里要**先 hover 再 click**，否则第一次点会落空。
- 输入框占位符带品牌名（`给 Toyuis 发消息`，来自 `brand.ts`）；头像颜色 v2.81 起搬到了「偏好设置」。
- 访问日志不再往 stderr 灌（`_QuietHandler`），跑完了就是干净的退出码 0；跑完/跑挂都会打印「请求了但没有假数据」清单。
- 剩下的（不影响跑通，只是那几屏偏空）：`GET /api/connectors/mcp`、`GET /api/memory-notes` 还没有假数据。




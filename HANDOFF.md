# Toyuis 交接文档（2026-10-19，v3.5.5）

> **给每个接手的 agent**：先读第二节宗旨（1–21 条）。用户在对话里说出的任何纲领性要求，当轮用明确、不会被误解的话（不必照抄原话）带日期补进第二节，这是硬规矩（见第 16 条）。


> 写给接手的 AI / 开发者。先通读本文件，再读 `docs/devlog.md` 末尾、`docs/home-redesign.md`、`CHANGELOG.md`。

## 〇、最新交接（2026-10-19，接手先读这一节）

**v3.5.5 = 3.5.4 + 步骤胶囊 + 一批收尾（wip/v3.5.1 分支，版本号 3.5.5 / build 30505，tag v3.5.5；未部署服务器，服务器仍 3.5.1；APK toyuis-3.5.5-arm64.apk 在 VPS 编，取回 /workspace/work/apk/）**。内容：
- 空态建议被输入框挡（492dc16）：两端复现查根因 = 浏览器标签页多报 44px 顶部安全区（v3.5.1 已修），加回归守卫（App chat_empty_footer_test + Web shots.py 断言）。
- Web 一级页左钮随页横滑（798394a，= App）：顶栏左钮槽移进每层页面（AppShell ShellView/LeadSlot），进出“我的”跟本页 transform 走；分段宽度在“我的”不再 252↔300 跳。
- NOTICE 补两端（1a8bb5e）：流光着色器参考 mesh_gradient（MIT，Ben Fornefeld）一行，未复制代码。
- Flyme 高刷提示条件显示（6f70b74）：滑动中系统刷新率最低值 < 90Hz 才出，读不到不出。
- 步骤胶囊照 Hark（c8ebd7f，测试跟进 0445600；第二节 31）：回复下方一颗胶囊只显示当前步骤、换步原地交叉淡入淡出，完成收成“N 个步骤 · 用时”，点开看完整时间线；删回复上方步骤行与回复卡里逐条“正在…”小条，运行中的工具不再另起回复卡。
- **未决，给用户定**：
  1. 两端空态不一致：App 是胶囊、Web 是卡，统一成哪种？
  2. PlanBlock / DelegateBlock 要不要也收进步骤胶囊？
  3. 接管点击修复在分支 wip/takeover-input（30935d1）待合并：需要把线上浏览器镜像升到 Playwright ≥ 1.49（新无头模式），等用户定是否升级 / 部署。合并前不要动 work/wt-takeover。
- 真机未验证：步骤胶囊的手感、Web 左钮横滑。

以下为 v3.5.4 交接：


> **2026-10-19 真机结论（魅族 20，v3.5.4，4 次性能自检）**：高刷已生效。滑动中系统刷新率 120Hz（最低=最高），所有变体 ≈121fps、超预算 0%，光栅均值 1.3–2.8ms、p90 ≤3.7ms，UI 0.3–0.8ms。A–H 差异在噪声内 → 视觉层（壁纸/模糊/渐隐/卡片）都不是瓶颈，**不要为性能删效果**。根因确认是 3.5.3 及以前被 Flyme 锁 60Hz；生效的是 `Surface.setFrameRate(ALWAYS)` + `preferredRefreshRate`。请求 144 时系统只给 120（Flyme 普通应用上限，推断），可接受。仅一次 A 变体首跑 49fps/最大 12.1ms，其余三次正常，判为首跑预热/手动触碰，不追。卡顿问题可关闭；服务器仍 3.5.1。

**v3.5.4 = 3.5.3 + 强制高刷多管齐下 + 自检采样刷新率（wip/v3.5.1 分支，版本号 3.5.4 / build 30504，tag v3.5.4；未部署服务器；APK toyuis-3.5.4-arm64.apk 在 VPS 编）**。
- **真机结论（魅族 20 / Flyme，3.5.3 自检四次截图）**：系统当前模式 4 · 60.0 Hz；窗口请求模式 2（144Hz）；可选 120/144/90/60；Flutter 报 120Hz。每变体 2.5 秒约 153 帧 ≈ 61fps → 屏幕实际跑 60Hz，preferredDisplayModeId 被 Flyme 忽略。各变体结果双峰随机：要么光栅均 ≈3.5ms、p90 5ms、0% 超预算；要么均 ≈10–11ms、p90 正好 16.7ms；哪个变体落哪边每次不同（A 全开有一次 3.4ms/1%，H 全关有一次 10.9ms/60%）。→ **没有哪一层是 GPU 瓶颈**，真实绘制 ≈3–4ms；16.7ms 是 60Hz 下交换链等 vsync 的反压被计进 rasterDuration。**根因 = 屏幕被锁 60Hz**（外加 Flutter 以为 120Hz 按 8.3ms 节奏出帧、与 60Hz 显示不匹配导致不均匀）。所以不要再按层砍视觉。
- MainActivity.kt 三招都做：① preferredDisplayModeId（保留）② window.attributes.preferredRefreshRate = 最高 Hz ③ API≥30 遍历 decorView 找 FlutterSurfaceView，对 holder.surface 调 setFrameRate(maxHz, FRAME_RATE_COMPATIBILITY_DEFAULT)，API≥31 用带 CHANGE_FRAME_RATE_ALWAYS 的重载；onCreate / onResume（含下一帧 post）/ onWindowFocusChanged(true) / surfaceCreated / surfaceChanged 后都重设。Flutter 3.47 引擎（FlutterEngineFlags.java）没有帧率相关 manifest meta-data，未加。
- 自检：滑动中每 200ms 经 MethodChannel `refreshRate` 采 display.mode.refreshRate，结果页显示“滑动中系统刷新率：最低/最高”、每变体 fps = 帧数/实际时长、窗口请求刷新率与 Surface 帧率状态；顶部提示“Flyme 若仍 60Hz：系统设置 → 显示和亮度 → 屏幕刷新率…给 Toyuis 选高刷”（魅族 20 的确切菜单名没查到可靠来源，写的是通用说法，待用户确认）。
- **下一步**：用户装 3.5.4 跑自检，看“滑动中系统刷新率”是否到 120/144、fps 是否 ≈120+。仍 60 → 只能靠用户在系统设置里开，或再查 Flyme 白名单机制。

以下为 v3.5.3 交接：

**v3.5.3 = 3.5.2 + 性能自检（wip/v3.5.1 分支，版本号 3.5.3 / build 30503，tag v3.5.3；未部署服务器；APK toyuis-3.5.3-arm64.apk 已在 VPS 编出）**。内容：
- 性能自检（b8041ed）：关于页打开性能浮层后出现“性能自检 ›”，A–H 分层逐层开关测真机光栅耗时（core/perf_probe.dart、features/me/perf_probe_screen.dart，MainActivity.kt 新 MethodChannel）。
- 用户截图（3.5.2，“我的”页）：Raster avg 15.8ms / max 17.1ms，UI 0.4ms → 瓶颈在光栅不在 UI。
- **下一步**：等用户真机跑完 A–H 自检的结果，再定修哪一层；结果出来之前不要盲改。

以下为 v3.5.2 交接：

**v3.5.2 已提交（wip/v3.5.1 分支，版本号 3.5.2 / build 30502，tag v3.5.2；未部署服务器；APK toyuis-3.5.2-arm64.apk 已在 VPS 编出，等用户真机验证）**。内容：
- 项目 = 目录（两端，83869bf App / dcde221 Web，照 Hark，第二节 29）：删项目切换胶囊（App project_switcher.dart、Web ProjectSwitcher.tsx 删除），顶栏下一行行项目名，进去左上 ☰ 回目录；聊天历史同为目录式。
- App 卡顿（魅族 20，第二节 30；诊断见 /workspace/work/jank-diagnosis.md 与 devlog「v3.5.2 真机卡顿」）：
  - 高刷新率：MainActivity.kt 在同分辨率显示模式里选最高刷新率设 preferredDisplayModeId（onCreate + onResume）。**MainActivity.kt 由这次 APK 构建首次编译通过。**
  - 壁纸 1/4 离屏贴图（d0ad7f5）：每 33ms 时钟步只在 1/4 分辨率跑一次 sky.frag，整屏 / 渐隐条用 sky_blit.frag 双线性放大贴图；滑动时暂停流光时钟。
  - 盖住不画（331b395 SkipWhenCovered）：外壳壁纸被不透明子页完全盖住时不画；PulseDot 改 30fps Timer；隐藏性能浮层（关于页入口，core/perf_overlay.dart）供真机看 UI / Raster 柱。
  - 沙盒软件光栅每帧 39–44ms → 约 12ms。
- **待真机验证（必须）**：魅族 20 上是否真跑到 120/144Hz、滑动是否流畅（打开性能浮层截图 UI / Raster 柱）；沙盒数字不算验收。
- 仍未决 / 未做：WS 几秒就断（部署后看 ws.py 日志）；主要聊天 + 旁聊（第二节 25，先出设计）；v3.5.1 列的未决视觉选择照旧。

以下为 v3.5.1 交接：

**v3.5.1 已合并完成（wip/v3.5.1，版本号 3.5.1，tag v3.5.1；未部署、未出 APK，按第二节 12 条等用户开口）**。内容：
- 弹层全屏（两端：抽屉 / 半屏弹层 → 整屏落在壁纸上，第二节 24）；新建面板 = 主页整屏“发起”态（两端，删白底弹层）；“我的”= 第四个标签（两端横滑、顶栏常驻）。
- 卡片 / 浮层半透明 token（App `Palette.card` / `Palette.glass` = Web `--card` / `--glass`，第二节 27）。
- 五色流光（第二节 28）：App 单片元着色器（app/shaders/sky.frag），Web WebGL（frontend/src/lib/skyGl.ts），同一核心、同一色表。
- 电脑页一屏概览 + 子页（两端）：412×915 上 maxScroll 3522→94，轮询重建 689→59（只重建变化的行）；用量页一卡概览 + 前 3 / 全部 ›（两端）。测量见 devlog「v3.5.1 电脑页 / 用量页精简」「v3.5.1 五色流光」。
- 全量校验：flutter test 787 过 / 11 跳过；Web 全过（tsc / npm test / build 含架构守卫 + 配色守门）。
- **待真机验证**：流光的 GPU 开销（App profile 光栅、真 GPU Chrome）与各页真机滚动手感；以上测量都是沙盒软件光栅 / 无头 Chromium 4× CPU。
- **未决视觉选择（列给用户，或照 Hark 定）**：“我的”页行高 64 / 用量卡尺寸（Hark 61 / 83，现在要滚一小段才见“退出登录”）；头像当前项外环样式；新面板胶囊样式；App 平板弹层是否改成 Web 桌面那样的居中卡。
- **WS 几秒就断**：ws.py 已有断开日志（谁断 / 断开码 / 时长 / UA），要部署后看日志定因。
- 下一项：主要聊天 + 旁聊（第二节 25，先出设计给用户确认）。

以下为 v3.5.1 过程记录：


**v3.5.0 已部署（2026-10-16 22:25，/api/version 3.5.0；备份 /root/app-v321-backup.tgz、/root/env.bak.v35）+ APK toyuis-3.5.0-arm64.apk 已交付。现在 wip/v3.5.1：用户真机反馈一批（22:27–22:48），进度：**
- [x] 半屏抽屉 → 全屏（第二节 24）：Web 窄屏 .convs 铺满、落在壁纸上、聊天区淡出、删 .glass-drawer / 遮罩 / ×（左上钮开关）；App FullDrawer（glass.dart）铺满 + Backdrop。截图 App 已看；Web 待截图
- [x] 所有半屏弹层 → 全屏（第二节 24，2026-10-17）：Web 43366c7（手机 .sheet 全屏、桌面居中卡）；App ui/sheets.dart `SheetPage`（壁纸 + 圆钮 ‹ + 居中标题、内容整页滚、表单提交钮钉底、上下 BackdropFade、只淡入、opaque 路由下面不绘制、无 BackdropFilter），GlassSheet / 把手 / showModalBottomSheet 已删；App 平板也全屏（Web 桌面是居中卡，要不要对齐待定）。真机光栅未测
- [x] 浏览器里顶部凭空多约 44px：手机浏览器报了 safe-area-inset-top → 统一 --sat（tokens.css），浏览器标签页里为 0
- [x] Web 计划钮手机上点了看不出：开着时显示“计划”+ 细边（= App）
- [ ] 主页空态建议卡被输入框挡（待查，可能顶部空白修掉后就够）
- [x] 主页左上 + 新建面板（已合并 99b4ee9）：照 Hark 改成进入整屏毛玻璃“发起”态（已有的 home-focused 那套）+ 输入框上方“创建一个新面板”、占位词轮播面板示例；删白底 NewPanelSheet / new_panel.dart 弹层（最近移除保留，放在建议位置）
- [ ] WS 几秒就断：服务器本机 / 经 Caddy 探针 170 秒不断 → 断在客户端或手机网络；ws.py 已加“谁断的 / 断开码 / 活了多久 / UA”日志，部署后看
- [ ] App“我的”页及其他页真机滑动卡（GPU）：拆每帧合成层（沙盒侧已做：拉伸重绘边界、SettleOpacity、电脑页 / 用量页精简；真机未验证）
- [x] “我的”页 = 第四个标签（用户 22:49 附 Hark 截图）：顶部导航胶囊保留（主页 / 聊天 / 项目都不选中，头像为当前项），点头像像切标签一样整页从左往右横滑过去，点回别的标签再滑回；两端同改
  - **App 已做（wip/v3.5.1-me）**：/me 成 StatefulShellRoute 第四个分支（app.dart），“我的”套 ShellPage，删自带 Backdrop / 顶部渐隐 / 返回钮；顶栏 index=3 时滑块淡出、头像外圈 pillOn 环亮起；`ShellBranches`（app_shell.dart，navigatorContainerBuilder）进出“我的”整页横滑（只 transform，减少动态直接切），三个分段之间照旧直切；返回键在“我的”回主页分支。主页卡片 / 聊天块里 push('/me/…') 照旧叠在当前页上、返回回原处。决定见 devlog「v3.5.1 “我的” = 第四个分支」。
  - **Web 已做（wip/v3.5.1-me）**：TopBar `isShellRoot` 加 /me，“我的”顶栏常驻：滑块原位淡出（`.segments-thumb.off`，位置记在模块级 lastSegment）、头像外圈 `--pill-on` 环淡入（`.avatar-tab.on`）+ `aria-current="page"`；MeScreen 删返回钮 / “回到主页”× 和“我的”专用渐隐，改用一级页 `.shell.has-bar` 同一套；AppShell `ShellViews` 进出“我的”整页横滑 360ms（离场页元素 + location 冻住多留一段，只动 transform，渐隐条壁纸副本反向平移抵消；reduce-motion 直接切），三个分段之间、子页进出不变；SkyFade 定位改量布局位置（不受 transform 影响）。决定 + 测量见 devlog「v3.5.1 “我的” = 第四个标签（Web）」。
  - **待做**：412×915 上“退出登录”和“关于”现在要滚一小段（顶栏常驻多让出 72px，行高 64 / 用量卡 98 比 Hark 61 / 83 高、且多一行“我的电脑”），要不要收紧行高 / 卡高待定；两端真机看横滑手感未验证；Web 一级页左上按钮（ShellLead portal 进顶栏）横滑时不随页滑（App 随页滑），未改。
- [x] 卡片不要纯白（用户 2026-10-17，第二节 27）：两端卡片 = 半透明灰白假玻璃，同一 token（App `Palette.card` / Web `--card`），减少透明度回实色；浅色 danger / warning 压深一档保卡上小字 ≥ 4.5；两端对比度守门加“卡叠壁纸”一档。决定 + 取样 + 测量见 devlog「v3.5.1 卡片 = 半透明灰白假玻璃」。未验证真机。
- [x] 浮层也不要近乎纯白（用户 2026-10-18，第二节 27）：两端 glass token 降到 Hark 实测（浅 50% 白 / 深 76% 炭灰），透出壁纸；网页三处不模糊却读 --glass 的改读 --card（= App）；glassSheet 仍在用（表单弹层 / 对话框 / 菜单）不删；两端守门加“浮层叠壁纸 / 卡 / 卡上墨色”一档。见 devlog「v3.5.1 浮层玻璃透出壁纸」。未验证真机。
- [ ] 之后：主要聊天 + 旁聊（第二节 25，先出设计）
**v3.4.0 已发版：wip/v3.4 合并进 main、tag v3.4、已 push。服务器仍是 v3.2.1，未部署（用户明确说“更新服务器”才部署）；未出 APK。**
- v3.4 内容（决定与测量见 devlog「v3.3 视觉验收」「后端偶发测试失败查根因」「“我的”页顶部渐隐」「v3.4 验证」）：
  1. [x] 视觉验收修浅色白天壁纸下半屏发灰（两端 #C0D4E2→#EBDBBF）。
  2. [x] “我的”页顶部渐隐（两端）：复用 BackdropFade / SkyFade，无新增整页离屏层，搜索胶囊仍独立毛玻璃。截图 App 明暗×白天/夜间×首屏/中段/底部、Web 再×手机/桌面全看过。帧耗时：App perf_frame_test 新“我的”滚动用例 backdropLayers=2、shaderMaskLayers=0、fadeRebuilds=0，CPU 中位 3.0–3.5ms（临时退回基线 3.3–3.6ms）；Web 4×CPU 无头 Chromium 开/关渐隐 median 16.7ms、p95 ≤16.8ms、>20ms 帧 0。
  3. [x] 后端偶发失败根因（run.sh 启动/取消竞态是产品 bug，其余三处是测试替身/等法/端口竞态）。验证：smoke_jobs / smoke_preview_ws / smoke_reply_quote / smoke_stop 各串行 20 次全过，4 份并行各 10 次全过（85 秒）。**VPS 真沙盒镜像实测**（assistant-sandbox:latest 临时容器，按沙盒 runner 的 `setsid -f bash run.sh` 启动，测完已删）：旧 run.sh “启动后立刻取消”15/15 取消落空、“标记先于启动”15/15 落空；新 run.sh 三种时序 45/45 全部取消成功、无残留进程；正常任务退出码/日志正确。
  4. [x] smoke_stepfun 不是“需真密钥”（全是模拟），以前一直被跳过、断言已过时（WS 事件多了 turn_id / seq）→ 改为只比内容，纳入全量，**后端 smoke 现在 203/203、不再跳任何一个**。
  5. [x] **真模型 E2E**（用户 2026-10-16 19:08 同意花 token）：VPS 上用 app-backend 镜像临时容器跑 wip 代码的 `tests/live_stepfun.py`（密钥只在服务器 .env 里传进容器，没出服务器）：工具调用、带工具结果作答、每次调用记账、朗读→识别 往返 4 项全过。
- 发版前全量校验（最终代码）：flutter analyze 0；flutter test **735 过 / 9 跳过 / 0 失败**；npm run build 过、npm test 14/14；后端 smoke 202/202 + smoke_stepfun 单跑过。
- **仍未验证**：真机 Flutter profile 光栅耗时、真 GPU Chrome trace、真机/真浏览器看新渐隐与返回那一帧；新 run.sh 在线上沙盒容器（sbx-*）里的真实运行要等部署后看。
- **视觉验收 4 处不一致：用户 19:34 让照 Hark 定（第二节第 21 条）**，排在 v3.5 做：①子页标题两端改 Hark 式悬浮小胶囊（App 改）；③“退出登录”两端整行浅底条——**v3.5 已做（两端，见 devlog）**；④Web 项目列表收紧到 Hark / App——**v3.5 已做（去 ⋯，菜单 = 右键 / 长按聚焦菜单）**；②浅色夜间照 Hark 改成蓝→金——**v3.5 已做（fb3f9a6 第一版；第二版调浓 + 次要字压深在 wip 提交里）**。①子页标题——**v3.5 已改成 Hark 子页样式（两端）**：圆玻璃返回钮 ‹ + 居中裸字标题 + 右侧动作收进一颗玻璃胶囊，整宽胶囊删掉；App `GlassAppBar`（NavigationToolbar 真居中，返回钮规则同 AppBar），Web `.page-head` 三栏 1fr auto 1fr + `.page-head-actions`，子页打开 `.sky-fade-page` 渐隐（标题没底了）；App“我的”页返回钮同换 ‹。flutter test 736 过 / 9 跳过、analyze 0；Web tsc / 14 测 / 架构守卫 / build 过；截图对照 work/subpage-hark.png。Web 4×CPU：子页 >20ms 帧比旧版多（渐隐条的成本，拆因见 devlog），降到和一级页同一水平，median / p95 不变；App 子页帧耗时、真机仍未测。**v3.5 这批（夜间第二版 + 子页胶囊 + 退出登录条 + Web 项目列表）校验**：flutter analyze 0、flutter test 735 过 / 9 跳过；Web tsc、npm test 14/14、架构守卫、配色守门过；Web 138 张 + 流光 128 张截图已看；4× CPU 手机视口滚动（主页 / 我的 / 项目 / 聊天，壁纸在动）新旧都是 median 16.7ms、p95 ≤16.8、>20ms 帧 0。App 真机 profile 仍未验证。**App“我的”退出登录条（21:31 用户问哪里被挡）**：只是刚打开没滑时最后一条有一半压在“搜索设置”浮条下，滑到底全露（PageBody 底部留白 = 浮条实高），判断是内容从浮层下经过、不是 bug；用户 21:33 同意不改；21:35 用户又说“会更好看就改” → **v3.5 已做底部渐隐（两端、所有底部浮条统一）**：FloatingFooter 自带一条渐隐（App `BackdropFade.bottom` = 同一个 SkyLayer 着色器反方向，Web `SkyFade kind="footer"`），底条上沿再往上 16px 起淡、到胶囊中线全是壁纸；主页 / 项目输入胶囊、聊天输入胶囊、“我的”搜索条都有，静止时最后一行不被淡（App 聊天列表底留白 Sp.x2→topFadeRamp，= Web sp-4）。决定 + 测量见 devlog「v3.5 底部浮条渐隐」。Web 截图在沙盒要补库：chromium 缺 libatk 等 5 个库且无 root → 从 deb.debian.org trixie arm64 下 deb，dpkg-deb -x 到 /tmp/libs/root，LD_LIBRARY_PATH 指过去即可。
- **v3.5 沙盒能做的已全部做完（2026-10-16 22:06，wip/v3.5 = 662732a 已 push）**：Web ListRow 分体主体 / 正文附加槽 + 收 RAW_ROWS（cf012fa）、浅色夜间蓝→金两版、子页照 Hark、退出登录条、Web 项目列表、底部浮条渐隐。**只剩发版**：wip/v3.5 合并 main + tag v3.5 + push，等用户点头；部署 / APK 仍等用户开口。
- VPS 访问：用户 2026-10-16 19:01 授权（见第二节第 20 条）。Hark 沙盒的公钥 `hark-sandbox-20261016` 已加进 VPS root 的 authorized_keys（`ssh -i ~/.ssh/hark_vps root@172.93.163.240`；私钥在 Hark 沙盒 home，换 agent/机器后可能没有，要再请用户加新公钥，不要索要密码）。VPS 现状：磁盘 79%，app-* 容器 Up。
- 第五节剩余：RAW_ROWS 现 7 个文件 14 处，都是逐条评估后**有意保留**的特殊版式（原因写在 check-arch 注释里），不再收；其余未勾项都要真机 / 真 GPU 浏览器 / 部署后 / 用户，沙盒做不了。

### v3.3 视觉验收（2026-10-16，在 main 上改，**未提交**；决定见 devlog「v3.3 视觉验收」）
- **已完成**：两端拍了 明 / 暗 × 夜 2:00 / 黎明 6:00 / 白天 12:00 / 黄昏 18:30 × 主页、聊天、聊天流式中、项目列表、“我的”首屏 + 翻到底（设置搜索）、安全子页；App 56 张（1080×2340 = 411×891 逻辑像素 @2.625，真着色器），Web 112 张（手机 400 宽 @2x + 桌面 1280）。图在 /workspace/work/shots-3.3/{app,web}/，按页拼的四时段对照在 sheets/，修前在 before/。
  - 出图：App `SHOTS=1 SHOTS_SKY=1 SHOTS_OUT=<目录> flutter test test/screens/shots_test.dart`（字体 /tmp/shots/fonts 见 app/README；可加 SHOTS_SKY_TIMES=day）；Web `npm run build && SHOTS_CHROMIUM=/usr/bin/chromium python scripts/shots.py <目录> sky`（arm64 沙盒 playwright 自带浏览器下载 403，用 apt 的 chromium）。
  - **修了 1 处（两端同值）**：浅色白天壁纸下半屏发灰（底部实测 #d0d9d8，灰绿）：白天第三团柔光 #C0D4E2 冷蓝灰压在暖米底上 → 改暖沙 #EBDBBF（tokens.dart SkyTable.light.day blobC、tokens.css --sky-day-c）；改后底部 #e9ddc3，“亮蓝 → 暖米”回来了。对比度守门不变。
  - 截图脚本：App 新增「v3.3 壁纸 × 时段截图」测试（默认跳过）+ 假接口 2fa / sessions；Web shots.py 新 `sky` 段 + 项目假数据补 status（和 App 同）。
  - 查过没问题：顶部渐隐条与壁纸逐像素相邻差 ≤1/255，无接缝；毛玻璃组无断层 / 错位；深色四时段都是暗蓝紫、夜里最暗；正文 / 次要字清楚；流式两端正常。
  - 校验：flutter analyze 0；全量 flutter test **732 过 / 9 跳过 / 0 失败**（多跳的 1 个是新截图测试）；npm run build 过（配色守门 浅 12.37 / 4.63 / 3.03，深 11.83 / 4.74 / 3.13）；npm test **14/14**。
- **拿不准、未改（等用户定）**：
  1. 子页标题栏两端不一样：App 是贴边整条玻璃栏 + 底部发丝线（浅色时像一条白带），Web 是悬浮玻璃胶囊。要统一得改其中一端的外框（SubPage / .page-head），属设计决定。
  2. 浅色夜间（2:00）整屏淡灰紫，几个色值很接近，层次偏平；要更有层次就得拉开柔光色差，会影响次要字对比度余量。
  3. “我的”页（两端）没有顶部渐隐条，翻下去内容直接切在顶边；App 上会压到状态栏下。原来就是这样（只有带顶栏的一级页有渐隐）。
  4. “退出登录”：App 是整行按钮，Web 是居中小胶囊；Web 项目行的胶囊行为放 ⋯ 留了 32px 最小高，行距比 App 松约 10%。
- 未做：真机 / 真浏览器 GPU 下看流动效果和帧耗时（仍按上面“未验证”）。

### A. 已完成且测试通过（可直接保留）
1. 项目列表按 Hark：名字占满整行最多 3 行、状态胶囊另起一行；删页头摘要 / 列表 emoji / App 行尾 ⋯（改长按菜单）；Web ⋯ 在胶囊行右端。文件：app/lib/features/projects/projects_screen.dart、test/projects_screen_test.dart、frontend/src/features/projects/ProjectsScreen.tsx、projects.css。
2. “我的”底部搜索胶囊两侧内收到 Layout.gutter + Sp.x3（=36），Web .me-search 同值；me_search_test 有断言。
   - 已跑：`flutter test test/projects_screen_test.dart test/me_search_test.dart` 27 项全过；web `tsc -b` + check-arch 通过。

### B. 写了但没验证（接手第一步：让 App 编译通过）
环境：/tmp 被清过，先 `git clone --depth 1 -b stable https://github.com/flutter/flutter.git /tmp/flutter`，`cd app && flutter pub get`。
1. **SWR 统一缓存（用户要求：切页不要每次出骨架屏，先显示上次内容、后台静默刷新）**
   - 新 app/lib/core/swr.dart（SwrCache 64 条 LRU、SwrNotifier、swrGet/swrGetFamily、AsyncValue.swr）。
   - 已改：core/resource.dart、session.dart、usage_screen/usage_day、conversation_files/memory/usage/share、feedback/security/task_detail、login_sessions、reply_language、computer/host/browser_sessions、memory_digest、memory_notes、home_screen、kit.dart AsyncBody、test/design_p3_test.dart（已补 import）。
   - **App 已完成（2026-10-16 16:47，未提交）**：flutter analyze 0；全量 flutter test **719 过 / 8 跳过 / 0 失败**。新增 `test/swr_test.dart`（9 例：二次进入首帧是旧数据不经加载态、后台重取后替换、数据没变不发新状态、有缓存时后台出错 / reload 失败仍显示旧数据、无缓存出错才报错、退出登录缓存换新且重新请求、orNull 取不到给 null、LRU、页面级“第一次骨架 / 离开再进首帧就是内容”）。
     - 修的真问题：① `SwrNotifier.emit` 判“数据没变”原来拿新 JSON 和 `_raw` 比，`_raw` 被别处原地改过时会误判成没变、吞掉更新（技能开关测试暴露）→ 改为存入时记下 JSON 文本签名再比；② `SwrGet(orNull)` 取不到时 `parse(null)` 会抛 → 直接给 null。
     - 测试改动：新加磁盘键（技能 / 任务 / 连接器 / Pages / 记忆 / 笔记 / 用量）后，没覆盖 `cacheStoreProvider` 的测试在 testWidgets 假时钟里等真实文件 IO 会挂死 → 按已有惯例在 19 个测试文件里补 `cacheStoreProvider.overrideWithValue(MemoryCacheStore())`（connect_block、connector_library、me_identity、memory_card、memory_note、memory_screen、mentions、pages、skill_toggle、skills、slash、task_library、usage_compare/csv/day/motion/router、usage、version）；memory_card “invalidate 会重拉”按 SWR 语义改为“先给旧列表、后台取回后换新”。
   - **Web 已完成（2026-10-16，未提交）**：`frontend/src/lib/swr.ts`（64 条 LRU、按路径缓存、同键请求合并、`swrClear()` 退出 / 登录过期 / 重新登录时清空且作废在途请求）+ `hooks/useSwr.ts`（有缓存先显示、后台静默刷新、JSON 相同不重渲；有数据时出错静默；无缓存才 loading；`reload()` 不抛、失败进 error）；`useResource` 改为基于它（顺带修掉首页 5 秒轮询闪骨架）；列表里 17 个文件的 useEffect+http.get 全部换掉。check-arch 第 8 条：blocks/features/hooks 里 `http.get` 只许在 GET_RAW 登记文件里（只减不增）。单测 `frontend/tests/swr.test.ts`（node 22 原生跑 TS，`npm test`，无新依赖）。截图脚本实测：用量页离开再回来首帧 0 个骨架（浅/深 × 桌面/手机）。
2. **流光壁纸（用户要求：随时间变化，夜里暗蓝紫灰、白天亮蓝→暖米，柔和流动，绝不能卡）**
   - 已写：app/shaders/sky.frag（pubspec 已注册）；tokens.dart 删 Palette.backdrop → `SkyTable sky`（浅/深 × 夜/黎明/白天/黄昏，Sky.keyframes 插值，Sky.frame=33ms）；motion.dart 末尾 `SkyClock`（单 Timer≈30fps、无订阅/后台/测试环境 FLUTTER_TEST 时停）；新 app/lib/ui/sky.dart（SkyLayer：着色器，加载失败回退竖向渐变）；glass.dart Backdrop 改用 SkyLayer。
   - **App 已完成（2026-10-16，未提交）**：编译过（tokens.dart 关键帧循环的解构语法错、sky.dart catchError 类型）；全仓 grep 已无 `p.backdrop` / `backdrop:` / Palette.backdrop 旧引用（测试与对比度测试原本就不引用）。新增 `test/sky_test.dart`（13 例：关键帧插值 + 跨午夜、Palette.lerp 带 sky、ramp/fadeAlpha、浅 / 深正文对壁纸全天每 15 分钟 × 底色与三团柔光峰值 ≥4.5（实测浅 4.84 起、深 9.89 起）、SkyClock 测试环境冻结、单 Timer 选档、SkyLayer 按可见性 / 减少动态选档、回退渐变能画、着色器在测试引擎里**能**加载且 uniform 个数对得上）。
     - SkyClock 成本收紧（决定见 devlog 2026-10-16 B1/B2 App 节）：原来是两个 Timer（30fps + 每分钟）→ **真正的单 Timer**；无订阅 / 后台 / 测试环境不起；减少动态原来是“不订阅”导致天色冻在启动时 → 改为“静止档”：只每分钟换天色、柔光不漂（效果保留）；被盖住的路由（TickerMode 关）不订阅。SkyLayer 自带 RepaintBoundary（删 glass.dart 外包的那层）、删没人用的 child 参数和 isComplex、着色器加载完通知重画。
     - 仍未做：真机 / 截图看浅深效果；profile 帧耗时。⚠ 壁纸每 33ms 变一次，上面每个 BackdropFilter 都会跟着每 33ms 重新模糊——这是第 3 项 BackdropGroup 要解决的。
     - ⚠ 同意上面 Web 的发现，App 实测（全天 × 底色与柔光）：浅色 text2 1.60–5.10、text3 1.02–3.23；深色 text2 3.97–7.56、text3 2.61–4.98。正文（text）两套都 ≥4.5。次要字怎么改需两端一起定，App 本轮未改色。
   - **Web 已完成（2026-10-16，未提交）**：tokens.css `--sky-<时段>-<部位>`（浅 :root / 深 [data-theme=dark]，= SkyTable 逐值，check-contrast 查同值 + 正文对壁纸 40 色 ≥4.5 + 深色次要字对底色 ≥4.5，改一个值即红）；`src/lib/sky.ts`（关键帧插值，整分钟重算，页面隐藏停，切主题重算；单测 `tests/sky.test.ts`）；`ui/Sky.tsx` + base.css `.sky`（9 色标竖向底色 + 三团高斯柔光，外 translateX / 内 translateY 两条 alternate 动画，只动 transform，will-change 只在 3 个柔光上；reduce-motion 静止；减少透明度 = 实色 --bg）；`--sky-*` 用 @property 注册，切主题时随 .theme-switching 渐变。删 `--backdrop-1/2/3`（三处）与 body 旧渐变。
   - **次要字对比度：已完成（2026-10-16，未提交）**：两端同一张色表——浅色天色整体提亮（只抬 OKLab 明度、保色相；夜间更亮的灰蓝紫，白天顶色 #5b8bb9→#add6fe），深色黎明/白天/黄昏柔光略压暗；浅色 text2 #64605a→#5c5852、text3 #857f77→#7a746c（两端同步，深色 token 不动）。对壁纸全天最低：浅 text2 4.63 / text3 3.03，深 4.74 / 3.13（原 1.60/1.02、3.97/2.61）。阈值进了 app/test/sky_test.dart、frontend check-contrast.mjs（改为全天采样）、tests/sky.test.ts。sky_test 17/17、a11y 12/12、web build 过、npm test 13/13。未做：截图肉眼看。下面这条“发现”即此项。
   - **⚠ 发现（未改，需定）**：浅色壁纸上 `--text-2`（#64605a）只有 1.60–1.95:1（对顶色）/ 3.51–4.60:1（对底色），`--text-3` 更低；截图里“安全”页页头说明、分区标题直接压在壁纸上明显发灰看不清。App 同一张表同样如此（sky_test 只测正文）。两端要一起改：要么浅色 SkyTable 顶色提亮，要么壁纸上的次要字改用 --text。
3. **卡顿根因（用户：16GB 手机也卡；不准删功能/效果）**
   - **App 已完成（2026-10-16，未提交；决定 + 测量见 devlog「v3.3 B3 App」）**：①毛玻璃分组 `BlurGroup`（glass.dart；BackdropGroup + 固定 key）开在 AppShell（顶栏 + 一级页面左侧按钮 / header，横幅在组外）、ShellPage 内容、SubPage、云浏览器接管页；GlassSurface / 子页标题栏改 `BackdropFilter.grouped`；弹层 / 对话框 / 磨砂遮罩仍独立；“我的”页不分组（返回钮在滚动列表里，规则见 glass.dart 文件头）。读引擎源码确认语义：组里第一个画到的取背景，所以排了绘制顺序（ShellPage 内容→渐隐条→左侧按钮→header；输入胶囊永远先画：底条 Column verticalDirection.up、输入行 rtl，布局不变），转场中 / 上面压着路由 / 主聊天抽屉露出时 ShellPage 的按钮另成一组。②kit.dart TopFade 删除 → ShellPage 顶部 `BackdropFade`（玻璃 = SkyLayer(fade)，减少透明度 = 实色 bg），shell_page_test 重写 7 例。③ChatView 行缓存（同一 Message 实例 + 同一组行状态 → 同一个 widget 实例）。④AppMarkdown 样式表按 ThemeData + 减少透明度缓存。⑤新 test/perf_frame_test.dart：改前→改后 聊天流式其他行重建 305→0、每帧重建元素 695→362、CPU 每帧 ~32→~22ms；一级页滚动 每帧元素 440→100、CPU 15.5→6.5ms；取背景次数 聊天 / 主页 3→2、项目列表 2→1；整页 ShaderMask 1→0。flutter analyze 0，全量 729 过 / 8 跳过 / 0 失败。
   - App 未做：真机 profile 光栅耗时（沙盒无设备）。
   - **B4 外壳壁纸被子页盖住时暂停：已完成（2026-10-16，未提交；决定见 devlog「v3.3 B4」）**。App：SkyLayer 不驱动时画笔不再听共享时钟（原来只退订 Timer、画笔仍挂在 time 上，被盖住照样每 33ms 重画）；ui/sky.dart 新 `SkyCoverScope`（AppShell 最外层）+ `SkyCover`（SubPage 包一层）：本页路由 opaque && 进场 completed && 在台上 → 外壳那层（`Backdrop(coverable: true)`）暂停；转场中 / pop 一开始 / 切 Tab 立刻恢复，恢复那一帧直接取时钟此刻（暂停期间子页那层在驱动时钟，不跳色）。顶栏 FloatAway 判定没动。测试：sky_test +2（转场中照常、完成后外壳订阅数 1→0 且时钟走也不重绘、pop 第一帧恢复并重画、叠两层子页 / 半透明路由 / 无 Scope）、shell_test +1（真路由 /projects/p1/brief：暂停、切到主页恢复、回来再暂停、pop 第一帧恢复）。Web：只有一层全局 .sky，子页透明、不盖壁纸（无此浪费）；真正整屏实色盖住的是云浏览器接管页和看大图 → 进场动画结束后 `<html data-sky-covered>`，`.sky { content-visibility: hidden }`（不用 animation-play-state：会改写 startTime 让渐隐条副本错位），卸载同一次提交撤销；`lib/sky.ts coverSky` + `ui/Sky.tsx useSkyCover`，tests/sky.test.ts +1。未做：没有浏览器（沙盒无 Chromium/Playwright）实看撤销那一帧；真机看返回无闪。
   - 约 9 处独立 BackdropFilter（top_bar、GlassIconButton、composer、project_switcher、chat_view JumpLatest/ErrorBar、inbox、me 搜索、browser_takeover、sub_page 标题）每帧各自模糊 → 用 BackdropGroup + BackdropFilter.grouped。注意：同组只在第一个滤镜处取一次背景，所以分组放三处：AppShell（横幅不进组）、ShellPage 内容、SubPage；ShellPage 绘制顺序 内容→顶部渐隐条→header→lead。
   - kit.dart TopFade = 整页 ShaderMask(dstIn) 离屏层 → 删掉，改为 ShellPage 顶部一条 SkyLayer(fade: (clear, solid))（sky.dart 已支持 fade 参数），改 test/shell_page_test.dart。
   - chat_view.dart 流式时整列重建 → 按 Message 实例 + 行状态缓存行 widget（ChatController 只替换最后一条，其余实例不变）。
   - Markdown：AppMarkdown 每次 build 新建 MarkdownStyleSheet → 缓存。
   - Web：shell.css 6-15 `.page` 与 chat.css:90 `.thread` 的 mask-image 让整个滚动区离屏 → 改顶部窄条。**Web 已完成（2026-10-16，未提交）**：两处去掉整区 mask，换成 `ui/Sky.tsx SkyFade`（一条渐隐带高的壁纸副本，按视口位置反向偏移，漂移动画 startTime 对齐；窄条自己的 mask = 原遮罩反过来），滚动区加 isolation 保持层叠。实测：隐藏内容后有/无窄条逐像素最大差 1/255（浅/深 × 桌面/手机 × 页面/聊天）。4× CPU 无头 Chromium 下新旧都 60fps，软件渲染看不出差别；真 GPU 的 Chrome trace 未做。
   - 完成后：Flutter profile/frame timing，Web Chrome 4× CPU trace。

### B'. 全量校验（2026-10-16 B4 之后，工作区含 B1–B4 全部改动，未提交）
- app：`flutter analyze` 0 问题；全量 `flutter test` **732 过 / 8 跳过 / 0 失败**。
- frontend：`npm run build`（check-arch + check-contrast + tsc -b + vite）通过；`npm test` **14/14**。
- 后端：backend/.venv 逐个跑 tests/smoke_*.py：**202/202 过**（共 203 个，跳过需真密钥的 smoke_stepfun；smoke_preview_ws 本次一次过）。

### C. 发布步骤（全部通过后）
VERSION → 3.3.0，`python3 brand/sync.py`，CHANGELOG 加一节（含“删除/合并”行），合并到 main，tag v3.3，push（APK 按第二节第 12 条等用户要时才编；GitHub Actions 的 app.yml 是每次 push 自动跑的测试 + 构建检查，产物只留在 GitHub，不算交付）。服务器只有用户明确说“更新服务器”才部署；部署前删除服务器上 tag 里不存在的旧源码文件（见第二节第 17 条 / work/vps/README.md）。

### D. 参考
- 流光着色器设计参考 mesh_gradient（MIT，Ben Fornefeld），未复制代码；需在 NOTICE 加一行。
- 决策记录：docs/devlog.md 末尾 2026-10-15 23:15 之后几节。

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
   - **能自动的写进脚本**：`deploy/build-apk.sh` 结尾清上面“必须删”里的 APK 缓存；更新脚本结尾 `docker image prune -f` + `docker builder prune -f`。**v3.0.1 已落地**（APK 产物改为 `/root/toyuis-<版本>-arm64.apk`，只留最新一份；测试 `deploy/tests/test_build_apk_cleanup.sh`；未在 VPS 实跑）。本地沙盒同理：测试日志、临时截图用完就删。

18. **流畅丝滑是“顾全大局”的一部分**（用户 2026-10-15 23:05，原话大意：“做新功能、新动效或任何东西时，都要保证软件和网页的流畅性丝滑性，不能做一些东西就卡顿……叫你顾全大局，要思考就思考这些东西”；用户为此很伤心，不想每次提醒）：
   - 每个改动（新功能、动效、换样式、优化）上线前都要证明 **App 和 Web 不因它变卡**：动手前估算成本（毛玻璃 / backdrop 层数、重建范围、会触发布局的动画、大字体 / 大图、逐帧计算），做完后验证（Flutter 帧耗时测试 / profile 光栅 < 16ms；Web Chrome 性能录制 4× CPU 降速）。
   - **优化卡顿不准删功能、不准删效果**（用户 23:03：“保证功能完好、效果完好的同时去优化卡顿”）。
   - 照 Hark 截图做的界面要**忠实还原版式**（23:02 项目列表：项目名占满整行、状态胶囊另起一行），不能“学一半”。

19. **多调研、多思考、立足实际，别堆屎山**（用户 2026-10-16 19:00 重申）：动手前先读现有代码和交接文档、查官方文档 / 成熟开源实现，想清楚它在全局里归属哪里、替换什么；判断以**真实代码和真实测量**为准（grep 确认谁在用、改前改后同条件对比帧耗时），不凭印象加“以防万一”的代码。例：v3.4 曾想给“我的”页加 isolation 防头像越过渐隐条，grep 发现那个头像只在偏好子页、“我的”页没有带 z-index 的元素 → 不加。拿不准就先查，查不到就在 HANDOFF 里写“未验证”，不写成已完成。

20. **VPS 可以连，但只做验证不部署**（用户 2026-10-16 19:01 授权连接 VPS；19:08 同意跑真模型）：可 ssh 上去只读查看、用临时容器（`docker run --rm`，名字带 hark-）跑真沙盒/真模型测试，测完删容器和 /tmp 文件；密钥只在服务器内传递，不读出、不打印、不拷出服务器；不改线上容器、不动 .env、不部署——部署和 APK 仍按第 12 条等用户开口。费 token 的测试先说明。

21. **拿不准的设计就照 Hark 做**（用户 2026-10-16 19:34：“不会就学 Hark！他的我十分喜欢！”并发了 6 张 Hark 深色截图）：两端不一致、设计取舍拿不准时，不要攒着问用户，先对照 Hark 真机截图定；Hark 没有参照的才列给用户。据截图已定（19:35）：①项目聊天标题 = 顶部导航下方居中、按文字宽度的小玻璃胶囊（App / Web 本来就是）；**子页（20:49 用户补发 Hark 钱包 / 安全 / 系统偏好设置截图）= 没有栏也没有胶囊：左边一颗独立圆玻璃返回钮（‹），标题居中裸字，内容直接接在下面**；②“退出登录” = 整行浅底圆角条、左侧图标 + 文字、无箭头，不放在卡片组里；③项目列表 = 无卡片底、名字大字占满一行、状态胶囊另起一行、行上无 ⋯；④“我的”页没有标题栏，导航胶囊悬浮在内容上方。⑤浅色夜间（用户 19:41 补发 Hark 浅色截图）：Hark 浅色半夜也是“深蓝天 → 浅青 → 暖金米”（采样 23:02 顶 #3a6d99 → #6093b6 → #9dbfce → #cad7cd → 底 #d8d4b3；22:20 底 #e5c988），不是淡灰紫 → 浅色夜间改这套蓝→金；Hark 顶部 #3a6d99 上我们的次要字只有 1.3:1，所以取色相、亮度守在次要字 4.5 线以上（v3.5 第一版 top #b6d8f5 太淡；用户 20:06“你想想吧，反正就是要有美感”交我定 → 第二版：浅色次要字 #4a4640 / 最次要字 #605b54 压深一档，换来 night top #8ebbe3 · a #86bcea · b #c6dfe8（中段亮光）· c #efe4c4（底部奶油光）· bottom #dcc58a，两端同值，理由见 devlog）。

22. **壁纸 / 背景必须有美感**（用户 2026-10-16 20:04：“背景反正就是要有美感”）：调背景色不只看守门数字，每个时段 × 明暗都要出图看，和 Hark 截图并排比层次、色相过渡、柔光；数字达标但发平、发灰、发脏的不算完成。**而且背景是流动的**（用户 20:04：“而且他是流动的你知道不”）：v3.3 流光（三团柔光慢漂 + 按钟点换色）是背景的一部分，任何改动不准把它变静止或变卡，验收时要看动起来的样子，不只看静态截图。对比度守门照旧（字要看得清），两者冲突时先想办法两全（换色相 / 柔光位置），实在不行列给用户。

23. **能更好看的就改，不因“旧版就这样 / 只是小瑕疵”放着**（用户 2026-10-16 21:35：“会更好看就改”）：发现视觉瑕疵时，判断改了确实更好看就动手，但要按宗旨统一做（同类组件一起改、两端同改、替换不叠加）并测帧耗时，不为一页单独打补丁。例：v3.5 底部浮条渐隐做在 FloatingFooter 里，所有底部浮条两端统一。
24. **不要半屏弹层，全部全屏**（用户 2026-10-16 22:27–22:40 真机反馈，原话：“为什么还是半屏显示？”“肯定是做成全屏啊，就这样啊！”“我都说了 你别留那个半屏的 还给我留留留”“丑爆了”“聊天页面的历史记录也是”）：项目切换、聊天历史这类从侧边 / 底部滑出的窄卡（白底圆角卡、右边露出底下页面）一律不要；打开就是铺满整屏、直接落在壁纸上的一页，样子照“项目”列表页（无卡片底）。App 与 Web 同改，旧抽屉样式直接删，不留两套。
25. **主要聊天 + 旁聊**（用户 2026-10-16 22:40 想法，附 Ziggy 截图：列表顶部固定“主要聊天”，下面“旁聊”分区，未读蓝点、归档）：聊天只有一条永不结束的主对话（无限上下文：旧内容自动压缩成摘要 + 记忆带着走），具体的事开旁聊，旁聊结论回写主对话；替换现在平级的历史对话列表。**待做**：先修完 v3.5.1 这批（全屏 / 断线 / 计划钮 / 顶部空白 / 建议卡被挡），再出设计（数据模型、迁移、提示词、两端 UI）给用户确认后动手。
26. **照 Hark 的交互细节一个个对齐**（用户 2026-10-16 22:48–22:49：“你看看 hark 做的多好，你的好丑！”“人家点击他，他是做了一个动向…从左往右切过去，这样挺好的。你这样做吧”）：主页 + 新建面板 = 整屏毛玻璃 + 底部输入胶囊（不是白底弹层）；“我的”= 第四个标签横滑切换、导航不消失。今后同类交互先对照 Hark 截图。

27. **卡片 = 带壁纸透色的半透明灰白“假玻璃”，不用纯白**（用户 2026-10-17 定，参考 Hark）：列表里的卡（主页面板卡、今天卡、“我的”列表组 / 用量卡、聊天里的块、子页卡）一律用同一个 token——App `Palette.card` / 网页 `--card`，两端同值（浅 `rgba(248,249,250,0.66)`，深 `rgba(22,23,28,0.62)`，取样见 devlog 2026-10-17）。
   - 做：新卡片只走 GlassCard / AppCard / ListGroup / BlockFrame（App）或读 `var(--card)`（Web），蓝天上自然偏冷灰、暖底上偏暖灰。
   - 不做：不写纯白 / 实色卡底；不为卡片加真模糊（BackdropFilter / 背景模糊只给浮层）；不在页面里另写一个半透明色。
   - 减少透明度时卡片回实色 surface。卡上的字按“card 叠在壁纸上”守对比度（App test/sky_test.dart、网页 check-contrast.mjs），改透明度或改字色前先跑这两个。
   - **浮层（顶栏导航胶囊 / 输入胶囊 / “我的”搜索框 / 圆钮）同样透出壁纸**（用户 2026-10-18 反馈“还是近乎纯白，不好看”）：同一个 token App `Palette.glass` / 网页 `--glass`，两端同值（浅 `rgba(255,255,255,0.5)`，深 `rgba(27,28,33,0.76)`，Hark 取样见 devlog 2026-10-18）；浮层下面本来就有真模糊，不再加模糊层；不模糊的东西不读 glass（读 card）。浮层上的字按“glass 叠壁纸 / 卡 / 卡上墨色一半”守对比度（同上两个守门）。

28. **子页要短、要顺，不卡**（用户 2026-10-18 00:24：“这个电脑页他妈太长了吧，滑动也特别卡顿”“这个用量页也是很长，也卡顿”；00:27：“你要记得做得又美观又优雅，这两个也不要做得那么长，赶紧优化，优化，优化，再优化，而且不能卡顿”）：
   - 做：子页首屏约一屏就把概况说完（412×915 手机视口为准）；长列表只露前 3 条 + 行尾“全部 ›”进子页；同一信息只出现一次（概览里有的，下面不再列一遍）；轮询 / 刷新只重建数值变了的行，滚动时不触发重建；淡入用到 1 就不留合成层的写法（App SettleOpacity）。
   - 不做：不把所有明细平铺在一页；不为了短而删信息或删效果（明细进子页，不是删掉）。
   - 验收：改前改后量 maxScroll、每帧 / 轮询重建次数、opacity 层数，并写进 devlog。例：v3.5.1 电脑页 maxScroll 3522→94、轮询重建 677→59。
   - **流光背景照 Hark 做**（用户 2026-10-18 同一轮）：肉眼明显在流动（不是几乎看不出的漂移）；多种颜色柔和、有前后层次；颜色随时间变化，白天在蓝 / 淡紫 / 蜜桃珊瑚 / 薄荷 / 暖金之间轮转；任何时候都不能让页面变卡。两端同一色表、同一核心算法，字的对比度守门照旧（第二节 22、27）。

29. **项目 / 聊天都做成 Hark 那种目录**（用户 2026-10-18 原话：“项目/聊天都做成 Hark 那种目录：顶栏下一行行名字，进去左上 ☰ 回目录，不要切换胶囊、不要卡片堆叠和重复信息”）：项目列表、聊天历史 = 顶部导航下面直接一行一行的名字（无卡片底、不堆卡片、同一信息不重复出现）；点进去后左上角 ☰ 回到目录；不要项目 / 对话切换胶囊。两端同改，旧切换胶囊删掉不留。

30. **真机流畅才算完成，不能只拿沙盒数字**（用户 2026-10-18 原话：“魅族 20 跑 Hark 不卡，卡就是我们软件问题；必须真机高刷流畅，不能只拿沙盒数字”）：魅族 20（骁龙 8 Gen 2，120/144Hz 屏）跑 Hark 流畅，所以我们卡就是我们软件的问题，不许归咎设备。App 必须在真机上跑满高刷新率并且滑动流畅；沙盒软件光栅 / 无头浏览器的数字只能作参考，交付性能改动时要说明“真机未验证”并请用户真机确认（可用隐藏性能浮层截 UI / Raster 柱）。

31. **聊天里的过程只用一颗步骤胶囊（照 Hark）**（用户 2026-10-19 18:50 原话大意：“助手的操作 / 工具调用 / 步骤现在全部展开，占空间且丑，改成 Hark 式”）：
   - 做：回复**下方**只有一颗小胶囊（发丝描边、半透明卡片底、单行小字），生成中实时显示“当前正在做的那一步”（如“正在运行命令 · pip install pandas”，两步之间“正在思考”），步骤推进就在原地交叉淡入淡出换字；生成完胶囊收成安静的“N 个步骤 · 用时”。点胶囊展开 = 完整步骤历史（逐步、diff、失败原因，一样不少）。正文回复、需要用户操作的卡片（确认 / 表单 / 文件 / 改动 / 浏览器 / 订单等）照常展开显示。
   - 不做：不再逐条列出步骤 / 工具小条；不为过程单独撑一张空回复卡；不删步骤历史（是收进胶囊，不是删掉）。
   - 两端同改、同样式、同文案规则（App StepCapsule / Web StepCapsule，规则 models/activity.dart capsuleLabel = lib/activity.ts capsuleLabel）；动画只动 opacity / transform；改完要截图核对明暗。
   - 拿不准的：计划清单卡（PlanBlock）、子助手卡（DelegateBlock）算“带结果的卡”还是“过程”，v3.5.5 没收，列给用户定。

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
- 已发布到 git：**v3.4（tag v3.4，2026-10-16，“我的”页顶部渐隐、白天壁纸不发灰、后台任务取消竞态根因修复；VPS 真沙盒 + 真模型验证过，见第〇节；服务器未部署，线上仍 v3.2.1）**、**v3.3（tag v3.3，流光壁纸、SWR、卡顿根因）**、**v3.2.1（tag v3.2.1，历史搜索搜全部含项目、网页手机输入框占位符不截断、截图假数据补齐）**、**v3.2（tag v3.2，2026-10-15 20:35，字体统一为打包的 MiSans 子集、数字比例宽、去小标签字距、正文行距 1.4）**、**v3.1（tag v3.1，对照 Hark 真机截图：暗色炭灰面、字号降一档、深色浮层去描边）**、**v3.0.2（tag v3.0.2，v3.0 网页截图验收后修两处：定位等内容出来再闪、Spot 分区间距）**、**v3.0.1（tag v3.0.1，部署脚本自动清理，见第二节第 17 条；应用无变化）**、**v3.0（tag v3.0，2026-10-15，“我的”页底部设置搜索两端 + `?focus=` 定位闪一下；版本号因构建号规则从 2.99 进位，无破坏性改动；纯前端）**、**v2.99（tag v2.99，2026-10-15，E4 ImageStack 两端 + App 震动统一入口 / AppSwitch；“我的”页底部搜索未做，见第五节第 6 项；纯前端）**、**v2.98（tag v2.98，2026-10-15，E1 Web 收尾：RAW_ROWS 81→23 处、23→12 个文件迁到 ListGroup / ListRow，App 6 个富内容行评估后保留，见第五节第 6 项；纯前端）**、**v2.97（tag v2.97，2026-10-15，E1 收尾：ListRow / ListGroup / PageIntro 两端统一 + App 附件弹层高度修复，见第五节第 6 项；无后端 / 迁移变化）**、**v2.96（tag v2.96，2026-10-15，“我 → 连接的账号”一页：连接器 + 保险箱合并，见 5·2a；含迁移 0067，只改旧卡去处 vault→connectors）**、v2.91、v2.91.1、v2.92、v2.93（tag v2.93，2026-10-15）、**v2.94（tag v2.94，主页三个 bug，见 6a）**、**v2.95（tag v2.95，2026-10-15，项目 = 一段对话，见 5b；含迁移 0066，部署时自动合并旧多对话项目、可回退）**。v2.94/v2.95/v2.96/v2.97/v2.98/v2.99/v3.0 均未部署、未出 APK（按新规则等用户说）。**2026-10-15 11:41 已部署 v2.93.0**（`/api/version`=2.93.0，容器全部 Up，.env 备份 /root/env.bak.v293，磁盘 88%，下次先 prune）；**2026-10-15 12:54 已在 VPS 用 `deploy/build-apk.sh` 编好 v2.93.0 APK**（arm64，22.2 MB，约 7 分钟，构建后容器已恢复）。
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
    - 遗留：部署后核对迁移结果；~~主聊天搜索命中项目对话时结果无 project_id~~ v3.2.1：面板搜全部，项目那段带 project_id/project_name 并跳进项目定位；tokens.css `--pill-drop` 为对齐 App 保留
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
     - [x] Web 截图核对（2026-10-15 18:50，本机已装 Chromium，`frontend/scripts/shots.py` 已修到能跑）：发现并在 v3.0.2 修了“对空区块闪一下”和 Spot 分区间距两处
     - [ ] 未做：App 截图（需中文字体环境）；真机手感（定位滚动 + 闪一下）
7. 后台任务/定时任务的运行对话不要出现在主对话列表（用户叫“子对话”，嫌乱）——确认 v2.75 修复在 VPS 上生效。
8. ~~Web 截图重拍~~ 2026-10-15 v3.0.2：本机装好 Chromium，shots.py 修到能跑（134 张，`/tmp/shots/web`）；之前几版标“未截图”的网页页面可以逐个对照了（还没逐张看完）。banner“稍后再看”：评估后不做——横幅 4 秒自动收起，收件箱那一行已有“稍后再看”，横幅上再加按钮是叠加（宗旨第 2 条）。
   - ~~既有小问题：手机宽度下项目聊天输入框带“快速”芯片时占位符被截成“给 Toyuis 发消”。~~ v3.2.1 修（≤480px 档位钮只留图标）。
9. SearXNG 集成测试（需 VPS）；关闭 VPS SSH 密码登录。
10. ~~CORE：`docs/core-gaps.md` #9（一次读多文件）~~ 2026-10-15 核对：v2.33 已做（read_many_files），core-gaps #9 早已打勾，此项无剩余（`docs/core-gaps.md` 在项目根 docs/，不在仓库）。BRAIN：继续对照 Hark 公开表现找差距（先写对比再做）。

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
- ~~`GET /api/connectors/mcp`、`GET /api/memory-notes` 还没有假数据~~ v3.2.1 已补。




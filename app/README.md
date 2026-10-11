# 原生 App（Flutter：安卓优先，iOS 同一套代码）

和后端只通过 `../docs/protocol.md` 对话。

## 目录
```
lib/
  theme/tokens.dart     设计令牌：颜色、间距、圆角、字号、动效（唯一来源）
  theme/app_theme.dart  令牌 → Material 主题；组件用 context.palette；systemOverlay() 管状态栏/手势条
  theme/appearance.dart 外观偏好（跟随系统/浅色/深色），只有 app.dart 读、“我的 → 外观”写
  theme/look.dart       个性化偏好（头像颜色、减少透明度），只存本机；app.dart 把 solid 注入 GlassMode
  ui/motion.dart        共用动效：FadeSlideIn、Pressable、Shimmer、TypingDots、PulseDot、SlideDownSwitcher、SwapSwitcher（小块换值：上下错开淡入淡出）、SidePaneSwitcher、FlashHighlight、MeterBar（进度条，长到目标值）、SlidingThumb（分段滑块）、FloatAway（浮层淡出让位）、RiseSwitcher（从下方升起：输入胶囊上方的建议条/错误条、左侧收起钮）
  ui/glass_mode.dart    材质最底层：GlassMode（减少透明度）+ GlassFills（context.cardFill/tileFill/hairline）；只依赖 theme，motion.dart 和 glass.dart 都用，glass.dart re-export
  ui/glass.dart         设计 v2 材质：Backdrop、GlassSurface（blur 只给浮层）、GlassCard（列表大卡）、GlassGroup（分组列表卡）、ValueTile（标签+大数字）、PillButton（卡内胶囊按钮）、WidePill（整行入口）、GlassIconButton、Avatar（自选色）、GlassChip、FrostScrim；页面不自己写 BackdropFilter/阴影，衬线只用 `style.serif`（app_theme.dart）
  ui/adaptive.dart      自适应：context.window（compact <600 / medium / expanded ≥840）；一级导航各尺寸都是浮动顶栏，宽度只影响页面内部（聊天双栏）
  ui/sub_page.dart      子页面外框 SubPage（Backdrop + 透明 Scaffold + GlassAppBar 毛玻璃标题栏，extendBodyBehindAppBar 让位）：所有非一级页面只用它，不写 AppBar
  ui/kit.dart           共用零件：FloatingFooter（底部浮条让位：量出高度加进 MediaQuery.padding.bottom）、PageBody、ListGroup、RowTile、AppCard、EmptyHint、AsyncBody（加载/失败/空三态）、SwipeToDelete、Pill
  ui/sheets.dart        底部弹层：showAppSheet / showAppScrollSheet（唯一入口，外框 GlassSheet 玻璃）、showFormSheet（字段表单）、showActionSheet（操作/选择）、showAppDialog（居中玻璃对话框，唯一入口）、confirmDanger（两颗等宽胶囊）
  ui/format.dart        文件大小、相对时间、金额（formatMoney）、token（formatTokens）
  core/links.dart       打开外部链接（url_launcher 只在这里）
  core/share.dart       系统分享面板（share_plus 只在这里）：shareTextFile
  core/speech.dart      朗读唯一入口（audioplayers / flutter_tts 只在这里）：speechProvider.toggle(id, text)；服务器 tts=server → POST /api/voice/speak 播 mp3，否则或失败 → 系统语音；同时只读一段，ChatView 卸载/换对话即停；测试用 speechEngineProvider 换假引擎（test/speech_test.dart）
  core/                 session（安全存储 token）、api（REST）、chat_socket（WS 重连 + 连接状态流，不排队）、resource（通用增删改查，可带 cacheKey 离线可读）、cache（本地离线缓存）
  models/               block（消息块，sealed）、message、resources、memory（记忆分类名/顺序、多词搜索+分类筛选、MemoryDigest）、usage（用量报表 + 预算档位）、export
  blocks/               每种消息块一个组件；block_view.dart 是唯一分发点
  features/             home（面板卡头：刷新 + “更多”菜单 = 编辑面板 / 刷新记录 / 移除；inbox.dart 收件箱未读：轮询节奏、角标、横幅；action_card.dart 主动建议卡 + cardTargets 去处表，如预算提醒 → 查看用量；card_snooze.dart 稍后提醒唯一入口：卡头小钮 showSnoozeSheet（快捷时刻与一次性任务共用 models/time_shortcuts.dart）+ “为你准备”底部 SnoozedCards 一行，点开现在放回）/ chat（chat_scaffold 聊天骨架：手机历史在抽屉、平板双栏常驻；history_panel 历史栏：搜索/分组/重命名/置顶，主聊天和项目共用，点内容命中 = open(id, focus: message_id) 定位到那条消息（ChatView 往上翻屏直到建出来 → ensureVisible → motion.dart 的 FlashHighlight 闪一下）；chat_cache 对话离线缓存 + 发件箱持久化；model_choice 可选模型列表 + 输入框模型钮；conversation_usage 顶栏标题下的本对话用量 ChatTitle + 明细弹层（右上角“分享为网页”）；conversation_share 分享对话：conversationShareProvider(id) + showConversationShare 唯一入口，历史长按菜单与用量弹层共用） / projects（含项目文件；project_brief_screen 规则与档案页 /projects/:id/brief：进页静默 reload、查看=ui/markdown.dart AppMarkdown、编辑=等宽输入框 + 字数、未保存返回要确认、保存 PATCH {brief}）/ me（记忆 memory_screen：概括卡 memory_digest（MemoryDigestController：进页 GET、memoriesProvider 一变静默重取、只在点“生成/更新”时 POST；接口不存在就不显示）+ SearchField + 分类筛选条 + 分组列表，筛选逻辑在 models/memory.dart；定时任务 tasks_screen 列表（新建、详情“编辑”、主页面板菜单“编辑面板”都用 task_form.dart showTaskForm（唯一任务表单，编辑只发改了的字段；面板 repeatOnly 无“一次”），计划用 schedule_picker.dart：SegmentedButton 重复/一次 + cron 常用项 / 一次性快捷时刻 + “选时间…”展开 CupertinoDatePicker 滚轮（RiseSwitcher），状态在 ValueNotifier<TaskPlan>，TaskPlan.toJson 两个字段都带）（上次失败挂红点 DotBadge）+ task_detail 详情（状态文案只在 task_labels.dart：排队 > 上次失败 > 下次运行/马上运行/已暂停，读服务端 next_run_at；运行记录、排队/运行中每 Timing.taskRunPoll 轮询、结束即停、报告那次 openConversation）、连接器、技能（skills_screen：自定义版归“内置”组带“已自定义”，编辑页 _Origin 卡给“复制一份来改 / 恢复默认”，都走 skillsProvider.act(id, customize|reset)；行尾 Switch 和编辑页“启用”行共用 toggleSkill（乐观拨动、失败拨回），停用的行用 motion.dart Dimmed 变淡，Pages 下线行同用 Dimmed / tokens Op.dimmed）、保险箱、Pages（pages_screen：PageRow 按发布状态给菜单，下线/重新发布/重命名都走 pagesProvider.patch，分享走 core/share.dart shareLink）、用量与花费 usage_screen）/ auth
  shell/app_shell.dart  外壳 = Backdrop → 当前 Tab → FloatingTopBar；三个一级入口（主页/聊天/项目），顶栏只在一级路径（shellRoots）显示，子页面时 FloatAway 隐藏
  shell/top_bar.dart    浮动顶栏：左侧空位 + 居中 SegmentedNav（玻璃胶囊 + 滑块，主页带未读点）+ 头像（push /me）
  shell/launch_composer.dart 主页/项目底部的输入胶囊 LaunchComposer：同一个 Composer，发出 = askInNewChat（新对话 + 切到聊天）；聚焦 = FrostScrim 磨砂 + 左侧“收起”+ 上方建议（starterPrompts，聊天空状态共用）；返回键先收起
  shell/shell_page.dart 一级页面外框：把顶栏高度加进 MediaQuery.padding.top（内容可滚到顶栏下面），在顶栏左侧空位画本页的上下文按钮（lead），可选 header 行（主聊天标题胶囊）
  app.dart              路由（未登录自动去 /login）；/me 是头像进入的顶层全屏页（不是 Tab），深链直达时返回去主页
```

## 规则
- 设计 v2 外壳（`test/shell_test.dart`、`test/adaptive_test.dart`）：一级页面 = `Scaffold(backgroundColor: transparent)` + `ShellPage(lead: GlassIconButton(...))`，不写 AppBar；内容让位只读 `MediaQuery.paddingOf(context).top`（PageBody 已自动叠加）；子页面保留 AppBar、实色底。玻璃只用 `ui/glass.dart`，真模糊只给浮层。新建面板入口 `features/home/new_panel.dart createPanel`，“问一句就去聊天”统一走 `open_conversation.dart askInNewChat`
- 输入胶囊与气泡（`test/design_p2_test.dart`）：Composer 是浮在内容上的玻璃胶囊，外面一律包 `FloatingFooter`，列表底部留白只读 `MediaQuery.paddingOf(context).bottom`；聊天页的 Composer 只在 ChatView（对话状态在那），一级页面只用 `LaunchComposer`，不要再造第三个输入框。气泡宽度按 LayoutBuilder 的聊天区宽 × `Layout.bubbleMax`，不读屏宽。日期分隔只认 `models/message.dart startsNewDay` + `ui/format.dart formatDay`（`Message.createdAt` 本地时间，null = 不开新的一天）
- 颜色、时长、间距只从 `theme/tokens.dart` 取；页面不写 AnimationController，用 `ui/motion.dart`
- 无障碍（`test/a11y_test.dart` 兜底）：纯图标按钮必须有名字——`IconButton` 给 `tooltip`，`Pressable` 给 `semanticLabel`（有文字的会自动并进来）；可点区域 ≥ `A11y.minTap`（视觉小就外圈补透明区，且要落在父组件范围内）；文字不写死高度，1.3 倍字号下 360 宽不溢出；对比度：正文/按钮字 ≥ 4.5:1、text3 ≥ 3:1
- 系统“移除动画”时 motion.dart 的组件自动静止；页面里直接写的 `AnimatedX` 时长用 `context.motion(Motion.x)`
- 平板/折叠屏（`test/adaptive_test.dart` 兜底）：页面不自己比宽度，只问 `context.window`；断点只在 `Layout`。切换布局时只增减侧边的东西，主内容保持同一个带 key 的孩子（状态不丢）；尺寸变化引起的切换不做动画，用户主动收起/展开才动
- 新增消息块：`models/block.dart` 加类 → `blocks/` 加组件 → `block_view.dart` 的 switch 会提示你登记
- 列表页 = `core/resource.dart` 里一行 provider + `AsyncBody`；表单和菜单一律用 `ui/sheets.dart`，不手写 showModalBottomSheet / showDialog / PopupMenuButton（自定义内容用 showAppSheet，长列表用 showAppScrollSheet；test/sheet_test.dart 的架构守卫会拦）。输入框底色由主题统一（tile 底、聚焦实底），页面里别再写 fillColor。玻璃上的填充只用 `context.cardFill / tileFill / hairline`（ui/glass.dart，减少透明度时自动变实色），聊天块里不写 surface/surface2
- 列表错峰入场用 `Motion.stagger(i)`
- 搜索框一律用 `ui/kit.dart` 的 `SearchField`（历史栏、记忆页共用）；会花 token 的生成（如记忆概括）只由用户按钮触发，页面不自动调
- 深浅色只靠 Palette 切换，组件里不判断 brightness；新颜色要在 light/dark 两套里都给值（lerp 会自动带上）
- 未读数只认 `inboxProvider`；它的摘要一变会让 `cardsProvider` 重拉，页面不各自轮询
- 网络请求只经过 `core/api.dart` / `core/chat_socket.dart`
- 离线（`test/offline_cache_test.dart` 兜底）：缓存只存服务器原样 JSON，不给模型写 toJson；只有 `chat_controller`（经 `chat_cache.dart`）和 `resource.dart`（cacheKey）碰缓存，页面不碰；先显示缓存再静默刷新，`ApiError.isNetwork` 时保留缓存、标 offline，其它错误照常报；缓存读写失败一律吞掉；退出登录清空
- 发件箱（`test/outbox_test.dart` 兜底）：消息的发送状态（`Message.outbox`：待发送/失败）只归 `chat_controller` 管，`chat_socket` 只报连接状态、`send()` 写不出去就返回 false；一次只在飞/排队一条；审批回复不排队（服务器在等），断线直接提示；未发出的消息不进对话缓存，而是按对话存进 `chat_cache` 的发件箱（`outbox.<对话id>` / `outbox.new.<范围>`），写入只在 `chat_controller` 的 `listenSelf(_saveOutbox)` 一处；切回/重启后一律以“发送失败”恢复，不自动补发（`test/outbox_persist_test.dart` 兜底）
- 消息操作（`test/regenerate_test.dart` 兜底）：复制用 `models/block.dart` 的 `copyText`（块 → Markdown，与后端 blocks_to_text、网页 lib/copy.ts 同规则）；“重新生成”只给最后一条回复，`ChatState.canRegenerate` 是唯一判据，`ChatController.regenerate()` 不排队（线不通给错误提示）；上一轮失败时错误条上出现“重试”（同一个 regenerate，不带 message_id）；被服务器拒绝或回复开始前断线 → 以服务器为准重拉，用户消息不标失败
- 编辑最后一条用户消息（`test/edit_test.dart`）：`ChatState.editableId` 是唯一判据；`ChatController.edit(text)` 与 regenerate 共用 `_rewind`（带 text）。气泡长按出菜单（复制 / 编辑），因此用户气泡不再用 SelectableText。编辑态是 ChatView 的界面状态（`EditDraft`），Composer 显示“编辑消息”条、暂存原草稿、收起附件托盘；安卓返回键先退出编辑（PopScope）
- 停止生成（`test/stop_test.dart` 兜底）：`ChatController.stop()` 发 `message.cancel`、置 `stopping`（`ChatState.canStop` 是唯一判据），不在本地先砍，等服务器的 message.done（`Message.stopped`）或 message.stopped 收尾；`copyWith` 在 streaming 变 false 时自动清 stopping。Composer 生成中右侧圆钮换成停止键（同一个 `_RoundButton` + AnimatedSwitcher 缩放），停下的回复在操作行尾标“已停止”
- 导出对话（`test/export_test.dart`）：格式只在 `models/export.dart`（每条正文复用 `copyText`，与网页 lib/export.ts 同规则，只导已进服务器的消息）；取数只在 `ChatController.exportMarkdown`（服务器优先，断网退回离线缓存）；系统分享只经 `core/share.dart`（share_plus 只在这里）；入口是历史栏长按菜单“导出 Markdown”
- 卡片去处（`test/budget_card_test.dart`）：HomeCard.target 只在 action_card.dart 的 cardTargets 映射成按钮，未知值当没有；点去处先标已读再 go；忽略后刷新收件箱未读
- 用量与花费（`test/usage_test.dart`）：只读 `GET /api/usage`，`usageProvider`（autoDispose）在 usage_screen.dart，我的页那一行副标题也读它；预算档位只认 `UsageReport.level`（≥80% warning、≥100% danger），客户端不算钱；没配单价时只显示 token 并提示去 .env 配 MODEL_PRICES。按模型列表 `ModelUsageList` 在 usage_screen.dart，本对话明细也用它。“本月每天”柱状图在 usage_chart.dart（`test/usage_chart_test.dart`）：数据只来自报表的 daily，不另请求；CustomPainter 画柱，入场用 motion.dart 的 `GrowIn`，高度 `Layout.chartHeight`；选天默认跟着今天，点/拖/读屏上下滑都走同一个 `_pick`；日均预算 = `UsageReport.dailyPace`（有预算且定价才有）。
- 本月最花钱的对话（`test/usage_top_test.dart`）：数据只来自报表的 conversations，不另请求；`TopConversationList` 在 usage_screen.dart，占比只认 `UsageReport.shareOf`（有定价按钱，否则按 token），占比条用 motion.dart 的 `MeterBar`；已删（title=null）只展示。从别处跳进某个对话一律走 `features/chat/open_conversation.dart` 的 `openConversation()`（收件箱也用它），不要各处自己 go('/chat') + open
- 用量图选某天看明细（`test/usage_day_test.dart`）：`features/me/usage_day.dart`（`usageDayProvider` 以 `dayKey` 日期为键 → `UsageDayDetail`、`DayBreakdown`、紧凑的 `DayModelRows` + `DayConversationRows`，两者共用私有 `_ShareRow`；对话行点开走 `openConversation`，已删的不可点）挂在 `DailyUsageChart(detail:)`；图表的读数跟手，明细只跟“选定”那天（点下、拖完、读屏调节），拖动途中不请求；今天也请求（报表里没有今天的对话），请求途中/失败时先用 `report.today` 画模型行；对话累计和某天明细共用 `UsageTotal` 形状（某天外面包一层 `UsageDayDetail` 带 `conversations`，份额 `shareOf` 按当天算）
- 导出本月用量 CSV（`test/usage_csv_test.dart`）：格式只在 `models/usage_csv.dart`（`usageCsv`/`usageCsvFileName`，与网页 lib/usageCsv.ts 同规则；汇总行带上月同期/上月全月，服务器有 last_month 才出）；UsageScreen AppBar 的 `_ExportButton` 报表加载完才可点，经 `core/share.dart` 分享（mime text/csv）。不多发请求。
- 对比上月同期（`test/usage_compare_test.dart`）：口径与涨跌只在 `models/usage.dart`（`LastMonthUsage`、`UsageReport.comparesMoney/monthDelta`，同期为 0 或老服务器 → null）；界面是 `usage_screen.dart` 的 `MonthCompare`（月卡大数字下面），颜色只取 Palette（涨 warning、降/持平 text2），带读屏标签（Semantics 要 container: true，否则会被合并掉）。
- 本对话用量（`test/conversation_usage_test.dart`）：`conversationUsageProvider`（autoDispose.family，键 = 对话 id）只在 conversation_usage.dart；ChatScaffold 把页面标题包进 `ChatTitle`，刷新只在换对话和 streaming true→false 时（ref.invalidate，沿用旧值不闪，SwapSwitcher 换字）；新对话/没调用过/出错 → 不显示也不可点；措辞 `usageLine()` 与网页 lib/usage.ts 一致
- 每个对话选模型（`test/model_choice_test.dart`）：列表只来自 `model_choice.dart` 的 `modelCatalogProvider`（缓存先行），生效项/回落只认 `ModelCatalog.effective`；选择只归 `ChatState.model`（null = 默认），改只经 `ChatController.setModel`（已有对话立刻 PATCH；新对话或 PATCH 没成功 → 随下一条 user.message / regenerate 带 `model`）。`ModelChip` 经 `Composer.accessory` 插进输入框，Composer 不认识它；非默认模型加一圈 text3 细边（不上强调色）
- 外部 → App 用深链 `myassistant://app/<路由>?…`（scheme 常量在 `core/links.dart`），go_router 直接当路由打开；页面从路由参数拿结果，不另写监听

## 截图（设计改版每阶段交付前）
```
mkdir -p /tmp/shots/fonts && cd /tmp/shots/fonts && \
  curl -sL -o NotoSansSC.ttf "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" && \
  curl -sL -o NotoSerifSC.ttf "https://github.com/google/fonts/raw/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf" && \
  curl -sL -o NotoEmoji.ttf "https://github.com/google/fonts/raw/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf"
TZ=Asia/Shanghai SHOTS=1 flutter test test/screens/shots_test.dart   # 输出 /tmp/shots/out/{light,dark}-{home,home-focused,chat,projects,me}.png
```
默认跳过；画面是真 App + 假数据，和 `../../docs/design-refs/` 对照看。

## 出包
- 推到 GitHub → Actions → app → 下载 `assistant-android`（选 `arm64-v8a` 那个 APK 装到手机）
- 本地：`flutter build apk --release`（需要 Android SDK）
- iOS：Actions 手动运行并勾选 iOS；装到 iPhone 需要苹果开发者账号签名
- 子页面（`test/sub_page_test.dart`）：`SubPage(title:, actions:, body:)` 代替 `Scaffold(appBar: AppBar(...))`；卡片用 AppCard/ListGroup（玻璃材质，减少透明度时实色），下拉刷新用 kit 的 `PullRefresh`（转圈从标题栏下面出来）。不要对 lib 跑 `dart format`（新格式器会重排全部文件）。
- 字样：theme/app_theme.dart 里的 `t()` 是唯一字样工厂（平台系统字族 + 表情兜底）。主题里任何不经过 textTheme 的样式（AppBar 标题、按钮字、SnackBar）都必须用它，不写裸 `TextStyle(...)`。登录页也在 Backdrop 上，表单是 GlassSurface。截图回归现在还拍 `-usage`/`-brief`（子页面）、`-login` 和 `-sheet-form`/`-sheet-actions`（玻璃弹层）。
- 设计 v2.1「克制」（v0.55）：强调色一屏最多两处（未读点、进度条、链接）；主按钮/用户气泡/导航选中/发送键用 `p.ink`/`p.onInk`。字重只用 `Weights.body/title/strong`（页面禁写 w700，`test/design_test.dart` 守着）；页面主标题用 `displayMedium`、大数字 `displaySmall`/`headlineMedium`（主题里已是衬线 + 等宽数字，不再手动 `.serif`）。行首图标用 `IconBadge`（细线、无色块）；卡片不加外投影，顶边高光由 `GlassSurface`/`AppCard` 自带。
- 实色守卫（`test/sheet_test.dart`）：`surface2` 只许出现在 `lib/theme/` 和 `ui/glass_mode.dart`，别处一律 `context.tileFill`；外投影只许在 `ui/glass.dart`（floatShadow），页面不写 boxShadow / elevation。
- 强调色克制落地（v0.60）：`p.accent`/`accentSoft` 只做信号——未读点、进度/运行中、链接/搜索命中、唯一关键状态（浏览器接管）。数据条/图表/占比条用 `p.ink`，状态字、标签、成功勾用 `p.text2`；TextButton 前景是墨色。`test/design_test.dart`「强调色克制」按文件登记允许次数，新增用法先登记角色。

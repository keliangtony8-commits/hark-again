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
  features/             home（面板卡头：刷新 + “更多”菜单 = 编辑面板 / 刷新记录 / 移除；inbox.dart 收件箱未读：轮询节奏、角标、横幅；action_card.dart 主动建议卡 + cardTargets 去处表，如预算提醒 → 查看用量；card_snooze.dart 稍后提醒唯一入口：卡头小钮 showSnoozeSheet（快捷时刻与一次性任务共用 models/time_shortcuts.dart）+ “为你准备”/“收件箱”底部 SnoozedCards 一行（叫法 snoozeNoun：建议=稍后提醒、报告=稍后再看），点开现在放回；report_actions.dart 收件箱行 InboxRow + showReportActions 唯一入口：点行打开、长按/行尾“更多” = 稍后再看 / 标为已读（未读才有）/ 收起）/ chat（chat_scaffold 聊天骨架：手机历史在抽屉、平板双栏常驻；history_panel 历史栏：搜索/分组/重命名/置顶，主聊天和项目共用，点内容命中 = open(id, focus: message_id) 定位到那条消息（ChatView 往上翻屏直到建出来 → ensureVisible → motion.dart 的 FlashHighlight 闪一下）；chat_cache 对话离线缓存 + 发件箱持久化；model_choice 可选模型列表 + 输入框模型钮；conversation_usage 顶栏标题下的本对话用量 ChatTitle + 明细弹层（右上角“分享为网页”）；conversation_share 分享对话：conversationShareProvider(id) + showConversationShare 唯一入口，历史长按菜单与用量弹层共用） / projects（projects_screen 列表：衬线页头 + 按最近活动排序 + 同形骨架，卡片 ⋯/长按菜单；project_form.dart showProjectForm = 新建/编辑名称图标的唯一入口，createProject/editProject/deleteProject 列表与项目内共用；含项目文件；project_brief_screen 规则与档案页 /projects/:id/brief：进页静默 reload、查看=ui/markdown.dart AppMarkdown、编辑=等宽输入框 + 字数、未保存返回要确认、保存 PATCH {brief}）/ me（记忆 memory_screen：概括卡 memory_digest（MemoryDigestController：进页 GET、memoriesProvider 一变静默重取、只在点“生成/更新”时 POST；接口不存在就不显示）+ SearchField + 分类筛选条 + 分组列表，筛选逻辑在 models/memory.dart；定时任务 tasks_screen 列表（v0.77 摘要 + “下一个”页头、需要留意/在跑/Home 面板/已停下 分组（task_library.dart 纯逻辑：groupTasks/taskSummary/nextUp/taskStarters）、行错峰 + 停下变淡 + 左滑删除、空列表起步模板预填表单；新建、详情“编辑”、主页面板菜单“编辑面板”都用 task_form.dart showTaskForm（唯一任务表单，编辑只发改了的字段；面板 repeatOnly 无“一次”），计划用 schedule_picker.dart：SegmentedButton 重复/一次 + cron 常用项 / 一次性快捷时刻 + “选时间…”展开 CupertinoDatePicker 滚轮（RiseSwitcher），状态在 ValueNotifier<TaskPlan>，TaskPlan.toJson 两个字段都带）（上次失败挂红点 DotBadge）+ task_detail 详情（状态文案只在 task_labels.dart：排队 > 上次失败 > 下次运行/马上运行/已暂停，读服务端 next_run_at；运行记录、排队/运行中每 Timing.taskRunPoll 轮询、结束即停、报告那次 openConversation）、连接器、技能（skills_screen：v0.75 摘要小标签 + 说明、≥7 条给搜索、“我的”为空给起步模板（skill_library.dart：filterSkills/skillSummary/skillStarters 纯逻辑，新建页经 GoRouter extra 接模板）、行错峰入场；编辑页内置原样=阅读态（AppMarkdown 渲染步骤），可编辑时步骤“编辑/预览”、只有真改了才能存、带着改动返回 PopScope 确认；自定义版归“内置”组带“已自定义”，编辑页 _Origin 卡给“复制一份来改 / 恢复默认”，都走 skillsProvider.act(id, customize|reset)；行尾 Switch 和编辑页“启用”行共用 toggleSkill（乐观拨动、失败拨回），停用的行用 motion.dart Dimmed 变淡，Pages 下线行同用 Dimmed / tokens Op.dimmed）、保险箱、Pages（pages_screen：PageRow 按发布状态给菜单，下线/重新发布/重命名都走 pagesProvider.patch，分享走 core/share.dart shareLink）、用量与花费 usage_screen）/ auth
  shell/app_shell.dart  外壳 = Backdrop → 当前 Tab → FloatingTopBar；三个一级入口（主页/聊天/项目），顶栏只在一级路径（shellRoots）显示，子页面时 FloatAway 隐藏
  shell/top_bar.dart    浮动顶栏：左侧空位 + 居中 SegmentedNav（玻璃胶囊 + 滑块，主页带未读点）+ 头像（push /me）
  shell/launch_composer.dart 主页/项目底部的输入胶囊 LaunchComposer：同一个 Composer，发出 = askInNewChat（新对话 + 切到聊天）；聚焦 = FrostScrim 磨砂 + 左侧“收起”+ 上方建议（starterPrompts，聊天空状态共用）；返回键先收起
  shell/shell_page.dart 一级页面外框：把顶栏高度加进 MediaQuery.padding.top（内容可滚到顶栏下面），在顶栏左侧空位画本页的上下文按钮（lead），可选 header 行（主聊天标题）；内容外包 kit TopFade（ShaderMask 只改透明度）：fadeClearOf 以上全透明（有 header 到 header 底边，没有到顶栏中线），到让位线全显——滚上去的内容不和标题/头像叠字
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
- 引用项目文件（v1.13，`test/project_file_refs_test.dart`）：Composer(projectId:) 的“添加附件”多一个“项目文件” → `features/projects/project_files_sheet.dart` pickProjectFiles（唯一选择器，多选、taken 不可重选、maxMessageFiles=10）→ 托盘 `Attachment.ref`（角上文件夹记号，不上传）；ChatController 把 source=project 的块发成 `project_files`、其余发成 `attachments`。网页同款：Composer `projectId` → kit Menu → features/projects/ProjectFilePicker.tsx；lib/files asFileBlock/projectFileBlock/MAX_MESSAGE_FILES
- 编辑最后一条用户消息（`test/edit_test.dart`）：`ChatState.editableId` 是唯一判据；`ChatController.edit(text)` 与 regenerate 共用 `_rewind`（带 text）。气泡长按出菜单（复制 / 编辑），因此用户气泡不再用 SelectableText。编辑态是 ChatView 的界面状态（`EditDraft`），Composer 显示“编辑消息”条、暂存原草稿、收起附件托盘；安卓返回键先退出编辑（PopScope）
- 停止生成（`test/stop_test.dart` 兜底）：`ChatController.stop()` 发 `message.cancel`、置 `stopping`（`ChatState.canStop` 是唯一判据），不在本地先砍，等服务器的 message.done（`Message.stopped`）或 message.stopped 收尾；`copyWith` 在 streaming 变 false 时自动清 stopping。Composer 生成中右侧圆钮换成停止键（同一个 `_RoundButton` + AnimatedSwitcher 缩放），停下的回复在操作行尾标“已停止”
- 导出对话（`test/export_test.dart`）：格式只在 `models/export.dart`（每条正文复用 `copyText`，与网页 lib/export.ts 同规则，只导已进服务器的消息）；取数只在 `ChatController.exportMarkdown`（服务器优先，断网退回离线缓存）；系统分享只经 `core/share.dart`（share_plus 只在这里）；入口是历史栏长按菜单“导出 Markdown”
- 卡片去处（`test/budget_card_test.dart`）：HomeCard.target 只在 action_card.dart 的 cardTargets 映射成按钮，未知值当没有；点去处先标已读再 go；忽略后刷新收件箱未读
- 用量与花费（`test/usage_test.dart`）：只读 `GET /api/usage`，`usageProvider`（autoDispose）在 usage_screen.dart，我的页那一行副标题也读它；预算档位只认 `UsageReport.level`（≥80% warning、≥100% danger），客户端不算钱；没配单价时只显示 token 并提示去 .env 配 MODEL_PRICES。本月零调用（`UsageReport.idle`）→ 统计格下面一张 EmptyHint 说明卡，不画全零的每日图（v0.88）。“我的”页页头身份行 `_Identity` = 用户名（`core/session.dart` 的 `accountNameProvider`，GET /api/auth/me，失败 → null 只显示域名）· 服务器域名，`test/me_identity_test.dart`。按模型列表 `ModelUsageList` 在 usage_screen.dart，本对话明细也用它。“本月每天”柱状图在 usage_chart.dart（`test/usage_chart_test.dart`）：数据只来自报表的 daily，不另请求；CustomPainter 画柱，入场用 motion.dart 的 `GrowIn`，高度 `Layout.chartHeight`；选天默认跟着今天，点/拖/读屏上下滑都走同一个 `_pick`；日均预算 = `UsageReport.dailyPace`（有预算且定价才有）。
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

- v0.67：features/chat/thought_view.dart 管“思考”的两种样子（生成中 ThinkingCard 带秒数；完成后 ThoughtSummary 可展开）；内容下方的小图标键一律用 ui/kit.dart 的 QuietAction / CopyAction（复制原地变对勾，不弹提示条），图标换状态用 motion.dart 的 PopSwitcher，箭头转向用 TurnIcon。
- v0.69：数字展示值统一走 motion.dart 的 CountUp（ValueTile 已接；解析规则在 ui/format.dart NumberParts：恰好一个数字才滚），“加载 ↔ 内容 ↔ 空状态”换态统一用 FadeSwitcher（给 child 随态变化的 key）；新时长令牌 Motion.count。网页对应 ui/CountUp.tsx + lib/numberParts.ts（--dur-count），入场错峰用 base.css 的 .enter + style --i。
- v0.71：骨架要和真实内容同形同高（用量页 _ReportSkeleton，尺寸在 Layout.skeleton*），整页 loading/error/data 用 FadeSwitcher 换态；滚动数字外面包 Semantics(excludeSemantics) 只念终值。网页错峰序号统一用 ui/kit.tsx 的 stagger(i)，区块用 <Section enter={i}>。
- v0.70：聊天记忆卡 blocks/memory_block.dart（MemoryBlock 块）。状态不存块里，models/memory.dart memoryCardState 对照 memoriesProvider 推算（unknown/active/undone/diverged）；撤销只走 memoriesProvider 的 remove/patch/create；chat_controller 收到记忆卡 invalidate(memoriesProvider)。网页对应 blocks/MemoryBlock.tsx + lib/memoryStore.ts（记忆页与记忆卡共用的唯一记忆列表仓库，useMemories）。
- v0.78：内容卡 blocks/content_blocks.dart：DraftBlockView（tileFill 小块，原样 SelectableText，CopyAction + 分享 core/share.dart shareText）、SummaryBlockView（AppCard，subtitle labelSmall + titleLarge，foldable(>600 字或 >14 行) → kit FoldedBox(Layout.summaryFold) 底边渐隐，展开/收起 = FadeSwitcher 按 open 换 key + TurnIcon）、ImagesBlockView（单张 AspectRatio 4:3、多张横排 Layout.imageStrip×imageTileWidth 错峰入场；motion.dart fadeInFrame 下好淡入，坏图 broken_image 占位；点开 showImageViewer = GlassDialog + InteractiveViewer + 打开原图）。ImageItem.safe 只认 http(s)。测试 test/content_blocks_test.dart。
- v0.82：Pages 页与记忆页接入 PageIntro/StarterCard。纯逻辑 features/me/page_library.dart（groupPages 在线/已下线 + 最近更新在前、pagesSummary、pageStarters → askInNewChat）；models/memory.dart 加 memorySummary / memorySearchFrom=7 / memoryStarters（_add(content:, category:) 预填表单）。两页都 PullRefresh + 整页 Motion.stagger 错峰 + SectionTitle(count:)；AsyncBody 不再传 empty，空态由页面自己画起步卡（与保险箱同）。测试 pages_test / memory_screen_test 扩充。
- v0.79：子页页头/起步卡收进 kit：PageIntro(summary, line)（摘要小字 + 说明，两行都 SwapSwitcher）、StarterCard(title, text, starters)（空列表的起步按钮卡，自带 FadeSlideIn）、SectionTitle(count:) 行尾数量；技能/定时任务/连接器/保险箱四页共用。纯逻辑 features/me/connector_library.dart（sortAccounts 已连接→可连接→未配置、connectorSummary、groupSecrets/vaultSummary、secretHint 只露 ••••末四位、secretKinds）。连接器页：账户排序 + 未配置 Dimmed + 尾部“已连接/连接” SwapSwitcher，MCP 空 → StarterCard，有了 → 标题行 QuietAction 添加，MCP 列表 FadeSwitcher 四态，工具弹层页头（N 个工具 · host）+ 错峰；保险箱：+ 移到 AppBar、空 → 两类起步按钮直开对应表单、点行 → 操作菜单删除（左滑之外的明面入口）、addSecret(kind:) 唯一入口。测试 test/connector_library_test.dart。
- v0.80：修主聊天叠字（截图里标题“额度”压在滚上去的消息上、用户气泡顶到头像）。ui/kit.dart TopFade(clear, solid)，ShellPage 用它包页面内容（header/lead 不包），ShellPage.fadeClearOf(top, headerHeight)。测试 test/shell_page_test.dart；截图样例 /api/usage 补 tokens/calls。
- v0.83：表单卡 blocks/form_block.dart（登录/验证码）：BlockActions 新增 onForm(id, values|null, remember) → bool（false = 断线，保留输入），chat_controller.replyForm 发 form.reply。登录卡包 AutofillGroup + autofillHints（系统密码管理器可填），验证码 oneTimeCode + 数字键盘；密码默认遮住可切换；填满才能提交；发出后清空并 RiseSwitcher 收起，PopSwitcher 图标换勾。测试 test/form_block_test.dart。
- v0.85：助手提议的 Home 建议卡。HomeCard `actionLabel`/`origin`，`offered`（origin=agent）/`actionText`（空 = 去做）；features/home/action_card.dart 提议卡标题上一行“可以替你做”、主按钮用 actionText，点了先 onDo 再 PATCH dismissed + 刷新未读（系统提醒不收起）。测试 test/home_offer_test.dart（复用 budget_card_test 的 pump）。
- v0.84：回复按段排版。models/block.dart `replySegments`/`standsAlone`：正文类块合成一张回复卡（bubbleMax），卡片类块（审批/订单/表单/商品/摘要/浏览器）单独成卡、宽度占满聊天区封顶 `Layout.chatCardMax`；运行中工具条跟在最后一段正文，最后一段是卡片就另起小回复卡。交互卡外框只用 blocks/block_frame.dart `BlockFrame(tone: calm|waiting|live)`（和 AppCard 同一种玻璃 + 顶边高光，Radii.lg），别再手写 AnimatedContainer 边框。`FadeSwitcher(alignment:)` 短字换态传 topStart。截图 shots_test 新增 `-chat-shop`/`-chat-shop-top`/`-chat-form`。测试 test/reply_segments_test.dart。
- v0.86：商品卡 blocks/commerce_blocks.dart 按 `ProductsBlock.hasPictures` 选版式：有图排宫格（缺图格子 `_Monogram` 字标占位），一张都没有排清单 `_ProductRow`（字标小格 + 名字/补充 + 价格 + 有链接时 north_east 小箭头）；字标规则 models/block.dart `monogramOf`（网页 lib/monogram.ts 同规则）。截图样例主页加了助手提议卡（origin=agent，要带 action_prompt 才有主按钮）。
- v0.91：主页建议卡配图/原页在 features/home/action_card.dart 的 OfferImage（卡顶 AspectRatio Layout.offerImageRatio + NetImage，有原页点图打开）/ OfferSource（“来源 · 域名 ↗”，≥ A11y.minTap）；HomeCard.imageUrl/linkUrl 只认 http(s)，linkHost 去 www.。网页 features/home/OfferMedia.tsx 同义。
- v0.93：Home 卡片去处表只在 features/home/action_card.dart `cardTargets`（值 = 名字 或 名字:id，`splitTarget`/`cardRoute` 填 {task}/{id}，缺了退列表页）；助手卡只有去处没有指令时眉题“需要你亲自处理”、去处按钮是主按钮。
- v1.00：行尾状态一律 `RowHint`（Pill 只留给页头/卡片里的信号）；页面级动作（新建）放 SubPage `actions`，SubPage 没有悬浮钮参数，design_test 守着不准用 `FloatingActionButton(`。截图新增 `-tasks`（正常 / 自动暂停 / 手动停）。
- v0.99：任务自动暂停（`ScheduledTask.failStreak/pausedReason/autoPaused`）：文案只在 task_labels.dart（`taskStateLabel` / `nextRunLabel` / `autoPauseNote`），分组 `taskIdle()`（自动暂停进“需要留意”、不变淡），列表行用 RowTile `problem:`，详情页 `_PauseNote` 说明条在 FadeSwitcher 里，恢复后收起。
- v0.98：行尾“状态”用 kit `RowHint`（小字），“动作”用 `PillButton(dense: true)`（看着 32 高，可点区仍 48）；RowTile 的问题用 `problem:`（只染那几个字，后接 · 副标题），MCP 列表经 `sortServers` 有问题的在前。截图新增 `-connectors`。
- v0.97：连接器页 MCP 行按 McpServerItem.problemText 显示“连不上 · host” + 警示图标（SwapSwitcher），关掉工具弹层后刷新列表（打开工具列表 = 后端体检）。
- v0.94：建议卡“来源”行自带 minTap 高度，前后只补 Sp.x1（不再叠 Sp.x4）。截图新增 `-home-end`（主页往下翻，含“需要你亲自处理”卡 k5）。
- v0.92：卡片里的输入框用 theme/field_border.dart 的 `compactField(label:, suffix:)`（紧凑版，表单卡在用；弹层/整页仍用主题默认）；一级页面上沿渐隐 TopFade 是缓入曲线，到让位线下 `Layout.topFadeRamp` 才全显（ShellPage.fadeSolidOf），列表顶部留白别小于它。截图样例的图片走 shots_test `_seedImage`（塞图片缓存，测试里没网）。
- v0.90：输入框外形只用 theme/field_border.dart 的 FieldBorder（填充式圆角块，isOutline=false，标签浮在块里；聚焦一圈细线）；别再用 OutlineInputBorder 配带标签的输入框。换对话时 chat_view 把列表跳回 0（最新一条）。截图新增 `-chat-ask`（信息表单），主页样例含“已交给助手”的建议卡。
- v1.01：Home“今天”日程规则只在 features/home/today_agenda.dart（todayAgenda/agendaSummary/agendaHint/agendaProblem/agendaDetail；cron 今天的时刻 core/cron.dart cronTodayAt），画法 home_screen.dart TodaySection；网页 features/home/todayAgenda.ts 同规则。测试 test/today_agenda_test.dart。
- v1.05：早间简报一键排 = task_library.dart `prepDayPrompt` / `morningBrief`（TaskStarter 早间简报 07:00，起步模板第一个）/ `briefTaskOf`（today_agenda.dart 再导出）；TodaySection `onSchedule` → home_screen 调 tasks_screen `createTask(starter: morningBrief)`；没排时 WidePill 下 FadeSwitcher 一颗 dense PillButton“每天早上自动准备”，排了就收起。
- v1.04：日程“现在”线 = today_agenda.dart `agendaNowAt`（前后都有事才画）+ home_screen `_NowLine`，经 `GlassGroup(separator:)` 替掉那一格分隔线（separator 返回 null = 默认细线；行首不是图标的列表用它把细线对齐标题边）。Markdown 标题层级只在 ui/markdown.dart（h2 = titleMedium + 上距 Sp.x3，h3 = titleSmall text2）；摘要卡标题 headlineMedium 衬线、subtitle 在下。截图 shots_test `-chat-day`（c5 简报卡）。
- v1.02：日程里只有“已完成”变淡（`AgendaItem.faded`），失败不淡；截图新增 `-home-today`（任务样例按现在时刻排，_cronAt）。
- v1.06：ChoiceChip 外观只来自 theme chipTheme（StadiumBorder、无描边、未选 tile + text2 = labelStyle、选中 ink + onInk = secondaryLabelStyle；别在 chipTheme 里用 WidgetStateTextStyle，字色会丢），测试 test/chip_theme_test.dart。任务行失败（非运行中）和自动暂停都走 RowTile.problem（问题字在前）。截图新增 `-memory` / `-vault`。
- v1.07：报告的收件箱行副标题 / 横幅第二行只用 models/resources.dart 的 HomeCard.glance / InboxItem.glance（headline · gist，老服务器退回纯文本），页面别再自己截正文。测试 test/report_glance_test.dart。
- v1.08：“新来了一条”只经 features/home/inbox.dart 的 `inboxArrivalProvider` 广播（InboxNotifier._apply 写，InboxWatcher 读/清）——别再让横幅依赖“是外壳自己问到的”。InboxWatcher 包住外壳整层（横幅在顶栏之上）。行“关着”用 `RowTile(dimmed:)`（只淡图标和文字，行尾开关不淡）；整行都不能用才外包 Dimmed。开关关着的轨道有 text3 细线（theme switchTheme）。截图新增 `-home-inbox` / `-banner` / `-pages` / `-skills` / `-project`。测试 inbox_test（谁问到都弹）、row_dimmed_test。
- v1.10：项目页标题栏只留“项目对话”+ ⋯（`showProjectMenu` 唯一菜单，列表卡和项目内共用）；没消息时 ChatScaffold/ChatView 的 `empty:` 画项目首屏 features/projects/project_home.dart（`projectRecent`/`projectLine` 纯规则；双栏不画最近对话）。截图 `-project` 前要 runAsync 等项目对话列表（缓存是真异步）。
- v1.11：项目首屏“文件”一节（`projectRecentFiles`/`projectFileLine` 纯规则在 project_home.dart；看 `projectFilesProvider`，文件抽屉改完自动刷新）；文件图标 `projectFileIcon`、打开 `openProjectFile`（路径逐段编码）是 project_files_sheet.dart 里唯一入口。ProjectFile 多了 `modified`（Unix 秒 → DateTime）。
- v1.12：kit SectionTitle 行固定 A11y.minTap 高（上距 Sp.x5、下距 0），行尾有没有按钮节奏都一样；页面不要在 SectionTitle 前后再加 SizedBox。
- v1.15：回复操作行多一颗“存到项目文件”（MessageView/_ReplyActions `onSave`，ChatView 给已落库的回复）；唯一入口 features/projects/save_reply.dart `saveReplyToProject(context, ref, messageId:, projectId:)`：项目对话直接存，主聊天先弹 `_ProjectPicker`（`saveTargets` 最近活跃在前）；提示 `savedReplyText`，存好刷新已打开的 projectFilesProvider。测试 test/save_reply_test.dart。
- v1.14：输入框附件托盘 features/chat/attachment_tray.dart：本机图片 = 方缩略图（`Attachment.asThumb`），其他 = 名片（类型角标 + 名字 + `Attachment.sub` 一行：上传中… / 大小 / 项目文件 · 大小），同高 `Layout.attachThumb`、名片宽 `Layout.attachChip`，小叉外框 `_Removable` 共用。项目文件行一律“标题 = 文件名、副标题 = `projectFileLine`（文件夹 · 大小）”，该函数搬到 project_files_sheet.dart（project_home 再导出）。网页同规则：lib/files `attachSub`，选择器/文件抽屉用 projectHome `projectFileLine`。截图新增 `-project-picker` / `-project-refs`。
- v1.16：横向滚动条右缘渐隐用 kit `EdgeFadeEnd`（width = 列表右内边距，只改透明度；输入框待发托盘在用）。回复操作条顺序固定：复制 · 朗读 · 重新生成 · 存到项目文件（与网页同序，save_reply_test 守）。shots_test 多一张 `-save-picker`。

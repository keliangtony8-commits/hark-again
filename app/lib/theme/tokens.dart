// 设计令牌：App 里所有颜色、间距、圆角、字号、动效只在这里定义。
// 与网页版 frontend/src/styles/tokens.css 同源，两端视觉一致。
// 组件里禁止写死任何颜色或时长——要新值就先加到这里。
// 对比度底线（test/a11y_test.dart 会查，网页 scripts/check-contrast.mjs 同一批配对）：
// 正文 text/text2、气泡字 onUserBubble、按钮 onInk/onAccent、警示 warning 与 danger/success ≥ 4.5:1；text3 ≥ 3:1。
import 'package:flutter/material.dart';

@immutable
class Palette {
  const Palette({
    required this.bg,
    required this.surface,
    required this.surface2,
    required this.border,
    required this.text,
    required this.text2,
    required this.text3,
    required this.accent,
    required this.accentSoft,
    required this.onAccent,
    required this.danger,
    required this.warning,
    required this.success,
    required this.shadow,
    required this.backdrop,
    required this.glass,
    required this.glassBorder,
    required this.ink,
    required this.onInk,
    required this.userBubble,
    required this.onUserBubble,
    required this.glassHighlight,
    required this.avatar,
    required this.scrim,
    required this.tile,
    required this.glassSheet,
  });

  final Color bg, surface, surface2, border, text, text2, text3;
  final Color accent, accentSoft, onAccent, danger, warning, shadow;

  /// 文件改动里“新增”的绿（v1.34 diff 的 + 行与 +N）；删除用 danger。只给 diff 用，不当第二个强调色。
  final Color success;

  /// 设计 v2 的“壁纸 + 玻璃”：
  /// backdrop = 底层渐变的三个色标（左上 → 中 → 右下），低饱和；
  /// glass = 浮层玻璃的着色（带透明度，下面是模糊后的内容）；glassBorder = 玻璃的 1px 发丝边；
  /// glassHighlight = 玻璃卡片顶边 1px 的内高光（v2.1：卡片不要外投影，靠发丝边 + 这条高光分层）。
  final List<Color> backdrop;
  final Color glass, glassBorder, glassHighlight;

  /// 设计 v2.1「墨色」：主按钮、用户气泡、导航选中块、发送键用它，不用强调色（强调色一屏最多两处：未读点、进度、链接）。
  /// 浅色 = 近黑，深色 = 暖白；onInk 是压在上面的字（≥ 4.5:1，test/contrast_test.dart 查）。
  final Color ink, onInk;
  /// §L 用户气泡：学 Hark 的中性偏灰，不用纯白/纯黑（v2.90.1）。
  final Color userBubble, onUserBubble;

  /// 分段导航选中的实心胶囊 = 墨色（v2 起的名字，保留给顶栏读）。
  Color get pillOn => ink;
  Color get onPillOn => onInk;

  /// 没自选颜色时的头像底：中性、柔和，上面用衬线首字 + 正文色。
  final Color avatar;

  /// 输入胶囊聚焦时盖在页面上的那层（再加 Glass.scrimBlur 的模糊）：把注意力收到输入框上。
  final Color scrim;

  /// 玻璃卡片里再嵌一层的“小块”（面板里 标签 + 大数字 的 tile、卡片里的次要胶囊按钮）：比卡片深一点。
  final Color tile;

  /// 底部弹层的玻璃：比浮条（glass）更实，表单字要压得住底下被模糊的页面（= 网页版 --glass-sheet）。
  final Color glassSheet;

  /// v2.80「Hark 式」浅色（home-redesign.md F）：暖白底、白卡不描边、唯一强调色 = 近黑（主按钮黑胶囊）。
  static const light = Palette(
    bg: Color(0xFFF5F4F1),
    surface: Color(0xFFFFFFFF),
    surface2: Color(0xFFF1EFEC),
    border: Color(0xFFE8E5E0),
    text: Color(0xFF111111),
    text2: Color(0xFF64605A),
    text3: Color(0xFF857F77), // 次要信息（时间戳、图标）：对底色 ≥ 3:1
    accent: Color(0xFF111111), // 唯一强调色 = 墨色：未读点、进度、链接
    accentSoft: Color(0xFFEDEBE7),
    onAccent: Color(0xFFFFFFFF),
    danger: Color(0xFFC43D3D),
    warning: Color(0xFF9A5B00), // a11y：这个色到处当小字用（bodySmall/labelSmall），得够 AA——对浅底 4.93、白卡 5.43；原来 #B86E00 只有 3.62 / 3.99
    success: Color(0xFF2E7D4F),
    shadow: Color(0x141C1B1A),
    backdrop: [Color(0xFFF3F1ED), Color(0xFFF7F6F3), Color(0xFFEFECE7)], // 三档暖白，几乎看不出渐变
    glass: Color(0xD9FFFFFF),
    glassBorder: Color(0x121C1B1A), // = 分隔线
    glassHighlight: Color(0x00FFFFFF), // F.2：不要玻璃描边/高光
    ink: Color(0xFF111111),
    onInk: Color(0xFFFFFFFF),
    userBubble: Color(0xFFE8E6E2), // 实测 Hark 浅色：暖浅灰配深字
    onUserBubble: Color(0xFF1C1B1A),
    avatar: Color(0xFFE4DFD8),
    scrim: Color(0x4DE4E6EA),
    tile: Color(0x0A1C1B1A),
    glassSheet: Color(0xF2FFFFFF),
  );

  /// 逐色插值：切换浅/深色时 MaterialApp 的主题过渡用它，整屏颜色平滑渐变而不是一跳。
  static Palette lerp(Palette a, Palette b, double t) {
    Color l(Color x, Color y) => Color.lerp(x, y, t)!;
    return Palette(
      bg: l(a.bg, b.bg),
      surface: l(a.surface, b.surface),
      surface2: l(a.surface2, b.surface2),
      border: l(a.border, b.border),
      text: l(a.text, b.text),
      text2: l(a.text2, b.text2),
      text3: l(a.text3, b.text3),
      accent: l(a.accent, b.accent),
      accentSoft: l(a.accentSoft, b.accentSoft),
      onAccent: l(a.onAccent, b.onAccent),
      danger: l(a.danger, b.danger),
      warning: l(a.warning, b.warning),
      success: l(a.success, b.success),
      shadow: l(a.shadow, b.shadow),
      backdrop: [for (var i = 0; i < a.backdrop.length; i++) l(a.backdrop[i], b.backdrop[i])],
      glass: l(a.glass, b.glass),
      glassBorder: l(a.glassBorder, b.glassBorder),
      glassHighlight: l(a.glassHighlight, b.glassHighlight),
      ink: l(a.ink, b.ink),
      onInk: l(a.onInk, b.onInk),
      userBubble: l(a.userBubble, b.userBubble),
      onUserBubble: l(a.onUserBubble, b.onUserBubble),
      avatar: l(a.avatar, b.avatar),
      scrim: l(a.scrim, b.scrim),
      tile: l(a.tile, b.tile),
      glassSheet: l(a.glassSheet, b.glassSheet),
    );
  }

  /// v2.80「Hark 式」深色（home-redesign.md F）：深海军蓝渐变底 → 近黑不透明卡（无描边）→ 白字；唯一强调色 = 白。
  static const dark = Palette(
    bg: Color(0xFF0D1226),
    surface: Color(0xFF0A0D16),
    surface2: Color(0xFF141824),
    border: Color(0xFF1D2130),
    text: Color(0xFFFFFFFF),
    text2: Color(0xFFA0A4AF), // ≈ 60% 白
    text3: Color(0xFF7F8390),
    accent: Color(0xFFFFFFFF), // 唯一强调色 = 白：未读点、进度、链接
    accentSoft: Color(0xFF1E2230),
    onAccent: Color(0xFF0A0D16),
    danger: Color(0xFFE5675F),
    warning: Color(0xFFE0A040),
    success: Color(0xFF62BD86),
    shadow: Color(0x80000000),
    backdrop: [Color(0xFF0E1428), Color(0xFF121A33), Color(0xFF1B2342)], // 深海军蓝
    glass: Color(0xD90A0D16),
    glassBorder: Color(0x14FFFFFF), // 8% 白 = 分隔线
    glassHighlight: Color(0x00FFFFFF),
    ink: Color(0xFFFFFFFF), // 主按钮 = 白胶囊黑字
    onInk: Color(0xFF0A0D16),
    userBubble: Color(0xFF1B2032), // 实测 Hark 暗色：比背景亮一点的冷蓝灰
    onUserBubble: Color(0xFFF5F5F7),
    avatar: Color(0xFF232838),
    scrim: Color(0x99080B16),
    tile: Color(0x0FFFFFFF),
    glassSheet: Color(0xF20C1020),
  );
}

/// 间距：4 的倍数
abstract final class Sp {
  static const x1 = 4.0, x2 = 8.0, x3 = 12.0, x4 = 16.0, x5 = 24.0, x6 = 32.0, x7 = 48.0;
}

/// 圆角只有三种（v2.80，home-redesign.md F.3）：卡片/气泡/块 card 32 → 卡片里的小块、输入框、缩略图 inner 16 → 胶囊 full。
abstract final class Radii {
  static const inner = 16.0, card = 32.0, full = 999.0;
}

/// 字号。display = 问候语这类页面主标题（衬线、偏细）；xl = 大数字。
abstract final class Fs {
  static const xs = 13.0, sm = 15.0, md = 17.0, lg = 20.0, xl = 32.0, display = 34.0; // v2.80 F.4：字少而大
  static const lineHeight = 1.3; // v2.83 §G：界面文字（标题、行、按钮、标签）紧凑 = 网页 --lh
  static const prose = 1.6; // 只给要“读”的正文：聊天回复（AppMarkdown）、记忆摘要、项目档案 = 网页 --lh-prose
}

/// 字重与字距（v2.1「降一档」）：正文 400、标题/按钮/导航 500、只有页面主标题和大数字 600。
/// 小标签（“为你准备”“本月花费”）不加粗，靠更小字号 + 字距 + text3 色区分。页面里不再写 FontWeight.w700。
abstract final class Weights {
  static const body = FontWeight.w400, title = FontWeight.w500, strong = FontWeight.w600;
  static const labelTracking = 0.5; // 小标签的字距
  static const displayTracking = -0.5; // 大标题、大数字收紧（v2.83 无衬线 600）
}

/// 动效：全 App 共用一套节奏，保证“手感”统一
abstract final class Motion {
  static const fast = Duration(milliseconds: 140); // 按压、开关
  static const base = Duration(milliseconds: 240); // 出现、展开（v2.1：220–280 之间，更沉稳）
  static const slow = Duration(milliseconds: 360); // 页面切换、大块位移
  static const ease = Cubic(0.33, 1, 0.68, 1); // easeOutCubic，和网页版 --ease 相同
  static const spring = Cubic(0.34, 1.12, 0.64, 1); // 弹性很小的回弹（导航滑块、按压松手）：只过冲一点点
  static const rise = 6.0; // 入场时从下面浮上来的距离（淡入 + 上移 6px）
  static const focusLift = 0.02; // 长按聚焦（§J）：被按的那条先放大 2% 再落回
  static const menuFrom = 0.96; // 聚焦菜单卡从 96% 长到 100%
  static const theme = slow; // 浅/深色切换的整屏渐变
  // §O 刚发出的那条气泡往上弹一下（App/网页同一条弹簧：从下方 28px 上移，冲过终点约 5px 再落回，一次过冲不来回抖）
  static const send = Duration(milliseconds: 460);
  static const sendRise = 28.0;
  static const sendDamping = 0.45; // 阻尼比：过冲 ≈ e^(-πζ/√(1-ζ²)) ≈ 20%
  static const sendFresh = Duration(seconds: 1); // 发出 1 秒内首次画出才弹（滚出屏幕再回来、重连同步都不弹）
  // 循环动画的一圈
  static const shimmer = Duration(milliseconds: 1300); // 骨架闪光
  static const typing = Duration(milliseconds: 1100); // 思考中的三个点
  static const pulse = Duration(milliseconds: 1200); // 录音/实时红点
  static const spin = Duration(seconds: 1); // 刷新图标转一圈
  static const flash = Duration(milliseconds: 1600); // 搜索命中的消息闪一下：先停住再淡出
  static const count = Duration(milliseconds: 700); // 面板关键数字滚到新值（入场从 0 起、刷新从旧值起）
  // §N 项目页（v2.91）
  static const morph = Duration(milliseconds: 280); // 左上 ≡ ↔ +：三条线旋转成十字
  static const morphCurve = Cubic(0.65, 0, 0.35, 1); // easeInOutCubic：来回对称（= 网页 --ease-morph）
  static const pageRise = 8.0; // v2.93 §Q 进出项目页：新页从下方 8px 浮上来 + 淡入（与 ≡/+ 同一个 Motion.morph 时长）
  static const pillDrop = 8.0; // 标题药丸从上方落下的距离（出现用 spring，过冲约 2–3%）
  static const pillReveal = 24.0; // 往上翻看历史累计超过这么多像素，药丸浮出
  static const pillHide = 4.0; // 往下滑超过这么多像素，药丸收起（滚动回弹的抖动不算）

  /// 列表错峰入场：第 i 项晚 i 拍，超过 10 项不再加（长列表不拖沓）。
  static const staggerStep = Duration(milliseconds: 30);
  static Duration stagger(int i, {int from = 0}) => staggerStep * (from + i.clamp(0, 10));
}

/// 非动画的节奏：输入防抖等
abstract final class Timing {
  static const searchDebounce = Duration(milliseconds: 300);
  static const inboxPoll = Duration(minutes: 2); // 前台时多久问一次“有新报告吗”（后台不问）
  static const bannerHold = Duration(seconds: 4); // 端内横幅停留多久
  static const taskRunPoll = Duration(seconds: 4); // 任务详情页有运行在排队/进行时多久刷新一次
  static const outboxGiveUp = Duration(seconds: 45); // 待发送的消息等多久没连上就标“发送失败”
  // 聊天长连接（core/chat_socket.dart；节奏参考 Codex remote_control：10 s ping、60 s 没回音算断、连上满 60 s 才清退避）
  static const socketPing = Duration(seconds: 25); // 多久发一次心跳（手机网络常常“假在线”，靠它发现）
  static const socketDead = Duration(seconds: 60); // 这么久什么都没收到 = 线已经死了，主动断开重连
  static const socketStable = Duration(seconds: 60); // 连上保持这么久才把重连退避清零（服务器反复闪断时不狂连）
  static const socketBackoffMin = Duration(seconds: 1); // 重连退避：1 s 起翻倍，封顶 10 s，再乘 0.5–1 的随机抖动
  static const socketBackoffMax = Duration(seconds: 10);
  static const copiedHold = Duration(milliseconds: 1500); // 复制键变成对勾停多久再变回去
  static const pillHold = Duration(milliseconds: 1500); // §N 标题药丸：停下多久后收起
  static const clockTick = Duration(seconds: 1); // “思考中 · 8 秒”这类计时多久跳一次
  static const jobPoll = Duration(seconds: 2); // 聊天里的后台任务卡运行中多久问一次进度
  static const computerPoll = Duration(seconds: 5); // 电脑状态块：有后台任务在跑时多久刷新一次（每次要问 Docker，别太密）
  static const liveRetryMin = Duration(seconds: 1); // 浏览器实时画面断了：1 s 起翻倍重连，封顶 15 s（= 网页 LIVE_RETRY_*）
  static const liveRetryMax = Duration(seconds: 15);
  static const takeoverInput = Duration(milliseconds: 80); // 接管页：拖动/滚动时最多这么久发一次（攒起来发，不是每帧一个请求）
}

/// 玻璃材质（ui/glass.dart 只读这里）。真模糊很贵：只给浮层（顶栏、输入胶囊、弹层），列表里的卡片用“假玻璃”。
abstract final class Glass {
  static const blur = 24.0; // 背景模糊 sigma
  static const scrimBlur = 14.0; // 输入胶囊聚焦时整页的模糊（比浮层轻：还认得出后面是什么）
  static const focusBlur = 28.0; // 长按聚焦菜单（§J）：背景重度模糊，只剩被按的那条清晰
  static const grabber = Size(36, 4); // 弹层顶上那根把手
}

/// 浮层的投影：贴着玻璃的一圈很淡的影子（v0.46 起：不要“贴纸感”的重投影，靠 1px 发丝边分层）。
abstract final class Elevation {
  static const floatBlur = 12.0;
  static const floatY = 1.0;
  static const floatAlpha = 0.5; // 乘在 Palette.shadow 上
}

/// 字体：正文用系统无衬线；衬线只做点缀（问候、品牌词、引导卡大标题），克制使用。
/// 不打包字体（省 10MB+）：安卓有 Noto Serif CJK 就用它，没有就退回系统衬线。
abstract final class Fonts {
  /// v2.83 §G：全 App 只有一种字——无衬线。拉丁/数字 = 打包的 Inter（OFL，assets/fonts，只含拉丁子集，
  /// = 网页 --font-sans 首位）；中文不在 Inter 里，自动落到下面的系统中文字（小米 MiSans、苹方、鸿蒙、思源黑体）。
  /// 不再有衬线/宋体：真机上它落成 Noto Serif CJK，是“丑”的头号来源。
  static const sans = 'Inter';
  static const sansFallback = ['MiSans', 'PingFang SC', 'HarmonyOS Sans SC', 'Noto Sans CJK SC', 'Noto Sans SC', ...emoji];
  static const emoji = ['Noto Color Emoji', 'Apple Color Emoji']; // 表情兜底（项目图标）：系统通常自己会兜，写明了更稳
}

/// 头像颜色（“我的”里点头像改）：只改头像，不动强调色——强调色的对比度是全局校验过的。
/// null = 跟随强调色。头像上的首字母按底色亮度自动选深/浅字。
abstract final class AvatarColors {
  static const presets = [Color(0xFF8A7CC0), Color(0xFF0E9C9C), Color(0xFF4D8BF5), Color(0xFF7D8088)];
  static const wheelSaturation = 0.62, wheelValue = 0.86; // 色轮只选色相，饱和度/明度固定：选出来的颜色都“好看且看得清字”
  static const lightInk = Color(0xFFFFFFFF), darkInk = Color(0xFF1C1B1A);
  static Color inkOn(Color c) => c.computeLuminance() > 0.45 ? darkInk : lightInk;
}

/// 两步验证的二维码（v2.58）：永远黑码白底——验证器 App 只认得这一种，深色模式也不反色。
abstract final class QrColors {
  static const dark = Color(0xFF000000), light = Color(0xFFFFFFFF);
  static const quiet = 2; // 四周留白（模块数）
  static const size = 184.0; // 显示边长
}

/// 不透明度
abstract final class Op {
  static const dimmed = 0.6; // 停用/下线的行：还在，但退到背景里
}

/// 无障碍底线
abstract final class A11y {
  static const minTap = 48.0; // 可点区域最小边长（安卓无障碍指南）
  static const textScaleMax = 1.6; // 系统字体再大也封顶在这，超过后版面不再保证
}

/// 布局
abstract final class Layout {
  static const contentMax = 720.0; // 平板/折叠屏上限制阅读宽度
  static const followSlack = 80.0; // 聊天“贴底跟随”：离最新一条这么近以内算在底部；再往上翻出“回到最新”（= 网页 FOLLOW_SLACK）
  static const topBar = 52.0; // 浮动顶栏（分段导航、头像、左侧上下文按钮）的高度
  static const gutter = 24.0; // 全 App 统一的左右留白（顶栏、页面、浮动按钮都对齐这条线）
  static const cardGap = Sp.x4; // 卡片之间的间距
  static const sectionGap = Sp.x6; // 区块之间（“为你准备”和“面板”之间）
  static const cardPad = Sp.x5; // 卡片内边距 24（F.9）
  static const headTop = 28.0; // 页面主标题（问候语、“我的”）离顶栏多远
  static const cardFace = 1.586; // 钱包里卡面的宽高比（ISO 银行卡 85.6 × 54）
  static const cardFaceMax = 340.0; // 卡面最宽
  static const rowIcon = 22.0; // 列表行首的细线图标（不加色块底）
  static const jobLogLines = 6; // 后台任务卡里日志尾巴显示几行（完整的点“完整日志”）
  static const rowValueMax = 180.0; // 行尾当前值最宽多少（RowTile.value），再长就省略
  static const rowMin = 64.0, rowMinTwoLine = 72.0; // 列表行高：单行 / 带副标题
  static const topBarTop = Sp.x2; // 顶栏离状态栏的距离
  static const shellTop = topBarTop + topBar + Sp.x3; // 一级页面内容要让出的顶部高度（不含状态栏）= 顶栏 + 12
  static const topFadeRamp = Sp.x4; // 让位线下面再渐显这么高（缓入），滚上去的深色气泡不再在标题下切出硬边；≤ 聊天列表顶部留白
  static const avatarLarge = 72.0; // “我的”页头的大头像
  static const wheel = 200.0; // 头像色轮直径
  static const segmentsMax = 320.0; // 分段导航最宽多宽（平板上不拉满）
  static const chatTitle = A11y.minTap; // 主聊天顶栏下那一行（标题胶囊 + 新对话钮）的高度
  static const chatCardMax = 560.0; // 聊天里单独成卡的卡片块最宽多宽（手机上占满聊天区，平板封顶）
  static const bubbleMax = 0.86; // 聊天气泡/回复卡最宽占聊天区的比例（留出一侧空白，看得出谁在说）
  // 窗口断点（Material 3 window size classes），只由 ui/adaptive.dart 读
  static const mediumMin = 600.0; // ≥ 此宽：底部 Tab 换成左侧导航栏
  static const expandedMin = 840.0; // ≥ 此宽：聊天变双栏（历史 + 对话并排）
  static const sidePane = 320.0; // 双栏时历史栏宽度
  static const focusMenuWidth = 232.0; // 长按聚焦菜单卡宽（§J）
  static const focusMenuRows = 5; // 菜单最多直接列几行，再多收进“更多”
  static const dialogMax = 400.0; // 居中对话框最宽多宽（平板上不拉满）
  static const chartHeight = 120.0; // 用量页逐日柱状图的绘图区高度
  static const skeletonHero = 148.0, skeletonStat = 104.0, skeletonChart = 200.0; // 用量页骨架：月卡 / 统计格 / 每日图（与内容同高，换态不跳版）
  static const summaryFold = 280.0; // 摘要卡折起时正文露多高（再长就“展开全文”）
  static const attachThumb = 64.0, attachChip = 184.0; // 输入框附件托盘：图片方缩略图边长 / 文件名片宽（同高 attachThumb）
  static const imageStrip = 176.0, imageTileWidth = 232.0; // 图片卡多张时横排：每张的高 / 宽；单张按 4:3 铺满
  static const productTileMin = 148.0; // 商品宫格每格最窄多宽（手机两列、平板更多列）
  static const offerImageRatio = 2.0; // 主页建议卡顶部配图的宽高比（宽图，不把卡撑太高）
  static const offerImageRatioWide = 2.5; // 窗口 ≥ contentMax（电脑 / 平板）时压扁一点，别一张图占半屏（= 网页 home.css ≥720px 的 5:2，v2.94）
  static const nowDot = 6.0; // 主页“今天”的“现在”标记：细线起头的小圆点
  static const agendaTime = 48.0; // 主页“今天”行首钟点列的宽（HH:MM 等宽数字，上下对齐）
  static const orderThumb = 40.0; // 订单卡每行商品小图的边长
  static const seekPagesMax = 60; // 定位消息时最多往上翻多少屏（防止死循环）
}

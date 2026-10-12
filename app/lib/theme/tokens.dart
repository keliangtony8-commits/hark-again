// 设计令牌：App 里所有颜色、间距、圆角、字号、动效只在这里定义。
// 与网页版 frontend/src/styles/tokens.css 同源，两端视觉一致。
// 组件里禁止写死任何颜色或时长——要新值就先加到这里。
// 对比度底线（test/a11y_test.dart 会查）：正文 text/text2 与 accent 上的 onAccent ≥ 4.5:1，text3 ≥ 3:1。
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
    required this.shadow,
    required this.backdrop,
    required this.glass,
    required this.glassBorder,
    required this.ink,
    required this.onInk,
    required this.glassHighlight,
    required this.avatar,
    required this.scrim,
    required this.tile,
    required this.glassSheet,
  });

  final Color bg, surface, surface2, border, text, text2, text3;
  final Color accent, accentSoft, onAccent, danger, warning, shadow;

  /// 设计 v2 的“壁纸 + 玻璃”：
  /// backdrop = 底层渐变的三个色标（左上 → 中 → 右下），低饱和；
  /// glass = 浮层玻璃的着色（带透明度，下面是模糊后的内容）；glassBorder = 玻璃的 1px 发丝边；
  /// glassHighlight = 玻璃卡片顶边 1px 的内高光（v2.1：卡片不要外投影，靠发丝边 + 这条高光分层）。
  final List<Color> backdrop;
  final Color glass, glassBorder, glassHighlight;

  /// 设计 v2.1「墨色」：主按钮、用户气泡、导航选中块、发送键用它，不用强调色（强调色一屏最多两处：未读点、进度、链接）。
  /// 浅色 = 近黑，深色 = 暖白；onInk 是压在上面的字（≥ 4.5:1，test/contrast_test.dart 查）。
  final Color ink, onInk;

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

  static const light = Palette(
    bg: Color(0xFFFAF9F7),
    surface: Color(0xFFFFFFFF),
    surface2: Color(0xFFF3F1EE),
    border: Color(0xFFE7E4DF),
    text: Color(0xFF1C1B1A),
    text2: Color(0xFF6B6762),
    text3: Color(0xFF8A857D), // 次要信息（时间戳、图标）：对底色 ≥ 3:1
    accent: Color(0xFFB94F27), // 白字压在上面 ≥ 4.5:1（WCAG AA）
    accentSoft: Color(0xFFFBEAE3),
    onAccent: Color(0xFFFFFFFF),
    danger: Color(0xFFC43D3D),
    warning: Color(0xFFB86E00),
    shadow: Color(0x141C1B1A),
    backdrop: [Color(0xFFDDE3EB), Color(0xFFEEECEA), Color(0xFFEBE1DC)], // 雾蓝 → 灰白 → 带一点我们赤陶色的暖灰
    glass: Color(0xB3FFFFFF),
    glassBorder: Color(0x1A1C1B1A),
    glassHighlight: Color(0xCCFFFFFF),
    ink: Color(0xFF22201E),
    onInk: Color(0xFFFFFFFF),
    avatar: Color(0xFFE4DFD8),
    scrim: Color(0x4DE4E6EA),
    tile: Color(0x0F1C1B1A),
    glassSheet: Color(0xE0FFFFFF),
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
      shadow: l(a.shadow, b.shadow),
      backdrop: [for (var i = 0; i < a.backdrop.length; i++) l(a.backdrop[i], b.backdrop[i])],
      glass: l(a.glass, b.glass),
      glassBorder: l(a.glassBorder, b.glassBorder),
      glassHighlight: l(a.glassHighlight, b.glassHighlight),
      ink: l(a.ink, b.ink),
      onInk: l(a.onInk, b.onInk),
      avatar: l(a.avatar, b.avatar),
      scrim: l(a.scrim, b.scrim),
      tile: l(a.tile, b.tile),
      glassSheet: l(a.glassSheet, b.glassSheet),
    );
  }

  /// 深色不是反色（v2.1）：底是带一点蓝紫的炭灰，玻璃更透（alpha 更低），正文 92% 白，墨色按钮是暖白。
  static const dark = Palette(
    bg: Color(0xFF131418),
    surface: Color(0xFF1B1C21),
    surface2: Color(0xFF23242A),
    border: Color(0xFF2C2D34),
    text: Color(0xFFEBEBED),
    text2: Color(0xFFA4A3AA),
    text3: Color(0xFF8B8A91),
    accent: Color(0xFFEF7A4F),
    accentSoft: Color(0xFF3A2219),
    onAccent: Color(0xFF1A0F0A), // 深色下强调色很亮，上面用深字才够对比（6.8:1）
    danger: Color(0xFFE06060),
    warning: Color(0xFFE0A040),
    shadow: Color(0x66000000),
    backdrop: [Color(0xFF1B1F2A), Color(0xFF16171C), Color(0xFF221E2B)], // 蓝灰炭 → 近黑 → 灰紫
    glass: Color(0x8C25272F),
    glassBorder: Color(0x1FFFFFFF),
    glassHighlight: Color(0x14FFFFFF),
    ink: Color(0xFFECE7DF),
    onInk: Color(0xFF16161A),
    avatar: Color(0xFF2E2F38),
    scrim: Color(0x80101114),
    tile: Color(0x33000000),
    glassSheet: Color(0xE01D1F25),
  );
}

/// 间距：4 的倍数
abstract final class Sp {
  static const x1 = 4.0, x2 = 8.0, x3 = 12.0, x4 = 16.0, x5 = 24.0, x6 = 32.0, x7 = 48.0;
}

/// 圆角层级（v2.1）：大卡片 card 24 → 子卡片/气泡 lg 20 → 卡片里的小块 tile 16 → 输入框 md 14 → 胶囊 full。
abstract final class Radii {
  static const sm = 8.0, md = 14.0, tile = 16.0, lg = 20.0, card = 24.0, full = 999.0;
}

/// 字号。display = 问候语这类页面主标题（衬线、偏细）；xl = 大数字。
abstract final class Fs {
  static const xs = 12.0, sm = 14.0, md = 16.0, lg = 20.0, xl = 28.0, display = 34.0;
  static const lineHeight = 1.6;
}

/// 字重与字距（v2.1「降一档」）：正文 400、标题/按钮/导航 500、只有页面主标题和大数字 600。
/// 小标签（“为你准备”“本月花费”）不加粗，靠更小字号 + 字距 + text3 色区分。页面里不再写 FontWeight.w700。
abstract final class Weights {
  static const body = FontWeight.w400, title = FontWeight.w500, strong = FontWeight.w600;
  static const labelTracking = 0.5; // 小标签的字距
  static const displayTracking = -0.3; // 大标题、大数字略收紧
}

/// 动效：全 App 共用一套节奏，保证“手感”统一
abstract final class Motion {
  static const fast = Duration(milliseconds: 140); // 按压、开关
  static const base = Duration(milliseconds: 240); // 出现、展开（v2.1：220–280 之间，更沉稳）
  static const slow = Duration(milliseconds: 360); // 页面切换、大块位移
  static const ease = Cubic(0.33, 1, 0.68, 1); // easeOutCubic，和网页版 --ease 相同
  static const spring = Cubic(0.34, 1.12, 0.64, 1); // 弹性很小的回弹（导航滑块、按压松手）：只过冲一点点
  static const rise = 6.0; // 入场时从下面浮上来的距离（淡入 + 上移 6px）
  static const theme = slow; // 浅/深色切换的整屏渐变
  // 循环动画的一圈
  static const shimmer = Duration(milliseconds: 1300); // 骨架闪光
  static const typing = Duration(milliseconds: 1100); // 思考中的三个点
  static const pulse = Duration(milliseconds: 1200); // 录音/实时红点
  static const spin = Duration(seconds: 1); // 刷新图标转一圈
  static const flash = Duration(milliseconds: 1600); // 搜索命中的消息闪一下：先停住再淡出
  static const count = Duration(milliseconds: 700); // 面板关键数字滚到新值（入场从 0 起、刷新从旧值起）

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
  static const copiedHold = Duration(milliseconds: 1500); // 复制键变成对勾停多久再变回去
  static const clockTick = Duration(seconds: 1); // “思考中 · 8 秒”这类计时多久跳一次
  static const jobPoll = Duration(seconds: 2); // 聊天里的后台任务卡运行中多久问一次进度
  static const computerPoll = Duration(seconds: 5); // 电脑状态块：有后台任务在跑时多久刷新一次（每次要问 Docker，别太密）
  static const screenFast = Duration(milliseconds: 600); // 浏览器画面：你在接管/助手在等你时多久刷一帧（要跟手）
  static const screenOpening = Duration(milliseconds: 1000); // 页面正在打开
  static const screenIdle = Duration(milliseconds: 1500); // 只是看着
  static const screenPauseAfter = Duration(minutes: 2); // 只是看着超过这么久就暂停刷新（省流量），点一下继续
}

/// 玻璃材质（ui/glass.dart 只读这里）。真模糊很贵：只给浮层（顶栏、输入胶囊、弹层），列表里的卡片用“假玻璃”。
abstract final class Glass {
  static const blur = 24.0; // 背景模糊 sigma
  static const scrimBlur = 14.0; // 输入胶囊聚焦时整页的模糊（比浮层轻：还认得出后面是什么）
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
  static const serif = 'serif';
  static const serifFallback = ['Noto Serif CJK SC', 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', ...emoji];
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
  static const topBar = 52.0; // 浮动顶栏（分段导航、头像、左侧上下文按钮）的高度
  static const gutter = 20.0; // 全 App 统一的左右留白（顶栏、页面、浮动按钮都对齐这条线）
  static const cardGap = Sp.x3; // 卡片之间的间距
  static const sectionGap = Sp.x6; // 区块之间（“为你准备”和“面板”之间）
  static const cardPad = Sp.x5 - Sp.x1; // 卡片内边距 20
  static const headTop = 28.0; // 页面主标题（问候语、“我的”）离顶栏多远
  static const rowIcon = 22.0; // 列表行首的细线图标（不加色块底）
  static const jobLogLines = 6; // 后台任务卡里日志尾巴显示几行（完整的点“完整日志”）
  static const rowMin = 56.0, rowMinTwoLine = 64.0; // 列表行高：单行 / 带副标题
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
  static const dialogMax = 400.0; // 居中对话框最宽多宽（平板上不拉满）
  static const chartHeight = 120.0; // 用量页逐日柱状图的绘图区高度
  static const skeletonHero = 148.0, skeletonStat = 104.0, skeletonChart = 200.0; // 用量页骨架：月卡 / 统计格 / 每日图（与内容同高，换态不跳版）
  static const summaryFold = 280.0; // 摘要卡折起时正文露多高（再长就“展开全文”）
  static const attachThumb = 64.0, attachChip = 184.0; // 输入框附件托盘：图片方缩略图边长 / 文件名片宽（同高 attachThumb）
  static const imageStrip = 176.0, imageTileWidth = 232.0; // 图片卡多张时横排：每张的高 / 宽；单张按 4:3 铺满
  static const productTileMin = 148.0; // 商品宫格每格最窄多宽（手机两列、平板更多列）
  static const offerImageRatio = 2.0; // 主页建议卡顶部配图的宽高比（宽图，不把卡撑太高）
  static const nowDot = 6.0; // 主页“今天”的“现在”标记：细线起头的小圆点
  static const projectMark = 56.0; // 项目首屏的字标方块（v1.10；列表卡里是 A11y.minTap）
  static const agendaTime = 48.0; // 主页“今天”行首钟点列的宽（HH:MM 等宽数字，上下对齐）
  static const orderThumb = 40.0; // 订单卡每行商品小图的边长
  static const seekPagesMax = 60; // 定位消息时最多往上翻多少屏（防止死循环）
}

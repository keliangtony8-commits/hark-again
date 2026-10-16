// 设计令牌：App 里所有颜色、间距、圆角、字号、动效只在这里定义。
// 与网页版 frontend/src/styles/tokens.css 同源，两端视觉一致。
// 组件里禁止写死任何颜色或时长——要新值就先加到这里。
// 对比度底线（test/a11y_test.dart 会查，网页 scripts/check-contrast.mjs 同一批配对）：
// 正文 text/text2、气泡字 onUserBubble、按钮 onInk/onAccent、警示 warning 与 danger/success ≥ 4.5:1；text3 ≥ 3:1。
import 'dart:math' as math;

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
    required this.sky,
    required this.glass,
    required this.glassBorder,
    required this.chromeEdge,
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

  /// 设计 v2 的“壁纸 + 玻璃”（v3.3 壁纸换成随钟点流动的天色 sky，见下面 SkyTable）：
  /// sky = 四个时段（夜 / 黎明 / 白天 / 黄昏）的底色与三团柔光；
  /// glass = 浮层玻璃的着色（带透明度，下面是模糊后的内容）；glassBorder = 玻璃的 1px 发丝边；
  /// glassHighlight = 玻璃卡片顶边 1px 的内高光（v2.1：卡片不要外投影，靠发丝边 + 这条高光分层）。
  final SkyTable sky;
  final Color glass, glassBorder, glassHighlight;

  /// v3.1 浮层（顶栏胶囊、圆钮、输入胶囊、头像）的外圈：浅色要一圈发丝边才和暖白底分得开；
  /// 深色 Hark 不描边（实测截图 1000035474），靠玻璃与海军蓝底的明度差分层 → 透明。分隔线仍是 glassBorder。
  final Color chromeEdge;

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
    text2: Color(0xFF5C5852), // v3.3 原 #64605A：压在流光壁纸上也要 ≥ 4.5（test/sky_test.dart）
    text3: Color(0xFF7A746C), // 次要信息（时间戳、图标）：对底色、对壁纸 ≥ 3:1（v3.3 原 #857F77）
    accent: Color(0xFF111111), // 唯一强调色 = 墨色：未读点、进度、链接
    accentSoft: Color(0xFFEDEBE7),
    onAccent: Color(0xFFFFFFFF),
    danger: Color(0xFFC43D3D),
    warning: Color(0xFF9A5B00), // a11y：这个色到处当小字用（bodySmall/labelSmall），得够 AA——对浅底 4.93、白卡 5.43；原来 #B86E00 只有 3.62 / 3.99
    success: Color(0xFF2E7D4F),
    shadow: Color(0x141C1B1A),
    sky: SkyTable.light, // v3.3 流光壁纸（原三档暖白渐变）
    glass: Color(0xD9FFFFFF),
    glassBorder: Color(0x121C1B1A), // = 分隔线
    chromeEdge: Color(0x121C1B1A),
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
      sky: SkyTable.lerp(a.sky, b.sky, t),
      glass: l(a.glass, b.glass),
      glassBorder: l(a.glassBorder, b.glassBorder),
      chromeEdge: l(a.chromeEdge, b.chromeEdge),
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
    surface: Color(0xFF1E2029), // v3.1 实测 Hark 暗色卡 / 回复气泡 #1E2029：中性炭灰，不是近黑（截图 1000035474）
    surface2: Color(0xFF272A34),
    border: Color(0xFF2E313C),
    text: Color(0xFFFFFFFF),
    text2: Color(0xFFA0A4AF), // ≈ 60% 白
    text3: Color(0xFF7F8390),
    accent: Color(0xFFFFFFFF), // 唯一强调色 = 白：未读点、进度、链接
    accentSoft: Color(0xFF2A2D38),
    onAccent: Color(0xFF0A0D16),
    danger: Color(0xFFE5675F),
    warning: Color(0xFFE0A040),
    success: Color(0xFF62BD86),
    shadow: Color(0x80000000),
    sky: SkyTable.dark, // v3.3 流光壁纸（原深海军蓝渐变）
    glass: Color(0xE01B1D25), // v3.1 实测 Hark 输入胶囊 #1B1D25
    glassBorder: Color(0x14FFFFFF), // 8% 白 = 分隔线
    chromeEdge: Color(0x00FFFFFF), // Hark 深色浮层不描边
    glassHighlight: Color(0x00FFFFFF),
    ink: Color(0xFFFFFFFF), // 主按钮 = 白胶囊黑字
    onInk: Color(0xFF0A0D16),
    userBubble: Color(0xFF1B2032), // 实测 Hark 暗色：比背景亮一点的冷蓝灰
    onUserBubble: Color(0xFFF5F5F7),
    avatar: Color(0xFF232838),
    scrim: Color(0x99080B16),
    tile: Color(0x0FFFFFFF),
    glassSheet: Color(0xF51E2029),
  );
}

/// v3.3「流光」壁纸的一个时段：竖向底色（top → bottom）+ 三团缓慢漂移的柔光（blobA 左上、blobB 右中、blobC 底部）。
/// 画法在 shaders/sky.frag（App）与 styles/base.css .sky（网页）；颜色两端同值（frontend scripts/check-contrast.mjs 查）。
@immutable
class SkyPhase {
  const SkyPhase(this.top, this.bottom, this.blobA, this.blobB, this.blobC);
  final Color top, bottom, blobA, blobB, blobC;

  List<Color> get colors => [top, bottom, blobA, blobB, blobC];

  static SkyPhase lerp(SkyPhase a, SkyPhase b, double t) {
    Color l(Color x, Color y) => Color.lerp(x, y, t)!;
    return SkyPhase(l(a.top, b.top), l(a.bottom, b.bottom), l(a.blobA, b.blobA), l(a.blobB, b.blobB), l(a.blobC, b.blobC));
  }

  @override
  bool operator ==(Object other) =>
      other is SkyPhase && other.top == top && other.bottom == bottom && other.blobA == blobA && other.blobB == blobB && other.blobC == blobC;

  @override
  int get hashCode => Object.hash(top, bottom, blobA, blobB, blobC);
}

/// 一套主题的四个时段；at(钟点) 在相邻两个关键帧之间线性插值（Sky.keyframes），黎明 / 黄昏平滑过渡。
/// 浅色整天都够亮、深色整天都够暗：正文 / 次要字 / 最次要字对壁纸任意一处（全天每 15 分钟 × 底色与三团柔光）
/// 分别 ≥ 4.5 / 4.5 / 3（test/sky_test.dart；网页 check-contrast.mjs 同一采样）。
@immutable
class SkyTable {
  const SkyTable({required this.night, required this.dawn, required this.day, required this.dusk});
  final SkyPhase night, dawn, day, dusk;

  SkyPhase phase(SkyName n) => switch (n) { SkyName.night => night, SkyName.dawn => dawn, SkyName.day => day, SkyName.dusk => dusk };

  /// hour = 0…24（带小数，13.5 = 下午一点半）。
  SkyPhase at(double hour) {
    final h = hour % 24;
    const k = Sky.keyframes;
    for (var i = 0; i < k.length - 1; i++) {
      final (h0, a) = k[i];
      final (h1, b) = k[i + 1];
      if (h <= h1) return a == b || h1 == h0 ? phase(a) : SkyPhase.lerp(phase(a), phase(b), (h - h0) / (h1 - h0));
    }
    return phase(k.last.$2);
  }

  static SkyTable lerp(SkyTable a, SkyTable b, double t) => SkyTable(
        night: SkyPhase.lerp(a.night, b.night, t),
        dawn: SkyPhase.lerp(a.dawn, b.dawn, t),
        day: SkyPhase.lerp(a.day, b.day, t),
        dusk: SkyPhase.lerp(a.dusk, b.dusk, t),
      );

  @override
  bool operator ==(Object other) => other is SkyTable && other.night == night && other.dawn == dawn && other.day == day && other.dusk == dusk;

  @override
  int get hashCode => Object.hash(night, dawn, day, dusk);

  /// 浅色：学 Hark 浅色（顶部天蓝 → 中段淡 → 底部暖米色），夜里是偏紫的灰蓝。v3.3 B2 整体提亮（只抬 OKLab 明度、保色相）：
  /// 次要字 text2 压在顶部 / 夜间最暗处也要 ≥ 4.5，所以顶色比 Hark 浅得多。
  static const light = SkyTable(
    night: SkyPhase(Color(0xFFC7D1F0), Color(0xFFD3D0DD), Color(0xFFC8D1EE), Color(0xFFD4CEEB), Color(0xFFD2CFE0)),
    dawn: SkyPhase(Color(0xFFC0D1FD), Color(0xFFF1D9C6), Color(0xFFC6D1F2), Color(0xFFF7D7BF), Color(0xFFD8CDE7)),
    day: SkyPhase(Color(0xFFADD6FE), Color(0xFFE6DCC2), Color(0xFFB1D6F5), Color(0xFFF4EEDF), Color(0xFFEBDBBF)), // v3.3 验收：底部柔光原 #C0D4E2（冷蓝灰）把暖米底盖成灰绿，改暖沙
    dusk: SkyPhase(Color(0xFFC5D0FB), Color(0xFFEBCDB6), Color(0xFFD2CDF7), Color(0xFFF3D2B4), Color(0xFFD8CDE5)),
  );

  /// 深色：夜里深灰蓝 / 深紫，白天稍微偏蓝一点，始终是暗底；柔光不能太亮（次要字 text2 对柔光峰值也要 ≥ 4.5）。
  static const dark = SkyTable(
    night: SkyPhase(Color(0xFF0B1024), Color(0xFF1C1A33), Color(0xFF2A2F5C), Color(0xFF3A2C55), Color(0xFF1F3346)),
    dawn: SkyPhase(Color(0xFF121A36), Color(0xFF2A2340), Color(0xFF363468), Color(0xFF4E2F51), Color(0xFF2C3A5A)),
    day: SkyPhase(Color(0xFF14213F), Color(0xFF23304A), Color(0xFF223966), Color(0xFF283B59), Color(0xFF2C3A59)),
    dusk: SkyPhase(Color(0xFF141A38), Color(0xFF2B2244), Color(0xFF3E3267), Color(0xFF4F2F4E), Color(0xFF2C395F)),
  );
}

enum SkyName { night, dawn, day, dusk }

/// 流光壁纸的节奏（画法 ui/sky.dart + shaders/sky.frag；驱动 ui/motion.dart SkyClock）。
abstract final class Sky {
  /// 一天里的关键帧（钟点, 时段）：之间线性过渡（= 网页 lib/sky.ts KEYFRAMES）。
  static const keyframes = [
    (0.0, SkyName.night), (4.5, SkyName.night), (6.0, SkyName.dawn), (8.0, SkyName.day),
    (16.5, SkyName.day), (18.5, SkyName.dusk), (20.5, SkyName.night), (24.0, SkyName.night),
  ];

  /// 柔光漂移每帧的间隔：最快的一团约 4 逻辑像素/秒，30 帧/秒每步 < 0.2px，看起来和 60/120 帧一样顺，GPU 空转只有一半或更少。
  static const frame = Duration(milliseconds: 33);

  /// 天色多久按钟点重算一次（不是每帧）。
  static const recolor = Duration(minutes: 1);

  /// 竖向底色的过渡曲线：t = smoothstep(0, 1, y^rampPow)（y = 0 顶 … 1 底），比线性更早变淡（= sky.frag、网页 base.css 的色标）。
  static const rampPow = 0.75;
  static double ramp(double y) {
    final x = math.pow(y.clamp(0.0, 1.0), rampPow).toDouble();
    return x * x * (3 - 2 * x);
  }

  /// ShellPage 上沿渐隐条在 clear → solid 之间的不透明度（1 → 0，smoothstep 缓入缓出；= sky.frag uFade）。
  static double fadeAlpha(double y, double clear, double solid) {
    if (solid <= clear) return y < solid ? 1 : 0;
    final x = ((y - clear) / (solid - clear)).clamp(0.0, 1.0);
    return 1 - x * x * (3 - 2 * x);
  }

  /// 三团柔光的强度（与 sky.frag 里 mix 的系数同值；网页 .sky-blob 的不透明度）。
  static const blobMix = [0.75, 0.65, 0.70];
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
  static const xs = 12.0, sm = 14.0, md = 16.0, lg = 19.0, xl = 30.0, display = 32.0; // v3.1 对着 Hark 真机截图降一档（同一台手机上我们的字大约大 20%）
  static const lineHeight = 1.3; // v2.83 §G：界面文字（标题、行、按钮、标签）紧凑 = 网页 --lh
  static const prose = 1.4; // v3.2 1.6→1.4（Hark 回复行距约 1.33，1.6 让段落发散）； 只给要“读”的正文：聊天回复（AppMarkdown）、记忆摘要、项目档案 = 网页 --lh-prose
}

/// 字重与字距（v2.1「降一档」）：正文 400、标题/按钮/导航 500、只有页面主标题和大数字 600。
/// 小标签（“为你准备”“本月花费”）不加粗，靠更小字号 + 字距 + text3 色区分。页面里不再写 FontWeight.w700。
abstract final class Weights {
  static const body = FontWeight.w400, title = FontWeight.w500, strong = FontWeight.w600;
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
  // v2.99 E4 ImageStack：后面几张第一次出现时从正下方扇开到位（= 网页 --stack-fan / stack-fan keyframes）
  static const stackFan = Duration(milliseconds: 420);
  static const stackTurn = 0.035; // 后面每层旋转多少弧度（约 2°），一层向右一层向左
  static const pillDrop = 8.0; // 标题药丸从上方落下的距离（出现用 spring，过冲约 2–3%）

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
  static const clockTick = Duration(seconds: 1); // “思考中 · 8 秒”这类计时多久跳一次
  static const jobPoll = Duration(seconds: 2); // 聊天里的后台任务卡运行中多久问一次进度
  static const computerPoll = Duration(seconds: 5); // 电脑状态块：有后台任务在跑时多久刷新一次（每次要问 Docker，别太密）
  static const liveRetryMin = Duration(seconds: 1); // 浏览器实时画面断了：1 s 起翻倍重连，封顶 15 s（= 网页 LIVE_RETRY_*）
  static const liveRetryMax = Duration(seconds: 15);
  static const takeoverInput = Duration(milliseconds: 80); // 接管页：拖动/滚动时最多这么久发一次（攒起来发，不是每帧一个请求）
  // v3.0.2 设置搜索直达：被定位的区块数据是异步取的，内容出来（高度 > 0）才滚过去闪；最多等这么久（= 网页 SPOT_WAIT_MS）
  static const spotlightWait = Duration(seconds: 5);
  static const spotlightPoll = Duration(milliseconds: 100);
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

/// 字体（v3.2）：全 App 只有一种字——打包的 MiSans，中文、拉丁、数字同一套字形（= 网页 --font-sans 首位）。
/// 为什么打包：Flutter 在安卓上按名字找不到系统 MiSans，中文会落成思源黑体、拉丁又是另一套（v2.83 的 Inter），
/// 两套字形拼在一起是“不细腻”的头号来源（对照 Hark 真机截图）。子集 = GB2312 + 界面用字，三字重约 5 MB；
/// 子集外的生僻字落到下面的系统字。没有衬线/宋体。
abstract final class Fonts {
  static const sans = 'MiSans';
  static const sansFallback = ['PingFang SC', 'HarmonyOS Sans SC', 'Noto Sans CJK SC', 'Noto Sans SC', ...emoji];
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
  static const stackLayer = 0.22; // 图片一摞后面每多一层淡多少（第一层 0.78、第二层 0.56）
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
  static const rowValueMax = 180.0; // 行尾当前值最宽多少（ListRow.value），再长就省略
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
  static const imageStackMax = 360.0; // v2.99 E4 图片一摞（ImageStack）最宽多宽：单张 / 最上面那张都按 4:3（= 网页 --image-stack-max）
  static const stackPeek = 8.0; // 一摞后面每层向右下露出多少
  static const stackLayers = 2; // 后面最多露几层（再多只算进“N 张”）
  static const productTileMin = 148.0; // 商品宫格每格最窄多宽（手机两列、平板更多列）
  static const offerImageRatio = 2.0; // 主页建议卡顶部配图的宽高比（宽图，不把卡撑太高）
  static const offerImageRatioWide = 2.5; // 窗口 ≥ contentMax（电脑 / 平板）时压扁一点，别一张图占半屏（= 网页 home.css ≥720px 的 5:2，v2.94）
  static const nowDot = 6.0; // 主页“今天”的“现在”标记：细线起头的小圆点
  static const agendaTime = 48.0; // 主页“今天”行首钟点列的宽（HH:MM 等宽数字，上下对齐）
  static const orderThumb = 40.0; // 订单卡每行商品小图的边长
  static const spotlightAt = 0.3; // v3.0 设置搜索直达：被定位的那一项滚到视口从上往下 30% 处（避开顶部标题栏，又不贴底）
  static const spotlightReach = 4000.0; // 有待定位项时列表多建多远的屏外内容（长页底部的区块也能被找到）
  static const seekPagesMax = 60; // 定位消息时最多往上翻多少屏（防止死循环）
}

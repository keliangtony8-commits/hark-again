// 把令牌组装成 Material 主题，并通过 ThemeExtension 暴露 Palette：
// 组件里用 `context.palette.accent`，不直接碰 Color。
import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/foundation.dart' show defaultTargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'tokens.dart';

class PaletteExt extends ThemeExtension<PaletteExt> {
  const PaletteExt(this.p);
  final Palette p;

  @override
  PaletteExt copyWith({Palette? p}) => PaletteExt(p ?? this.p);

  @override
  PaletteExt lerp(PaletteExt? other, double t) => other == null ? this : PaletteExt(Palette.lerp(p, other.p, t));
}

/// 衬线点缀（问候、品牌词、引导卡大标题）：同一字号字重，只换字族。克制使用。
extension SerifX on TextStyle {
  TextStyle get serif => copyWith(fontFamily: Fonts.serif, fontFamilyFallback: Fonts.serifFallback);
}

extension ThemeX on BuildContext {
  Palette get palette => Theme.of(this).extension<PaletteExt>()!.p;
  TextTheme get text => Theme.of(this).textTheme;
}

/// 状态栏和安卓手势条跟随主题：都透明（设计 v2 内容铺满全屏，壁纸透出来），图标深浅相反。
/// AppBar 和 app.dart 的根 AnnotatedRegion 共用这一份，没有 AppBar 的页面（登录）也对。
SystemUiOverlayStyle systemOverlay(Brightness brightness) {
  final icons = brightness == Brightness.dark ? Brightness.light : Brightness.dark;
  return SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: icons,
    statusBarBrightness: brightness, // iOS 用这个
    systemNavigationBarColor: Colors.transparent,
    systemNavigationBarContrastEnforced: false,
    systemNavigationBarDividerColor: Colors.transparent,
    systemNavigationBarIconBrightness: icons,
  );
}

ThemeData buildTheme(Brightness brightness) {
  final p = brightness == Brightness.dark ? Palette.dark : Palette.light;
  final scheme = ColorScheme.fromSeed(seedColor: p.accent, brightness: brightness).copyWith(
    primary: p.accent,
    onPrimary: p.onAccent,
    surface: p.surface,
    onSurface: p.text,
    error: p.danger,
    outline: p.border,
  );
  // 全 App 唯一的字样工厂：平台系统字族（安卓 Roboto / iOS 苹方·SF）+ 表情兜底。
  // AppBar 标题、按钮字这类不经过 textTheme 的样式也必须从这里出，否则它们没有字族、也没有表情兜底。
  final family = Typography.material2021(platform: defaultTargetPlatform).black.bodyMedium?.fontFamily;
  // v2.1：所有数字等宽（tabular figures）——金额、时间、计数上下对齐，跳动时不抖。
  TextStyle t(double size, FontWeight w, [Color? c]) => TextStyle(
      fontSize: size, fontWeight: w, color: c, height: Fs.lineHeight, fontFamily: family, fontFamilyFallback: Fonts.emoji, fontFeatures: const [FontFeature.tabularFigures()]);
  // 衬线“高级感”只给三处：页面主标题（display）、大数字（headline）、引导卡大标题——偏细、略收紧。
  TextStyle serif(double size, FontWeight w, [Color? c]) =>
      t(size, w, c).copyWith(fontFamily: Fonts.serif, fontFamilyFallback: Fonts.serifFallback, height: 1.2, letterSpacing: Weights.displayTracking);

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.bg,
    extensions: [PaletteExt(p)],
    splashFactory: InkSparkle.splashFactory,
    // 字重降一档（v2.1）：正文 400，标题/按钮 500，只有主标题和大数字 600；小标签不加粗、加字距。
    textTheme: TextTheme(
      displayMedium: serif(Fs.display, Weights.title, p.text), // 问候语、“我的”
      displaySmall: serif(Fs.xl, Weights.title, p.text), // 面板/用量卡里的大数字
      headlineMedium: serif(Fs.xl - 4, Weights.title, p.text), // 子页面的关键数字
      titleLarge: t(Fs.lg, Weights.strong, p.text).copyWith(height: 1.3),
      titleMedium: t(Fs.md, Weights.title, p.text),
      titleSmall: t(Fs.sm, Weights.title, p.text),
      bodyLarge: t(Fs.md, Weights.body, p.text),
      bodyMedium: t(Fs.sm, Weights.body, p.text),
      bodySmall: t(Fs.xs + 1, Weights.body, p.text2),
      labelLarge: t(Fs.sm, Weights.title, p.text),
      labelMedium: t(Fs.xs, Weights.title, p.text2),
      labelSmall: t(Fs.xs, Weights.body, p.text3).copyWith(letterSpacing: Weights.labelTracking),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: p.bg,
      surfaceTintColor: Colors.transparent,
      foregroundColor: p.text,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: t(Fs.lg - 2, Weights.strong, p.text).copyWith(height: 1.3),
      systemOverlayStyle: systemOverlay(brightness),
    ),
    // 输入框坐在玻璃上（弹层、登录卡、子页）：底 = tile、边透明；聚焦时变实底 + 强调色边（= 网页版 .form-field）。
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: WidgetStateColor.resolveWith((s) => s.contains(WidgetState.focused) ? p.surface : p.tile),
      hintStyle: t(Fs.md, Weights.body, p.text3),
      contentPadding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.md), borderSide: const BorderSide(color: Colors.transparent)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.md), borderSide: const BorderSide(color: Colors.transparent)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.md), borderSide: BorderSide(color: p.text3, width: 1)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        // 主按钮 = 墨色胶囊（v2.1：强调色不再铺在按钮上）
        backgroundColor: p.ink,
        foregroundColor: p.onInk,
        minimumSize: const Size(0, 48),
        shape: const StadiumBorder(),
        textStyle: t(Fs.md, Weights.title).copyWith(height: 1.2),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        // 选中段 = 墨色（和顶栏导航同一语言），未选 = 玻璃上的 tile
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.ink : p.tile),
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.onInk : p.text2),
        iconColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.onInk : p.text2),
        side: const WidgetStatePropertyAll(BorderSide(color: Colors.transparent)),
        shape: const WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(Radii.md)))),
        textStyle: WidgetStatePropertyAll(t(Fs.sm, Weights.title).copyWith(height: 1.2)),
        animationDuration: Motion.base,
      ),
    ),
    // 自己的对话框全走 ui/sheets.dart 的 showAppDialog（玻璃框）；这里只兜底系统偶尔弹的 Material 对话框。
    // 弹出菜单（PopupMenuButton/showMenu）不用：选项一律走 showActionSheet，架构守卫禁止它们出现。
    dialogTheme: DialogThemeData(
      backgroundColor: p.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Radii.lg)),
    ),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(foregroundColor: p.text, textStyle: t(Fs.sm, Weights.title))),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.text,
        side: BorderSide(color: p.glassBorder),
        shape: const StadiumBorder(),
        minimumSize: const Size(0, 44),
        textStyle: t(Fs.sm, Weights.title),
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.onInk : p.text3),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.ink : p.tile),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: p.text3),
    dividerTheme: DividerThemeData(color: p.border, thickness: 1, space: 1),
    // 弹层的底、圆角、把手全由 ui/glass.dart 的 GlassSheet 画（真模糊玻璃），Material 这层只留透明的壳。
    // 入口只有 ui/sheets.dart 的 showAppSheet / showAppScrollSheet（test/arch_test.dart 守着）。
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Colors.transparent,
      modalBackgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      modalElevation: 0,
      showDragHandle: false,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: p.ink,
      contentTextStyle: t(Fs.sm, Weights.body, p.onInk),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Radii.md)),
    ),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
      TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
    }),
  );
}

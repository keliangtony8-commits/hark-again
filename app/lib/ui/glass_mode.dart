// 材质层的最底一层：只依赖 theme，不依赖任何 ui 零件——motion.dart（骨架屏、进度条）和 glass.dart 都从这里取填充色，
// 不形成循环依赖。glass.dart 会 re-export 本文件，页面照旧只 import glass.dart。
import 'package:flutter/widgets.dart';

import '../theme/app_theme.dart';

/// 减少透明度（无障碍 / 低端机）：solid 时壁纸变纯色、玻璃变实色、所有背景模糊都不画。
class GlassMode extends InheritedWidget {
  const GlassMode({super.key, required this.solid, required super.child});
  final bool solid;

  static bool solidOf(BuildContext context) => context.dependOnInheritedWidgetOfExactType<GlassMode>()?.solid ?? false;

  @override
  bool updateShouldNotify(GlassMode old) => old.solid != solid;
}

/// 玻璃上的三种填充。页面和块里不再手写 `GlassMode.solidOf(context) ? p.surface2 : p.tile` 这类三元式：
///   cardFill  卡片/块本身（永远实色 surface，无描边无高光）
///   tileFill  卡片里再嵌一层的小块：代码块、详情框、胶囊、占位（tile ↔ surface2）
///   hairline  玻璃的 1px 发丝边（glassBorder ↔ border）
extension GlassFills on BuildContext {
  Color get cardFill => palette.surface; // v2.80 F.2：卡片一律不透明近黑/白，玻璃只留给浮层（顶栏、输入胶囊、弹层）
  Color get tileFill => GlassMode.solidOf(this) ? palette.surface2 : palette.tile;
  Color get hairline => GlassMode.solidOf(this) ? palette.border : palette.glassBorder;
}

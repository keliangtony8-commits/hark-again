// 自适应布局：窗口宽度 → 三档（手机 / 小平板·折叠屏竖放 / 平板·折叠屏展开），断点在 tokens.dart 的 Layout。
// 页面只问 context.window，不自己比较宽度。一级导航（设计 v2）各尺寸都是浮动顶栏（shell/top_bar.dart），宽度只影响页面内部（如聊天双栏）。
import 'package:flutter/material.dart';

import '../theme/tokens.dart';

enum WindowSize {
  compact,
  medium,
  expanded;

  static WindowSize fromWidth(double w) => w >= Layout.expandedMin
      ? expanded
      : w >= Layout.mediumMin
          ? medium
          : compact;

  bool get twoPane => this == expanded;
}

extension WindowContext on BuildContext {
  WindowSize get window => WindowSize.fromWidth(MediaQuery.sizeOf(this).width);
}

// 子页面（“我的”里的每一项、项目的档案页、项目聊天）的统一外框（设计 v2）。
// 一级页面是 ShellPage（浮动顶栏），子页面是 SubPage：同一张壁纸（Backdrop），顶上是一条玻璃标题栏，
// 内容从标题栏下面滚过去被模糊——和一级页面的材质、节奏一致，但保留标题 + 返回 + 右侧动作这一信息密度更高的形态。
//
// 让位：Scaffold(extendBodyBehindAppBar) 会把标题栏高度加进 MediaQuery.padding.top，
// 页面里的 PageBody / 聊天列表照常读安全区就会让出来（和 ShellPage、FloatingFooter 是同一个约定）。
// 下拉刷新用 kit 的 PullRefresh：它读同一个让位线，转圈从标题栏下面出来而不是被挡住。
//
// 页面只换 Scaffold → SubPage，不自己写 AppBar 颜色/模糊。新建等页面级动作放 actions（标题栏右侧），不用悬浮钮。减少透明度时标题栏变实色、不模糊。
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';

class SubPage extends StatelessWidget {
  const SubPage({
    super.key,
    required this.title,
    required this.body,
    this.actions = const [],
    this.leading,
    this.leadingWidth,
  });

  final Widget title;
  final Widget body;
  final List<Widget> actions;
  final Widget? leading;

  /// 左侧放了不止一颗钮时（项目对话：返回 + ≡/+）给出宽度。
  final double? leadingWidth;

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent, // 透出壁纸
      extendBodyBehindAppBar: true,
      appBar: GlassAppBar(title: title, actions: actions, leading: leading, leadingWidth: leadingWidth),
      body: body,
    ),
  );
}

/// 玻璃标题栏：真模糊（它是浮层）+ 玻璃着色 + 底部一根发丝线。标题、返回键、动作沿用 AppBarTheme 的字和色。
class GlassAppBar extends StatelessWidget implements PreferredSizeWidget {
  const GlassAppBar({super.key, required this.title, this.actions = const [], this.leading, this.leadingWidth});
  final Widget title;
  final List<Widget> actions;
  final Widget? leading;
  final double? leadingWidth;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    final bar = DecoratedBox(
      decoration: BoxDecoration(
        color: solid ? p.bg : p.glass,
        border: Border(bottom: BorderSide(color: solid ? p.border : p.glassBorder)),
      ),
      child: AppBar(
        title: title,
        leading: leading,
        leadingWidth: leadingWidth,
        actions: [
          ...actions,
          if (actions.isNotEmpty) const SizedBox(width: Sp.x1),
        ],
        backgroundColor: Colors.transparent,
        scrolledUnderElevation: 0,
      ),
    );
    if (solid) return bar;
    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: Glass.blur, sigmaY: Glass.blur),
        child: bar,
      ),
    );
  }
}

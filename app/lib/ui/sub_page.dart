// 子页面（“我的”里的每一项、项目的档案页、项目聊天）的统一外框（设计 v2）。
// 一级页面是 ShellPage（浮动顶栏），子页面是 SubPage：同一张壁纸（Backdrop），顶上是一颗悬浮玻璃标题胶囊（v3.5 照 Hark，
// = 网页 .page-head）：和一级页顶栏同位置、同高、同材质，只是里面放 返回 + 标题 + 右侧动作。
// 胶囊四周露出来的那一截由 BackdropFade 渐隐带盖住（和 ShellPage 同参数），滚上去的内容不和标题叠字。
//
// 让位：Scaffold(extendBodyBehindAppBar) 会把标题栏高度（= Layout.shellTop，和一级页同一条让位线）加进 MediaQuery.padding.top，
// 页面里的 PageBody / 聊天列表照常读安全区就会让出来（和 ShellPage、FloatingFooter 是同一个约定）。
// 下拉刷新用 kit 的 PullRefresh：它读同一个让位线，转圈从标题栏下面出来而不是被挡住。
//
// 页面只换 Scaffold → SubPage，不自己写 AppBar 颜色/模糊。新建等页面级动作放 actions（胶囊右侧），不用悬浮钮。减少透明度时胶囊变实色、不模糊。
// 自带整屏不透明壁纸：在外壳分支里打开、进场完成后，外壳底下那层壁纸暂停（SkyCover，规则见 ui/sky.dart）。
// 毛玻璃分组（v3.3）：整页一个 BackdropGroup，标题胶囊和页里的浮层（GlassSurface blur）共享一次取背景。
//   Scaffold 先画 body（含渐隐带）再画标题胶囊，胶囊底下的内容在 body 里已经画完，所以谁先取背景都对（规则见 glass.dart 文件头）。
import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'glass.dart';
import 'sky.dart';

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
  Widget build(BuildContext context) => SkyCover(
    child: Backdrop(
      child: BlurGroup(
        child: Scaffold(
          backgroundColor: Colors.transparent, // 透出壁纸
          extendBodyBehindAppBar: true,
          appBar: GlassAppBar(title: title, actions: actions, leading: leading, leadingWidth: leadingWidth),
          body: Builder(builder: (context) {
            // Scaffold 已把胶囊让位加进 padding.top：inset = 状态栏 + Layout.shellTop
            final top = MediaQuery.viewPaddingOf(context).top;
            final solid = BackdropFade.solidOf(MediaQuery.paddingOf(context).top);
            return Stack(children: [
              Positioned.fill(child: body),
              Positioned(top: 0, left: 0, right: 0, height: solid, child: BackdropFade(clear: BackdropFade.clearOf(top, 0), solid: solid)),
            ]);
          }),
        ),
      ),
    ),
  );
}

/// 悬浮玻璃标题胶囊（v3.5，= 网页 .page-head）：一级页顶栏同一个位置、高度和材质（GlassSurface blur + 全圆角），
/// 里面是 AppBar（返回、标题、动作沿用 AppBarTheme 的字和色）。
class GlassAppBar extends StatelessWidget implements PreferredSizeWidget {
  const GlassAppBar({super.key, required this.title, this.actions = const [], this.leading, this.leadingWidth});
  final Widget title;
  final List<Widget> actions;
  final Widget? leading;
  final double? leadingWidth;

  @override
  Size get preferredSize => const Size.fromHeight(Layout.shellTop);

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    return Padding(
      padding: EdgeInsets.fromLTRB(pad.left + Layout.gutter, pad.top + Layout.topBarTop, pad.right + Layout.gutter, 0),
      child: Align(
        alignment: Alignment.topCenter,
        child: SizedBox(
          height: Layout.topBar,
          child: GlassSurface(
            blur: true,
            radius: Radii.full,
            child: AppBar(
              primary: false,
              toolbarHeight: Layout.topBar,
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
          ),
        ),
      ),
    );
  }
}

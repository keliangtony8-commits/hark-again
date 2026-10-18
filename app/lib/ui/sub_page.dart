// 子页面（“我的”里的每一项、项目的档案页、项目聊天）的统一外框（设计 v2）。
// 一级页面是 ShellPage（浮动顶栏），子页面是 SubPage：同一张壁纸（Backdrop），顶上没有标题栏（v3.5 照 Hark 钱包 / 安全 / 系统偏好设置截图，
// = 网页 .page-head）：左边一颗独立的圆玻璃返回钮（= 一级页顶栏圆钮、“我的”页返回钮），标题是居中的裸字，右侧动作收进一颗玻璃胶囊；
// 和一级页顶栏同一行位置、同高。四周露出来的那一截由 BackdropFade 渐隐带盖住（和 ShellPage 同参数），滚上去的内容不和标题叠字。
//
// 让位：Scaffold(extendBodyBehindAppBar) 会把标题栏高度（= Layout.shellTop，和一级页同一条让位线）加进 MediaQuery.padding.top，
// 页面里的 PageBody / 聊天列表照常读安全区就会让出来（和 ShellPage、FloatingFooter 是同一个约定）。
// 下拉刷新用 kit 的 PullRefresh：它读同一个让位线，转圈从标题栏下面出来而不是被挡住。
//
// 页面只换 Scaffold → SubPage，不自己写标题栏。新建等页面级动作放 actions（右侧玻璃胶囊），不用悬浮钮。减少透明度时圆钮 / 胶囊变实色、不模糊。
// 自带整屏不透明壁纸：在外壳分支里打开、进场完成后，外壳底下那层壁纸暂停（SkyCover，规则见 ui/sky.dart）。
// 毛玻璃分组（v3.3）：整页一个 BackdropGroup，返回钮 / 动作胶囊和页里的浮层（GlassSurface blur）共享一次取背景。
//   Scaffold 先画 body（含渐隐带）再画标题行，圆钮底下的内容在 body 里已经画完，所以谁先取背景都对（规则见 glass.dart 文件头）。
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
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
    this.trailing,
  });

  final Widget title;
  final Widget body;
  final List<Widget> actions;

  /// 标题行右侧单独一颗钮（v3.5.1 我的电脑的“重启” GlassIconButton，和左边返回钮对称）；给了就不画 [actions] 胶囊。
  final Widget? trailing;
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
          appBar: GlassAppBar(title: title, actions: actions, leading: leading, leadingWidth: leadingWidth, trailing: trailing),
          body: Builder(builder: (context) {
            // Scaffold 已把胶囊让位加进 padding.top：inset = 状态栏 + Layout.shellTop
            final top = MediaQuery.viewPaddingOf(context).top;
            // v3.5.1：完全遮住到标题行底边（返回钮 / 标题下面绝不透出内容），渐显到内容静止上沿（让位线 + Sp.x2）。
            final clear = top + Layout.topBarTop + Layout.topBar;
            final solid = MediaQuery.paddingOf(context).top + Sp.x2;
            return Stack(children: [
              Positioned.fill(child: body),
              Positioned(top: 0, left: 0, right: 0, height: solid, child: BackdropFade(clear: clear, solid: solid)),
            ]);
          }),
        ),
      ),
    ),
  );
}

/// 子页标题行（v3.5 照 Hark）：[圆玻璃返回钮] 居中裸字标题 [动作玻璃胶囊]，没有整条栏、没有标题底。
/// 位置 = 一级页顶栏（gutter / topBarTop / topBar 高）；让位 = Layout.shellTop（同一条让位线）。
/// 返回钮图标 = ‹（arrow_back_ios_new，= Hark / 网页 IconBack，“我的”页同款）；规则跟 AppBar：给了 [leading] 用它，否则路由能退（impliesAppBarDismissal）才出，点了 maybePop。
/// 标题用 NavigationToolbar 真居中（按整屏宽居中，两侧放不下时自动让开、不和钮叠）。
class GlassAppBar extends StatelessWidget implements PreferredSizeWidget {
  const GlassAppBar({super.key, required this.title, this.actions = const [], this.leading, this.leadingWidth, this.trailing});
  final Widget title;
  final Widget? trailing;
  final List<Widget> actions;
  final Widget? leading;
  final double? leadingWidth;

  @override
  Size get preferredSize => const Size.fromHeight(Layout.shellTop);

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    final back = leading ??
        ((ModalRoute.of(context)?.impliesAppBarDismissal ?? false)
            ? GlassIconButton(icon: Icons.arrow_back_ios_new_rounded, tooltip: '返回', onTap: () => Navigator.of(context).maybePop())
            : null);
    final style = Theme.of(context).appBarTheme.titleTextStyle ?? Theme.of(context).textTheme.titleLarge;
    return Padding(
      padding: EdgeInsets.fromLTRB(pad.left + Layout.gutter, pad.top + Layout.topBarTop, pad.right + Layout.gutter, 0),
      child: Align(
        alignment: Alignment.topCenter,
        child: SizedBox(
          height: Layout.topBar,
          child: NavigationToolbar(
            leading: back == null || leadingWidth == null ? back : SizedBox(width: leadingWidth, child: Align(alignment: Alignment.centerLeft, child: back)),
            middle: Semantics(
              header: true,
              child: DefaultTextStyle.merge(style: style, maxLines: 1, overflow: TextOverflow.ellipsis, child: title),
            ),
            trailing: trailing != null || actions.isEmpty
                ? trailing
                : SizedBox(
                    height: Layout.topBar,
                    child: GlassSurface(
                      blur: true,
                      radius: Radii.full,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
                        child: IconTheme.merge(
                          data: IconThemeData(color: context.palette.text),
                          child: Row(mainAxisSize: MainAxisSize.min, children: actions),
                        ),
                      ),
                    ),
                  ),
            middleSpacing: Sp.x3,
          ),
        ),
      ),
    );
  }
}

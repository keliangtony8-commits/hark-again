// 一级页面（主页/聊天/项目）的外框：让出浮动顶栏的高度、在顶栏左侧画本页的上下文按钮。
// 让位的方式是把顶栏高度加进 MediaQuery.padding.top：页面里的 PageBody / 列表照常读安全区，
// 内容可以从顶栏下面滚过去（被玻璃模糊），而不是被一块实心色挡住。
// header：紧贴顶栏下面的一行（主聊天的标题胶囊），高度固定为 headerHeight，同样计入让位。
import 'package:flutter/material.dart';

import '../theme/tokens.dart';

class ShellPage extends StatelessWidget {
  const ShellPage({super.key, required this.child, this.lead, this.header, this.headerHeight = 0});
  final Widget child;
  final Widget? lead;
  final Widget? header;
  final double headerHeight;

  /// 一级页面内容顶部要让出的总高度（状态栏 + 顶栏 + header）。
  static double insetOf(BuildContext context, {double header = 0}) =>
      MediaQuery.paddingOf(context).top + Layout.shellTop + (header > 0 ? header + Sp.x2 : 0);

  /// header 那一行的顶边：紧贴顶栏下面（比内容让位线更靠上，它本身也是浮层）。
  static const _headerTop = Layout.topBarTop + Layout.topBar + Sp.x2;

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final top = mq.padding.top;
    final headerSpace = header == null ? 0.0 : headerHeight + Sp.x2;
    return Stack(children: [
      MediaQuery(
        data: mq.copyWith(padding: mq.padding.copyWith(top: top + Layout.shellTop + headerSpace)),
        child: child,
      ),
      if (header != null)
        Positioned(
          top: top + _headerTop,
          left: mq.padding.left + Layout.gutter,
          right: mq.padding.right + Layout.gutter,
          height: headerHeight,
          child: header!,
        ),
      if (lead != null)
        Positioned(top: top + Layout.topBarTop, left: mq.padding.left + Layout.gutter, child: lead!),
    ]);
  }
}

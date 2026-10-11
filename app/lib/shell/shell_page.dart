// 一级页面（主页/聊天/项目）的外框：让出浮动顶栏的高度、在顶栏左侧画本页的上下文按钮。
// 让位的方式是把顶栏高度加进 MediaQuery.padding.top：页面里的 PageBody / 列表照常读安全区，
// 内容可以从顶栏下面滚过去（被玻璃模糊），而不是被一块实心色挡住。
// header：紧贴顶栏下面的一行（主聊天的标题），高度固定为 headerHeight，同样计入让位。
// 滚上去的内容在让位线上方渐隐（TopFade）：顶栏是悬浮胶囊、两边是空的，不渐隐的话消息会和
//   头像、标题叠在一起（v0.80 修：聊天标题“额度”和滚上去的消息叠字）。有 header 时整行 header 下面才开始显，
//   到让位线下 Layout.topFadeRamp 才全显（缓入，v0.92：墨色气泡不再切出硬边）。
import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import '../ui/kit.dart';

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

  /// 内容完全透明到哪一行（不含状态栏的部分 + 状态栏 [top]）：没有 header 时到顶栏中线（胶囊两侧露一点点渐隐），
  /// 有 header 时到 header 底边（标题下面绝不叠字）。
  static double fadeClearOf(double top, double headerHeight) =>
      top + (headerHeight > 0 ? _headerTop + headerHeight : Layout.topBarTop + Layout.topBar / 2);

  /// 内容从哪一行起完全显出来：让位线 [inset] 再往下 [Layout.topFadeRamp]（缓入渐显，不切硬边）。
  static double fadeSolidOf(double inset) => inset + Layout.topFadeRamp;

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final top = mq.padding.top;
    final headerSpace = header == null ? 0.0 : headerHeight + Sp.x2;
    final inset = top + Layout.shellTop + headerSpace;
    return Stack(children: [
      TopFade(
        clear: fadeClearOf(top, header == null ? 0 : headerHeight),
        solid: fadeSolidOf(inset),
        child: MediaQuery(
          data: mq.copyWith(padding: mq.padding.copyWith(top: inset)),
          child: child,
        ),
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

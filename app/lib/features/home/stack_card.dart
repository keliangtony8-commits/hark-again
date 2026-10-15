// 主页卡片栈里的一张卡（v2.78 Home 重做）：同宽、同圆角、同底色、等距，标题在卡里（主页不再有小节标题）。
// 主页上除了“要你处理的建议卡”（action_card.dart，自带按钮排）以外，今天 / 面板 / 收件箱 / 连接引导都用它，
// 所以卡与卡的节奏只在这一处定：卡间距 Layout.cardGap，内边距 Layout.cardPad，标题一档 titleMedium。
// 两种身体：[child] = 普通内容（面板的块、引导卡的文字）；[rows] = 一列 ListRow（今天、收件箱），行贴卡边、
// 行内文字与标题对齐（行自带 Sp.x4 内边距，外面再补 cardPad − Sp.x4）。
import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';

class StackCard extends StatelessWidget {
  const StackCard({super.key, this.title, this.trailing, this.child, this.rows, this.separator})
      : assert(child != null || rows != null);
  final String? title;

  /// 标题行尾：一句小字（摘要、更新时间）或几颗小图标钮。
  final Widget? trailing;
  final Widget? child;
  final List<Widget>? rows;

  /// 第 i 行（i ≥ 1）上方的分隔；null 用默认细线（缩进到行首图标之后）。
  final Widget? Function(int i)? separator;

  static const _rowInset = Layout.cardPad - Sp.x4;

  @override
  Widget build(BuildContext context) {
    final rows = this.rows;
    return Padding(
      padding: const EdgeInsets.only(bottom: Layout.cardGap),
      child: GlassSurface(
        shadow: false,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(Radii.card),
          child: Material(
            type: MaterialType.transparency, // 行里的 InkWell 水波纹画在玻璃上
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (title != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(Layout.cardPad, Sp.x2, Sp.x2, 0),
                  child: SizedBox(
                    height: A11y.minTap,
                    child: Row(children: [
                      Expanded(child: Text(title!, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
                      ?trailing,
                    ]),
                  ),
                ),
              if (rows != null)
                Padding(
                  padding: EdgeInsets.fromLTRB(_rowInset, title == null ? Sp.x1 : 0, _rowInset, Sp.x1),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    for (var i = 0; i < rows.length; i++) ...[
                      if (i > 0) separator?.call(i) ?? Divider(indent: Sp.x4 + Layout.rowIcon + Sp.x4, endIndent: 0, color: context.hairline),
                      rows[i],
                    ],
                  ]),
                ),
              if (child != null)
                Padding(
                  padding: EdgeInsets.fromLTRB(Layout.cardPad, title == null ? Layout.cardPad : Sp.x1, Layout.cardPad, Layout.cardPad),
                  child: child,
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 卡头行尾的一句小字（今天的摘要、面板更新时间）：换字时旧字上滑淡出、新字浮上来。
class CardNote extends StatelessWidget {
  const CardNote(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(right: Sp.x3),
        child: SwapSwitcher(child: Text(text, key: ValueKey(text), style: context.text.labelSmall)),
      );
}

// 引用回复（§J / §C）的两处显示，共用一种样子：细竖线 + 一行灰字原文。
// - QuoteLine：气泡顶上那一行（折线连接符 + 原文截断），点一下滚回原消息并闪一下（ChatView._reveal）；原消息已删 = “原消息已删除”，点不了。
// - QuoteBar：输入胶囊顶部的引用条（“回复”后出现）：竖线 + 原文一行 + ✕；和编辑条同一个位置、同一种出场。
// 后台结果自动引用（§C 下一步）也画 QuoteLine，不另造组件。
import 'package:flutter/material.dart';

import '../../models/message.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';

class QuoteLine extends StatelessWidget {
  const QuoteLine(this.quote, {super.key, this.onTap, this.alignEnd = false});
  final MessageQuote quote;
  final VoidCallback? onTap;
  final bool alignEnd;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = Padding(
      padding: const EdgeInsets.fromLTRB(Sp.x3, 0, Sp.x3, Sp.x1),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.subdirectory_arrow_right_rounded, size: 14, color: p.text3),
        const SizedBox(width: Sp.x1),
        Flexible(
          child: Text(quote.line,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: context.text.bodySmall?.copyWith(color: p.text3, fontStyle: quote.missing ? FontStyle.italic : null)),
        ),
      ]),
    );
    final tap = quote.missing || onTap == null ? row : Pressable(onTap: onTap, semanticLabel: '回到被引用的消息', child: row);
    return Align(alignment: alignEnd ? Alignment.centerRight : Alignment.centerLeft, child: tap);
  }
}

class QuoteBar extends StatelessWidget {
  const QuoteBar(this.quote, {super.key, this.onCancel});
  final MessageQuote quote;
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.only(left: Sp.x4, top: Sp.x1),
        child: Row(children: [
          Container(width: 2, height: Fs.md, decoration: BoxDecoration(color: p.text3, borderRadius: BorderRadius.circular(Radii.full))),
          const SizedBox(width: Sp.x2),
          Expanded(
            child: Text(quote.line,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(color: p.text2)),
          ),
          IconButton(
            onPressed: onCancel,
            tooltip: '不回复这条',
            iconSize: 18,
            visualDensity: VisualDensity.compact,
            icon: Icon(Icons.close_rounded, color: p.text3),
          ),
        ]),
      ),
    );
  }
}

// 全应用唯一的 Markdown 排版：聊天文字块、项目档案等都用它，字号/颜色只从主题和 tokens 取。
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../core/links.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';

class AppMarkdown extends StatelessWidget {
  const AppMarkdown(this.data, {super.key, this.selectable = true});
  final String data;
  final bool selectable;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = context.text.bodyLarge!;
    return MarkdownBody(
      data: data,
      selectable: selectable,
      onTapLink: (_, href, _) => href != null ? openUrl(href) : null,
      // 可选中文字会吃掉点按手势：外层（聊天回复卡）要知道“点了正文”，就挂一个 TextTapScope
      onTapText: selectable ? TextTapScope.of(context) : null,
      styleSheet: MarkdownStyleSheet(
        p: base,
        a: base.copyWith(color: p.accent, decoration: TextDecoration.underline, decorationColor: p.accent.withValues(alpha: 0.4)),
        // 标题层级（v1.04）：h1 = 文档标题，h2 = 段落小标题（正文同号、加一档字重），h3 = 二级色小字。
        // 原先 h2 18/600 与卡片标题 20/600 挤成一档，段与段之间也没有呼吸。小标题上方留 Sp.x3，和正文段距分开。
        h1: context.text.titleLarge,
        h1Padding: const EdgeInsets.only(top: Sp.x3),
        h2: context.text.titleMedium,
        h2Padding: const EdgeInsets.only(top: Sp.x3),
        h3: context.text.titleSmall?.copyWith(color: p.text2),
        h3Padding: const EdgeInsets.only(top: Sp.x2),
        strong: base.copyWith(fontWeight: Weights.strong),
        listBullet: base.copyWith(color: p.text2),
        blockquote: base.copyWith(color: p.text2),
        blockquoteDecoration: BoxDecoration(
          border: Border(left: BorderSide(color: context.hairline, width: 3)),
        ),
        code: TextStyle(fontFamily: 'monospace', fontSize: Fs.sm, backgroundColor: context.tileFill, color: p.text),
        codeblockDecoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
        tableBorder: TableBorder.all(color: context.hairline),
        tableHead: base.copyWith(fontWeight: Weights.strong),
        tableBody: context.text.bodyMedium,
        horizontalRuleDecoration: BoxDecoration(
          border: Border(top: BorderSide(color: p.border)),
        ),
      ),
    );
  }
}

/// 给子树里的可选中正文（AppMarkdown）一个“点了文字”的回调。
/// 可选中文字自己认领点按（放光标/清选区），外层 GestureDetector 收不到；挂这个就能收到，长按选字不受影响。
/// 现在只有聊天里较早的回复用它：点一下回复卡露出操作行（features/chat/message_view.dart）。
class TextTapScope extends InheritedWidget {
  const TextTapScope({super.key, required this.onTap, required super.child});
  final VoidCallback onTap;

  static VoidCallback? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<TextTapScope>()?.onTap;

  @override
  bool updateShouldNotify(TextTapScope old) => old.onTap != onTap;
}

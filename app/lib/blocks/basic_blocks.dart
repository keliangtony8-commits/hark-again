// 只读展示类的块：文字、链接、表格、代码、关键数字。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/links.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/markdown.dart';

class TextBlockView extends StatelessWidget {
  const TextBlockView(this.block, {super.key});
  final TextBlock block;

  @override
  Widget build(BuildContext context) => AppMarkdown(block.text);
}

class LinksBlockView extends StatelessWidget {
  const LinksBlockView(this.block, {super.key});
  final LinksBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(
      children: [
        for (final l in block.items)
          Padding(
            padding: const EdgeInsets.only(bottom: Sp.x2),
            child: AppCard(
              onTap: () => openUrl(l.url),
              padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
              child: Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Image.network(
                      'https://icons.duckduckgo.com/ip3/${hostOf(l.url)}.ico',
                      width: 20,
                      height: 20,
                      errorBuilder: (_, _, _) => Icon(Icons.link_rounded, size: 20, color: p.text3),
                    ),
                  ),
                  const SizedBox(width: Sp.x3),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(l.title ?? l.label ?? hostOf(l.url), style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                        Text(l.label != null && l.title != null ? '${l.label} · ${hostOf(l.url)}' : hostOf(l.url), style: context.text.bodySmall),
                      ],
                    ),
                  ),
                  Icon(Icons.north_east_rounded, size: 18, color: p.text3),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class TableBlockView extends StatelessWidget {
  const TableBlockView(this.block, {super.key});
  final TableBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    Widget cell(String s, {bool head = false}) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2 + 2),
      child: Text(s, style: head ? context.text.labelLarge?.copyWith(color: p.text2) : context.text.bodyMedium),
    );
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (block.title != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, 0),
              child: Text(block.title!, style: context.text.titleMedium),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.all(Sp.x1),
            child: Table(
              defaultColumnWidth: const IntrinsicColumnWidth(),
              border: TableBorder(horizontalInside: BorderSide(color: p.border)),
              children: [
                TableRow(children: [for (final c in block.columns) cell(c, head: true)]),
                for (final r in block.rows) TableRow(children: [for (var i = 0; i < block.columns.length; i++) cell(i < r.length ? r[i] : '')]),
              ],
            ),
          ),
          if (block.note != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x3),
              child: Text(block.note!, style: context.text.bodySmall),
            ),
        ],
      ),
    );
  }
}

class CodeBlockView extends StatelessWidget {
  const CodeBlockView(this.block, {super.key});
  final CodeBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(
        color: context.tileFill, // 坐在 AI 回复的玻璃卡里：再深一层的小块，不再是实色板
        borderRadius: BorderRadius.circular(Radii.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x1, Sp.x1, 0),
            child: Row(
              children: [
                Expanded(child: Text(block.title ?? block.language, style: context.text.labelSmall)),
                IconButton(
                  icon: Icon(Icons.copy_rounded, size: 18, color: p.text3),
                  tooltip: '复制',
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: block.source));
                    showToast(context, '已复制');
                  },
                ),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x4),
            child: SelectableText(
              block.source,
              style: TextStyle(fontFamily: 'monospace', fontSize: Fs.sm, height: 1.5, color: p.text),
            ),
          ),
        ],
      ),
    );
  }
}

/// 关键数字：每项一块 ValueTile（标签 + 大数字 + 一句变化）。
/// 列数按宽度和数值长短定：数值都很短（“26°C”“17:42”）时手机上两列并排，长的（“¥1,280.00 / 月”）一项一行，宽屏最多三列。
class StatsBlockView extends StatelessWidget {
  const StatsBlockView(this.block, {super.key});
  final StatsBlock block;

  static const _shortValue = 8;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, c) {
      final n = block.items.length;
      final short = block.items.every((i) => i.value.characters.length <= _shortValue);
      final cols = (c.maxWidth >= Layout.contentMax * 0.66 ? 3 : (short ? 2 : 1)).clamp(1, n);
      final w = (c.maxWidth - Sp.x2 * (cols - 1)) / cols;
      return Wrap(
        spacing: Sp.x2,
        runSpacing: Sp.x2,
        children: [
          for (final i in block.items)
            SizedBox(
              width: w,
              child: ValueTile(label: i.label, value: i.value, note: i.note),
            ),
        ],
      );
    },
  );
}

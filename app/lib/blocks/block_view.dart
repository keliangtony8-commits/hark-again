// 块渲染入口：sealed class + switch，新增块类型时编译器会提醒这里漏了哪种。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../theme/tokens.dart';
import 'basic_blocks.dart';
import 'browser_block.dart';
import 'content_blocks.dart';
import 'interactive_blocks.dart';
import 'memory_block.dart';

class BlockView extends StatelessWidget {
  const BlockView(this.block, {super.key});
  final Block block;

  @override
  Widget build(BuildContext context) => switch (block) {
        TextBlock b => TextBlockView(b),
        LinksBlock b => LinksBlockView(b),
        TableBlock b => TableBlockView(b),
        CodeBlock b => CodeBlockView(b),
        FileBlock b => FileBlockView(b),
        ApprovalBlock b => ApprovalBlockView(b),
        BrowserBlock b => BrowserBlockView(b),
        PageBlock b => PageBlockView(b),
        StatsBlock b => StatsBlockView(b),
        MemoryBlock b => MemoryBlockView(b),
        DraftBlock b => DraftBlockView(b),
        SummaryBlock b => SummaryBlockView(b),
        ImagesBlock b => ImagesBlockView(b),
        UnknownBlock _ => const SizedBox.shrink(), // 新版服务器的新卡片：旧 App 安静忽略
      };
}

class BlockList extends StatelessWidget {
  const BlockList(this.blocks, {super.key});
  final List<Block> blocks;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < blocks.length; i++) ...[
            if (i > 0) const SizedBox(height: Sp.x3),
            BlockView(blocks[i]),
          ],
        ],
      );
}
